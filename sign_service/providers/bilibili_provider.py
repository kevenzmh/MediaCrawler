# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Dict, Optional

from ..base import SignProvider, SignResult


class BilibiliSignProvider(SignProvider):
    """B站签名提供者，包装 BilibiliSign。

    B站签名需要运行时获取的 img_key 和 sub_key，
    通过 update_keys() 方法更新。
    """

    def __init__(self, img_key: str = "", sub_key: str = ""):
        self._img_key = img_key
        self._sub_key = sub_key

    @property
    def platform(self) -> str:
        return "bilibili"

    def update_keys(self, img_key: str, sub_key: str) -> None:
        self._img_key = img_key
        self._sub_key = sub_key

    def sign(
        self,
        uri: str,
        *,
        method: str = "GET",
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        cookie_str: str = "",
    ) -> SignResult:
        if not self._img_key or not self._sub_key:
            return SignResult()

        from media_platform.bilibili.help import BilibiliSign

        signer = BilibiliSign(self._img_key, self._sub_key)
        signed_params = signer.sign(params or {})
        return SignResult(params=signed_params)
