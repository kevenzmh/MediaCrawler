# -*- coding: utf-8 -*-
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import config
from tools import utils


@dataclass
class ProxyConfig:
    ip: str = ""
    port: int = 0
    user: str = ""
    password: str = ""


@dataclass
class AccountConfig:
    account_id: str = "default"
    cookie_str: str = ""
    login_type: str = ""
    proxy: Optional[ProxyConfig] = None
    enabled: bool = True

    def __post_init__(self):
        if not self.login_type:
            self.login_type = config.LOGIN_TYPE
        if not self.cookie_str:
            self.cookie_str = config.COOKIES
        if isinstance(self.proxy, dict):
            self.proxy = ProxyConfig(**self.proxy)


_ACCOUNTS_FILE = "accounts.json"


def load_accounts(platform: str) -> list[AccountConfig]:
    """Load account configs from accounts.json for the given platform.
    Falls back to single-account mode using config.COOKIES if file missing or empty.
    """
    accounts_path = os.path.join(os.getcwd(), _ACCOUNTS_FILE)
    if not os.path.exists(accounts_path):
        utils.logger.info(
            f"[account_config] No {_ACCOUNTS_FILE} found, using single-account mode"
        )
        return [_fallback_single_account(platform)]

    try:
        with open(accounts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        utils.logger.warning(
            f"[account_config] Failed to read {_ACCOUNTS_FILE}: {e}, using single-account mode"
        )
        return [_fallback_single_account(platform)]

    platform_accounts = data.get(platform, [])
    if not platform_accounts:
        utils.logger.info(
            f"[account_config] No accounts configured for platform '{platform}', using single-account mode"
        )
        return [_fallback_single_account(platform)]

    accounts = []
    for item in platform_accounts:
        acct = AccountConfig(**item)
        if acct.enabled:
            accounts.append(acct)

    if not accounts:
        utils.logger.warning(
            f"[account_config] All accounts disabled for '{platform}', using single-account mode"
        )
        return [_fallback_single_account(platform)]

    utils.logger.info(
        f"[account_config] Loaded {len(accounts)} account(s) for platform '{platform}'"
    )
    return accounts


def _fallback_single_account(platform: str) -> AccountConfig:
    return AccountConfig(
        account_id=f"{platform}_default",
        cookie_str=config.COOKIES,
        login_type=config.LOGIN_TYPE,
        proxy=None,
        enabled=True,
    )
