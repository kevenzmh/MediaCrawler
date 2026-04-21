# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SignResult:
    """签名操作的统一返回值。"""

    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, str] = field(default_factory=dict)

    @property
    def has_headers(self) -> bool:
        return bool(self.headers)

    @property
    def has_params(self) -> bool:
        return bool(self.params)


class SignProvider(ABC):
    """签名提供者抽象基类，每个平台实现一个。"""

    @property
    @abstractmethod
    def platform(self) -> str:
        """平台标识，如 'xhs', 'douyin'"""
        ...

    @abstractmethod
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
        """计算请求签名。

        Args:
            uri: 请求路径，如 "/api/sns/web/v1/search/notes"
            method: HTTP 方法
            params: GET 查询参数
            data: POST 请求体
            headers: 当前请求头（部分签名需要 User-Agent 等）
            cookies: Cookie 字典
            cookie_str: 原始 Cookie 字符串
        """
        ...
