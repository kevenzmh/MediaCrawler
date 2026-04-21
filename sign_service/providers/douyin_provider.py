# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import urllib.parse
from typing import Dict, Optional

from ..base import SignProvider, SignResult


class DouyinSignProvider(SignProvider):
    """抖音签名提供者，包装 get_a_bogus_from_js。"""

    @property
    def platform(self) -> str:
        return "douyin"

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
        from media_platform.douyin.help import get_a_bogus_from_js

        query_string = urllib.parse.urlencode(params or {})
        user_agent = (headers or {}).get("User-Agent", "")
        a_bogus = get_a_bogus_from_js(uri, query_string, user_agent)
        return SignResult(params={"a_bogus": a_bogus})
