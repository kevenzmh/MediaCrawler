# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Dict, Optional
from urllib.parse import urlencode

from ..base import SignProvider, SignResult


class ZhihuSignProvider(SignProvider):
    """知乎签名提供者，包装 zhihu help.sign。"""

    @property
    def platform(self) -> str:
        return "zhihu"

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
        from media_platform.zhihu.help import sign as zhihu_sign

        # 知乎签名需要完整 URL (含查询参数)
        if params:
            full_url = uri + "?" + urlencode(params)
        else:
            full_url = uri

        sign_res = zhihu_sign(full_url, cookie_str)
        return SignResult(headers={
            "x-zst-81": sign_res["x-zst-81"],
            "x-zse-96": sign_res["x-zse-96"],
        })
