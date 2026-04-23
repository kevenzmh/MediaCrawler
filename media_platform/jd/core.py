import asyncio
import os
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from account import AccountManager, AccountSession
from base.base_crawler import AbstractCrawler
from store import jd as jd_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import JdClient
from .field import LicenseInfo, ShopInfo
from .help import JDExtractor
from .login import JdLogin


class JdCrawler(AbstractCrawler):

    def __init__(self) -> None:
        self.index_url = "https://www.jd.com"
        self.user_agent = utils.get_user_agent()
        self._extractor = JDExtractor()
        self.account_manager = AccountManager()

    async def start(self) -> None:
        async with async_playwright() as playwright:
            chromium = playwright.chromium

            sessions = await self.account_manager.create_sessions_with_browser(
                platform=config.PLATFORM,
                playwright=playwright,
                chromium=chromium,
                user_agent=self.user_agent,
                launch_browser_fn=self.launch_browser,
                launch_cdp_fn=self.launch_browser_with_cdp,
                stealth_js_path="libs/stealth.min.js",
                index_url=self.index_url,
            )

            for session in sessions:
                session.api_client = await self._create_client_for_session(session)
                if not await session.api_client.pong(browser_context=session.browser_context):
                    login_obj = JdLogin(
                        login_type=session.login_type,
                        browser_context=session.browser_context,
                        context_page=session.context_page,
                        cookie_str=session.cookie_str,
                    )
                    await login_obj.begin()
                    cookie_str, cookie_dict = utils.convert_cookies(
                        await session.browser_context.cookies()
                    )
                    await session.api_client.update_cookies(cookie_str=cookie_str, cookie_dict=cookie_dict)

            crawler_type_var.set(config.CRAWLER_TYPE)

            tasks = [self._crawl_with_session(session) for session in sessions]
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.account_manager.close_all()
            utils.logger.info("[JdCrawler] 京东爬虫运行结束")

    async def _create_client_for_session(self, session: AccountSession) -> JdClient:
        user_agent = await session.context_page.evaluate("() => navigator.userAgent")
        cookie_str, _ = utils.convert_cookies(await session.browser_context.cookies())
        return JdClient(
            timeout=30,
            ip_pool=session.proxy_ip_pool if config.ENABLE_IP_PROXY else None,
            default_ip_proxy=session.httpx_proxy,
            headers={
                "User-Agent": user_agent,
                "Cookie": cookie_str,
                "Referer": "https://www.jd.com/",
            },
        )

    async def _crawl_with_session(self, session: AccountSession):
        try:
            if config.JD_SPECIFIED_SHOP_IDS:
                shops = [
                    ShopInfo(shop_id=str(sid), shop_name="", shop_url=f"https://mall.jd.com/index-{sid}.html")
                    for sid in config.JD_SPECIFIED_SHOP_IDS
                ]
            else:
                shops = await self.search(session)

            if not shops:
                utils.logger.warning("[JdCrawler] 未找到任何店铺")
                return

            utils.logger.info(f"[JdCrawler] 共找到 {len(shops)} 家店铺，开始爬取营业执照")
            await self.get_shop_licenses(shops, session)
        except Exception as ex:
            utils.logger.error(f"[JdCrawler] 运行异常: {ex}")

    async def search(self, session: Optional[AccountSession] = None) -> List[ShopInfo]:
        """通过京东首页搜索框搜索关键词，从商品搜索结果中提取店铺列表"""
        page = session.context_page if session else self.account_manager.sessions[0].context_page
        all_shops: List[ShopInfo] = []
        seen_ids = set()

        keywords = config.JD_SEARCH_KEYWORDS.split(",") if config.JD_SEARCH_KEYWORDS else []
        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue
            source_keyword_var.set(keyword)
            utils.logger.info(f"[JdCrawler.search] 搜索关键词: {keyword}")

            try:
                # 先访问京东首页
                await page.goto("https://www.jd.com", wait_until="domcontentloaded")
                await asyncio.sleep(3)

                # 在搜索框输入关键词（兼容新旧版京东首页）
                search_input = await page.wait_for_selector(
                    "#key, input.search-input, input[type='text'][class*='search'], "
                    "input[aria-label*='搜索'], input[placeholder*='搜索']",
                    timeout=10000,
                )
                await search_input.fill("")
                await asyncio.sleep(0.5)
                await search_input.type(keyword, delay=100)
                await asyncio.sleep(1)

                # 点击搜索按钮或按回车
                search_btn = await page.query_selector(
                    "#search-btn, button.search-btn, button.button, a.button, "
                    "button[class*='search'], [class*='search-btn']"
                )
                if search_btn:
                    await search_btn.click()
                else:
                    await page.keyboard.press("Enter")

                # 等待搜索结果页加载（React 渲染较慢）
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(8)

                # 检查是否被风控
                is_blocked = await page.evaluate("""() => {
                    const text = document.body?.innerText || '';
                    return text.includes('访问频繁') || text.includes('请稍后再试');
                }""")
                if is_blocked:
                    utils.logger.warning("[JdCrawler.search] 被京东风控拦截，等待30秒后重试...")
                    await asyncio.sleep(30)
                    await page.goto("https://www.jd.com", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    continue

                # 缓慢滚动触发懒加载商品
                for scroll_y in range(200, 3000, 200):
                    await page.evaluate(f"window.scrollTo({{top: {scroll_y}, behavior: 'smooth'}})")
                    await asyncio.sleep(0.6)
                await asyncio.sleep(3)
                await page.evaluate("window.scrollTo({top: 0})")
                await asyncio.sleep(2)

                # 提取搜索结果中的店铺信息
                shops = await self._extractor.extract_shops_from_search(page)
                new_shops = [s for s in shops if s.shop_id not in seen_ids]
                for s in new_shops:
                    seen_ids.add(s.shop_id)
                all_shops.extend(new_shops)

                utils.logger.info(
                    f"[JdCrawler.search] 关键词={keyword}, "
                    f"本词店铺={len(shops)}, 新增={len(new_shops)}, 累计={len(all_shops)}"
                )

                # 关键词之间等待较长时间，避免触发风控
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC + 5)

            except Exception as e:
                utils.logger.error(f"[JdCrawler.search] 搜索关键词 {keyword} 异常: {e}")

            if len(all_shops) >= config.JD_MAX_SHOPS_PER_KEYWORD:
                break

        return all_shops[:config.JD_MAX_SHOPS_PER_KEYWORD]

    async def get_shop_licenses(self, shops: List[ShopInfo], session: AccountSession):
        """遍历店铺，爬取营业执照图片"""
        page = session.context_page
        client: JdClient = session.api_client

        for i, shop in enumerate(shops):
            utils.logger.info(f"[JdCrawler] [{i+1}/{len(shops)}] 正在处理店铺: {shop.shop_name} (ID: {shop.shop_id})")
            try:
                license_urls = await self._get_license_urls(page, shop)
                if not license_urls:
                    utils.logger.warning(f"[JdCrawler] 店铺 {shop.shop_id} 未找到营业执照图片")
                    continue

                for url in license_urls:
                    image_data = await client.download_image(url)
                    if image_data:
                        license_info = LicenseInfo(
                            shop_id=shop.shop_id,
                            shop_name=shop.shop_name,
                            license_image_url=url,
                            license_type="营业执照",
                        )
                        await jd_store.save_license_image(license_info, image_data)

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC + 3)
            except Exception as e:
                utils.logger.error(f"[JdCrawler] 店铺 {shop.shop_id} 爬取失败: {e}")

    async def _get_license_urls(self, page: Page, shop: ShopInfo) -> List[str]:
        """获取单个店铺的营业执照图片 URL 列表"""
        shop_url = f"https://mall.jd.com/index-{shop.shop_id}.html"
        try:
            await page.goto(shop_url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            # 检查页面是否正常（没被重定向到错误页）
            is_error = await page.evaluate("""() => {
                const url = location.href;
                return url.includes('error') || url.includes('error2');
            }""")
            if is_error:
                utils.logger.warning(f"[JdCrawler] 店铺 {shop.shop_id} 页面不存在或已关闭")
                return []

            # 提取店铺名
            shop.shop_name = await self._extractor.get_shop_name(page) or shop.shop_name

            # 策略1：找 footer 中"营业执照"链接 → 跳转 pro.jd.com
            license_link = await self._extractor.find_license_link_in_footer(page)
            if license_link:
                utils.logger.info(f"[JdCrawler] 找到营业执照链接: {license_link}")
                await page.goto(license_link, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                urls = await self._extractor.extract_license_from_pro_page(page)
                if urls:
                    return urls

            # 策略2：回到店铺页，点击证照入口弹窗
            await page.goto(shop_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            urls = await self._extractor.click_license_popup(page)
            return urls

        except Exception as e:
            utils.logger.error(f"[JdCrawler] _get_license_urls 异常: {e}")
            return []

    async def get_specified_notes(self, **kwargs):
        pass

    async def get_creators_and_notes(self, **kwargs):
        pass

    async def feed(self, **kwargs):
        pass

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
        account_id: str = "",
    ) -> BrowserContext:
        utils.logger.info("[JdCrawler.launch_browser] 创建浏览器上下文...")
        if config.SAVE_LOGIN_STATE:
            dir_name = f"{config.PLATFORM}_{account_id}" if account_id else config.USER_DATA_DIR % config.PLATFORM
            user_data_dir = os.path.join(os.getcwd(), "browser_data", dir_name)
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)
            browser_context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}, user_agent=user_agent
            )
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
        account_id: str = "",
    ) -> BrowserContext:
        try:
            cdp_manager = CDPBrowserManager()
            browser_context = await cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )
            browser_info = await cdp_manager.get_browser_info()
            utils.logger.info(f"[JdCrawler] CDP 浏览器信息: {browser_info}")

            for s in self.account_manager.sessions:
                if s.account_id == account_id:
                    s.cdp_manager = cdp_manager
                    break
            return browser_context
        except Exception as e:
            utils.logger.error(f"[JdCrawler] CDP 模式启动失败，回退到标准模式: {e}")
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless, account_id)
