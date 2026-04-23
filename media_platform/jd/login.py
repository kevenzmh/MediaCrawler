import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page

import config
from base.base_crawler import AbstractLogin
from tools import utils


class JdLogin(AbstractLogin):
    """京东登录，支持扫码和 Cookie"""

    def __init__(
        self,
        login_type: str,
        browser_context: BrowserContext,
        context_page: Page,
        cookie_str: str = "",
    ):
        self.login_type = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.cookie_str = cookie_str

    async def begin(self):
        if self.login_type == "qrcode":
            await self.login_by_qrcode()
        elif self.login_type == "cookie":
            await self.login_by_cookies()
        else:
            await self.login_by_qrcode()

    async def login_by_qrcode(self):
        """扫码登录京东"""
        utils.logger.info("[JdLogin] 请打开京东 APP 扫描二维码登录...")
        try:
            await self.context_page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")
            # 切换到扫码登录 Tab
            try:
                qrcode_tab = await self.context_page.wait_for_selector("a:has-text('扫码登录')", timeout=5000)
                if qrcode_tab:
                    await qrcode_tab.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # 等待用户扫码完成（页面跳转表示登录成功）
            utils.logger.info("[JdLogin] 等待扫码...登录成功后页面将自动跳转")
            await self.context_page.wait_for_url(
                lambda url: "passport.jd.com" not in url or "passport.jd.com/uclogin" not in url,
                timeout=120000,
            )
            utils.logger.info("[JdLogin] 扫码登录成功")
        except Exception as e:
            utils.logger.error(f"[JdLogin] 扫码登录失败: {e}")
            raise

    async def login_by_mobile(self):
        await self.login_by_qrcode()

    async def login_by_cookies(self):
        """Cookie 登录"""
        if not self.cookie_str:
            utils.logger.error("[JdLogin] Cookie 为空，无法登录")
            return
        try:
            cookies = []
            for item in self.cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    name, value = item.split("=", 1)
                    cookies.append({
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".jd.com",
                        "path": "/",
                    })
            await self.browser_context.add_cookies(cookies)
            utils.logger.info("[JdLogin] Cookie 注入完成")
        except Exception as e:
            utils.logger.error(f"[JdLogin] Cookie 登录失败: {e}")
