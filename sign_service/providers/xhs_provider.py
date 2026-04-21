# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Dict, Optional

from ..base import SignProvider, SignResult


class XhsSignProvider(SignProvider):
    """小红书签名提供者，包装 sign_with_xhshow。"""

    @property
    def platform(self) -> str:
        return "xhs"

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
        from media_platform.xhs.playwright_sign import sign_with_xhshow

        if method.upper() == "POST":
            sign_data = data
        else:
            sign_data = params

        signs = sign_with_xhshow(
            uri=uri,
            data=sign_data,
            cookie_str=cookie_str,
            method=method,
        )
        return SignResult(headers={
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
        })
