# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Optional

from .base import SignProvider, SignResult
from .registry import SignProviderRegistry
from .service import SignService

_registry = SignProviderRegistry()
_auto_registered = False


def _auto_register():
    """懒加载自动注册所有内置 Provider。"""
    from .providers.xhs_provider import XhsSignProvider
    from .providers.douyin_provider import DouyinSignProvider
    from .providers.zhihu_provider import ZhihuSignProvider
    from .providers.bilibili_provider import BilibiliSignProvider
    from .providers.noop_provider import NoOpSignProvider

    for cls in [XhsSignProvider, DouyinSignProvider, ZhihuSignProvider, NoOpSignProvider]:
        _registry.register(cls())
    # Bilibili 需要运行时密钥，注册一个占位实例
    _registry.register(BilibiliSignProvider())


def get_sign_service(platform: str, remote_url: Optional[str] = None) -> SignService:
    """获取指定平台的签名服务实例。

    Args:
        platform: 平台标识，如 'xhs', 'douyin', 'zhihu', 'bilibili', 'noop'
        remote_url: 可选的远程签名服务地址
    """
    global _auto_registered
    if not _auto_registered:
        _auto_register()
        _auto_registered = True

    # 读取配置中的远程签名设置
    if remote_url is None:
        try:
            from config.base_config import SIGN_SERVICE_MODE, SIGN_SERVICE_URL
            if SIGN_SERVICE_MODE == "remote" and SIGN_SERVICE_URL:
                remote_url = SIGN_SERVICE_URL
        except ImportError:
            pass

    provider = _registry.require(platform)
    return SignService(provider, remote_url=remote_url)


def register_provider(provider: SignProvider) -> None:
    """手动注册或替换签名提供者。"""
    global _auto_registered
    if not _auto_registered:
        _auto_register()
        _auto_registered = True
    _registry.register(provider)


__all__ = [
    "SignProvider",
    "SignResult",
    "SignService",
    "SignProviderRegistry",
    "get_sign_service",
    "register_provider",
]
