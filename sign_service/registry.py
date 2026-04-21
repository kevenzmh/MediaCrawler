# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Dict, Optional

from .base import SignProvider


class SignProviderRegistry:
    """签名提供者注册表，按平台名查找 Provider。"""

    def __init__(self):
        self._providers: Dict[str, SignProvider] = {}

    def register(self, provider: SignProvider) -> None:
        self._providers[provider.platform] = provider

    def unregister(self, platform: str) -> None:
        self._providers.pop(platform, None)

    def get(self, platform: str) -> Optional[SignProvider]:
        return self._providers.get(platform)

    def require(self, platform: str) -> SignProvider:
        provider = self._providers.get(platform)
        if not provider:
            raise KeyError(f"No sign provider registered for platform: {platform}")
        return provider

    def list_platforms(self) -> list:
        return list(self._providers.keys())
