# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import json
import logging
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx

from .base import SignResult, SignProvider

logger = logging.getLogger(__name__)


class SignService:
    """签名服务门面类，路由到本地或远程签名。"""

    def __init__(
        self,
        provider: SignProvider,
        remote_url: Optional[str] = None,
    ):
        self._provider = provider
        self._remote_url = remote_url

    @property
    def provider(self) -> SignProvider:
        return self._provider

    @property
    def remote_url(self) -> Optional[str]:
        return self._remote_url

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
        if self._remote_url:
            return self._sign_remote(
                uri,
                method=method,
                params=params,
                data=data,
                headers=headers,
                cookies=cookies,
                cookie_str=cookie_str,
            )
        return self._provider.sign(
            uri,
            method=method,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            cookie_str=cookie_str,
        )

    def _sign_remote(self, uri, **kwargs) -> SignResult:
        """调用远程签名服务。

        请求格式:
            POST {remote_url}
            Body: {"platform": "...", "uri": "...", "method": "...", "params": {}, ...}

        响应格式:
            {"headers": {...}, "params": {...}}
        """
        payload = {
            "platform": self._provider.platform,
            "uri": uri,
            "method": kwargs.get("method", "GET"),
            "params": kwargs.get("params"),
            "data": kwargs.get("data"),
            "cookie_str": kwargs.get("cookie_str", ""),
        }
        try:
            resp = httpx.post(
                self._remote_url,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            return SignResult(
                headers=result.get("headers", {}),
                params=result.get("params", {}),
            )
        except Exception as e:
            logger.warning(
                f"[SignService] Remote sign failed for {self._provider.platform}, "
                f"falling back to local: {e}"
            )
            return self._provider.sign(uri, **kwargs)
