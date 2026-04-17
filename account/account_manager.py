# -*- coding: utf-8 -*-
import asyncio
import os
from typing import Callable, Dict, List, Optional

from playwright.async_api import BrowserContext, BrowserType, Page, Playwright

import config
from config.account_config import AccountConfig, ProxyConfig, load_accounts
from proxy.proxy_ip_pool import IpInfoModel, ProxyIpPool, create_ip_pool
from tools import utils
from tools.cdp_browser import CDPBrowserManager


class AccountSession:
    """Single account session: BrowserContext + API client + bound proxy."""

    def __init__(self, account_config: AccountConfig):
        self.account_config = account_config
        self.browser_context: Optional[BrowserContext] = None
        self.context_page: Optional[Page] = None
        self.cdp_manager: Optional[CDPBrowserManager] = None
        self.api_client = None  # platform-specific client, set by crawler
        self.proxy_ip_pool: Optional[ProxyIpPool] = None
        self.httpx_proxy: Optional[str] = None
        self.playwright_proxy: Optional[Dict] = None

    @property
    def account_id(self) -> str:
        return self.account_config.account_id

    @property
    def cookie_str(self) -> str:
        return self.account_config.cookie_str

    @property
    def login_type(self) -> str:
        return self.account_config.login_type


class AccountManager:
    """Manages multiple AccountSession lifecycles."""

    def __init__(self):
        self.sessions: List[AccountSession] = []
        self._proxy_pools: List[ProxyIpPool] = []  # shared pools for auto-assign

    def load_account_configs(self, platform: str) -> List[AccountConfig]:
        return load_accounts(platform)

    async def create_sessions(
        self,
        platform: str,
        playwright: Playwright,
        chromium: BrowserType,
        user_agent: str,
        launch_browser_fn: Callable,
        launch_cdp_fn: Optional[Callable] = None,
        stealth_js_path: Optional[str] = None,
        index_url: Optional[str] = None,
        post_init_fn: Optional[Callable] = None,
    ) -> List[AccountSession]:
        """Create AccountSession for each configured account.

        Args:
            platform: Platform identifier (xhs, dy, etc.)
            playwright: Playwright instance
            chromium: Chromium browser type
            user_agent: Default user agent string
            launch_browser_fn: async fn(chromium, playwright_proxy, user_agent, headless, account_id) -> BrowserContext
            launch_cdp_fn: async fn(playwright, playwright_proxy, user_agent, headless, account_id) -> BrowserContext
            stealth_js_path: Path to stealth.min.js, inject if provided
            index_url: Navigate to this URL after browser launch
            post_init_fn: async fn(session) - custom init after session setup
        """
        account_configs = self.load_account_configs(platform)
        utils.logger.info(
            f"[AccountManager] Creating {len(account_configs)} session(s) for platform '{platform}'"
        )

        # Pre-create shared proxy pools for accounts without fixed proxy
        accounts_need_pool = [
            ac for ac in account_configs
            if ac.proxy is None and config.ENABLE_IP_PROXY
        ]
        if accounts_need_pool:
            pool = await create_ip_pool(
                len(accounts_need_pool), enable_validate_ip=True
            )
            self._proxy_pools.append(pool)

        for acct_cfg in account_configs:
            session = AccountSession(acct_cfg)

            # Resolve proxy: fixed proxy from config, or auto-assign from pool
            if acct_cfg.proxy and acct_cfg.proxy.ip:
                pw_proxy, hx_proxy = _format_fixed_proxy(acct_cfg.proxy)
                session.playwright_proxy = pw_proxy
                session.httpx_proxy = hx_proxy
                utils.logger.info(
                    f"[AccountManager] Account '{acct_cfg.account_id}' using fixed proxy: {acct_cfg.proxy.ip}:{acct_cfg.proxy.port}"
                )
            elif config.ENABLE_IP_PROXY and self._proxy_pools:
                ip_info: IpInfoModel = await self._proxy_pools[0].get_proxy()
                pw_proxy, hx_proxy = utils.format_proxy_info(ip_info)
                session.playwright_proxy = pw_proxy
                session.httpx_proxy = hx_proxy
                session.proxy_ip_pool = self._proxy_pools[0]
                utils.logger.info(
                    f"[AccountManager] Account '{acct_cfg.account_id}' auto-assigned proxy: {ip_info.ip}:{ip_info.port}"
                )

            # Launch browser context for this account
            if config.ENABLE_CDP_MODE and launch_cdp_fn:
                session.browser_context = await launch_cdp_fn(
                    playwright,
                    session.playwright_proxy,
                    user_agent,
                    headless=config.CDP_HEADLESS,
                    account_id=acct_cfg.account_id,
                )
            else:
                session.browser_context = await launch_browser_fn(
                    chromium,
                    session.playwright_proxy,
                    user_agent,
                    headless=config.HEADLESS,
                    account_id=acct_cfg.account_id,
                )

            # Inject stealth script
            if stealth_js_path and not config.ENABLE_CDP_MODE:
                try:
                    await session.browser_context.add_init_script(path=stealth_js_path)
                except Exception as e:
                    utils.logger.warning(
                        f"[AccountManager] Failed to inject stealth.js for '{acct_cfg.account_id}': {e}"
                    )

            # Create page and navigate
            session.context_page = await session.browser_context.new_page()
            if index_url:
                await session.context_page.goto(index_url)

            # Custom post-init (e.g., tieba special navigation)
            if post_init_fn:
                await post_init_fn(session)

            self.sessions.append(session)
            utils.logger.info(
                f"[AccountManager] Session created for account '{acct_cfg.account_id}'"
            )

        return self.sessions

    async def close_all(self):
        """Close all browser contexts and CDP managers."""
        for session in self.sessions:
            try:
                if session.cdp_manager:
                    await session.cdp_manager.cleanup()
                    session.cdp_manager = None
                elif session.browser_context:
                    await session.browser_context.close()
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    utils.logger.warning(
                        f"[AccountManager] Error closing session '{session.account_id}': {e}"
                    )
            session.browser_context = None
            session.context_page = None
        self.sessions.clear()
        utils.logger.info("[AccountManager] All sessions closed")


def _format_fixed_proxy(proxy: ProxyConfig):
    """Format a ProxyConfig into (playwright_proxy, httpx_proxy) tuple."""
    pw = {"server": f"{proxy.ip}:{proxy.port}"}
    if proxy.user:
        pw["username"] = proxy.user
    if proxy.password:
        pw["password"] = proxy.password

    if proxy.user and proxy.password:
        hx = f"http://{proxy.user}:{proxy.password}@{proxy.ip}:{proxy.port}"
    else:
        hx = f"http://{proxy.ip}:{proxy.port}"

    return pw, hx
