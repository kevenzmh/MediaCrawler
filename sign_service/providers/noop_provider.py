# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

from typing import Dict, Optional

from ..base import SignProvider, SignResult


class NoOpSignProvider(SignProvider):
    """无签名平台透传提供者，返回空 SignResult。"""

    @property
    def platform(self) -> str:
        return "noop"

    def sign(self, uri: str, **kwargs) -> SignResult:
        return SignResult()
