# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sign_service.base import SignProvider, SignResult
from sign_service.registry import SignProviderRegistry
from sign_service.service import SignService
from sign_service.providers.noop_provider import NoOpSignProvider
from sign_service.providers.bilibili_provider import BilibiliSignProvider


class TestSignResult:
    def test_default_empty(self):
        result = SignResult()
        assert result.headers == {}
        assert result.params == {}
        assert not result.has_headers
        assert not result.has_params

    def test_with_headers(self):
        result = SignResult(headers={"X-S": "abc"})
        assert result.has_headers
        assert not result.has_params

    def test_with_params(self):
        result = SignResult(params={"a_bogus": "xyz"})
        assert not result.has_headers
        assert result.has_params

    def test_with_both(self):
        result = SignResult(headers={"k": "v"}, params={"p": "q"})
        assert result.has_headers
        assert result.has_params


class TestSignProviderRegistry:
    def test_register_and_get(self):
        registry = SignProviderRegistry()
        provider = NoOpSignProvider()
        registry.register(provider)
        assert registry.get("noop") is provider

    def test_get_unregistered(self):
        registry = SignProviderRegistry()
        assert registry.get("nonexistent") is None

    def test_require_unregistered_raises(self):
        registry = SignProviderRegistry()
        with pytest.raises(KeyError, match="No sign provider registered"):
            registry.require("nonexistent")

    def test_unregister(self):
        registry = SignProviderRegistry()
        registry.register(NoOpSignProvider())
        registry.unregister("noop")
        assert registry.get("noop") is None

    def test_list_platforms(self):
        registry = SignProviderRegistry()
        registry.register(NoOpSignProvider())
        registry.register(BilibiliSignProvider())
        assert set(registry.list_platforms()) == {"noop", "bilibili"}


class TestNoOpSignProvider:
    def test_platform(self):
        provider = NoOpSignProvider()
        assert provider.platform == "noop"

    def test_sign_returns_empty(self):
        provider = NoOpSignProvider()
        result = provider.sign("/api/test")
        assert result.headers == {}
        assert result.params == {}


class TestBilibiliSignProvider:
    def test_platform(self):
        provider = BilibiliSignProvider()
        assert provider.platform == "bilibili"

    def test_sign_without_keys_returns_empty(self):
        provider = BilibiliSignProvider()
        result = provider.sign("/wbi", params={"foo": "bar"})
        assert result.params == {}

    def test_update_keys(self):
        provider = BilibiliSignProvider()
        # BilibiliSign requires img_key + sub_key length >= 64
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        provider.update_keys(img_key, sub_key)
        result = provider.sign("/wbi", params={"foo": "bar"})
        assert "w_rid" in result.params
        assert "wts" in result.params


class TestSignService:
    def test_local_sign(self):
        provider = NoOpSignProvider()
        service = SignService(provider)
        result = service.sign("/api/test")
        assert result.headers == {}
        assert result.params == {}

    def test_local_sign_with_bilibili(self):
        provider = BilibiliSignProvider()
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        provider.update_keys(img_key, sub_key)
        service = SignService(provider)
        result = service.sign("/wbi", params={"foo": "bar"})
        assert "w_rid" in result.params

    def test_remote_url_property(self):
        service = SignService(NoOpSignProvider(), remote_url="http://localhost:8080/sign")
        assert service.remote_url == "http://localhost:8080/sign"

    def test_provider_property(self):
        provider = NoOpSignProvider()
        service = SignService(provider)
        assert service.provider is provider


class TestGetSignService:
    """Test that get_sign_service returns correctly configured SignService instances."""

    def test_get_noop_service(self):
        from sign_service import get_sign_service
        service = get_sign_service("noop")
        assert isinstance(service, SignService)
        assert service.provider.platform == "noop"

    def test_get_bilibili_service(self):
        from sign_service import get_sign_service
        service = get_sign_service("bilibili")
        assert service.provider.platform == "bilibili"

    def test_get_nonexistent_raises(self):
        from sign_service import get_sign_service
        with pytest.raises(KeyError):
            get_sign_service("nonexistent_platform")


class TestRegisterProvider:
    def test_register_custom_provider(self):
        from sign_service import register_provider, get_sign_service

        class CustomProvider(SignProvider):
            @property
            def platform(self):
                return "custom_test"

            def sign(self, uri, **kwargs):
                return SignResult(headers={"X-Custom": "test"})

        register_provider(CustomProvider())
        service = get_sign_service("custom_test")
        result = service.sign("/api/test")
        assert result.headers == {"X-Custom": "test"}
