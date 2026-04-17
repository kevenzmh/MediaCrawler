# -*- coding: utf-8 -*-
import asyncio
import os
from typing import Callable, Dict, List, Optional, Tuple

import config
from config.account_config import AccountConfig, ProxyConfig, load_accounts
from proxy.proxy_ip_pool import IpInfoModel, ProxyIpPool, create_ip_pool
from tools import utils


class AccountSession:
    """Single account session: API client + bound proxy. Browser fields only set during login."""

    def __init__(self, account_config: AccountConfig):
        self.account_config = account_config
        # Browser fields — only populated during Playwright login sessions
        self.browser_context = None
        self.context_page = None
        self.cdp_manager = None
        # API client — populated by crawler after session creation
        self.api_client = None
        # Proxy fields
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
        self._proxy_pools: List[ProxyIpPool] = []

    def load_account_configs(self, platform: str) -> List[AccountConfig]:
        return load_accounts(platform)

    async def create_sessions_headless(self, platform: str) -> List[AccountSession]:
        """Create sessions WITHOUT launching a browser. Uses cookies from config.
        This is the primary mode for headless crawling — no Playwright dependency.
        """
        account_configs = self.load_account_configs(platform)
        utils.logger.info(
            f"[AccountManager] Creating {len(account_configs)} headless session(s) for platform '{platform}'"
        )

        await self._resolve_proxies(account_configs)

        for acct_cfg in account_configs:
            session = AccountSession(acct_cfg)
            await self._assign_proxy(session, acct_cfg)
            self.sessions.append(session)
            utils.logger.info(
                f"[AccountManager] Headless session created for account '{acct_cfg.account_id}'"
            )

        return self.sessions

    async def create_sessions_with_browser(
        self,
        platform: str,
        playwright,
        chromium,
        user_agent: str,
        launch_browser_fn: Callable,
        launch_cdp_fn: Optional[Callable] = None,
        stealth_js_path: Optional[str] = None,
        index_url: Optional[str] = None,
        post_init_fn: Optional[Callable] = None,
    ) -> List[AccountSession]:
        """Create sessions WITH browser launch (for platforms like Tieba that need Playwright)."""
        account_configs = self.load_account_configs(platform)
        utils.logger.info(
            f"[AccountManager] Creating {len(account_configs)} browser session(s) for platform '{platform}'"
        )

        await self._resolve_proxies(account_configs)

        for acct_cfg in account_configs:
            session = AccountSession(acct_cfg)
            await self._assign_proxy(session, acct_cfg)

            # Launch browser context
            if config.ENABLE_CDP_MODE and launch_cdp_fn:
                session.browser_context = await launch_cdp_fn(
                    playwright, session.playwright_proxy, user_agent,
                    headless=config.CDP_HEADLESS, account_id=acct_cfg.account_id,
                )
            else:
                session.browser_context = await launch_browser_fn(
                    chromium, session.playwright_proxy, user_agent,
                    headless=config.HEADLESS, account_id=acct_cfg.account_id,
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

            if post_init_fn:
                await post_init_fn(session)

            self.sessions.append(session)
            utils.logger.info(
                f"[AccountManager] Browser session created for account '{acct_cfg.account_id}'"
            )

        return self.sessions

    async def login_via_playwright(
        self,
        session: AccountSession,
        playwright,
        chromium,
        user_agent: str,
        launch_browser_fn: Callable,
        login_obj_factory: Callable,
        index_url: str,
        stealth_js_path: Optional[str] = None,
        post_login_hook: Optional[Callable] = None,
    ) -> Tuple[str, Dict]:
        """Launch Playwright for login only, extract cookies, close browser.

        Args:
            session: The account session to login
            playwright: Playwright instance
            chromium: Chromium browser type
            user_agent: User agent string
            launch_browser_fn: Browser launch function
            login_obj_factory: Callable(session, browser_context, context_page) -> AbstractLogin
            index_url: URL to navigate to before login
            stealth_js_path: Optional stealth.min.js path
            post_login_hook: Optional async fn(session) called after login before cookie extraction

        Returns:
            (cookie_str, cookie_dict) from the browser after login
        """
        utils.logger.info(
            f"[AccountManager] Launching Playwright for login: account '{session.account_id}'"
        )

        # Launch browser
        browser_context = await launch_browser_fn(
            chromium, session.playwright_proxy, user_agent,
            headless=config.HEADLESS, account_id=session.account_id,
        )

        # Inject stealth
        if stealth_js_path:
            try:
                await browser_context.add_init_script(path=stealth_js_path)
            except Exception:
                pass

        # Navigate and login
        context_page = await browser_context.new_page()
        await context_page.goto(index_url)

        # Temporarily set browser on session for login
        session.browser_context = browser_context
        session.context_page = context_page

        login_obj = login_obj_factory(session)
        await login_obj.begin()

        # Optional post-login hook (e.g., navigate to search page for cookies)
        if post_login_hook:
            await post_login_hook(session)

        # Extract cookies
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())

        # Close browser
        try:
            await browser_context.close()
        except Exception:
            pass
        session.browser_context = None
        session.context_page = None

        # Update session's stored cookies
        session.account_config.cookie_str = cookie_str

        utils.logger.info(
            f"[AccountManager] Login complete, browser closed for account '{session.account_id}'"
        )
        return cookie_str, cookie_dict

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

    async def _resolve_proxies(self, account_configs: List[AccountConfig]):
        """Pre-create proxy pools for accounts without fixed proxy."""
        accounts_need_pool = [
            ac for ac in account_configs
            if ac.proxy is None and config.ENABLE_IP_PROXY
        ]
        if accounts_need_pool:
            pool = await create_ip_pool(
                len(accounts_need_pool), enable_validate_ip=True
            )
            self._proxy_pools.append(pool)

    async def _assign_proxy(self, session: AccountSession, acct_cfg: AccountConfig):
        """Assign proxy to session based on config. Must be called after _resolve_proxies."""
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
