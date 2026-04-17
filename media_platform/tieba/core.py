# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/tieba/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


import asyncio
import os
from asyncio import Task
from typing import Dict, List, Optional, Tuple

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
from model.m_baidu_tieba import TiebaCreator, TiebaNote
from store import tieba as tieba_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import BaiduTieBaClient
from .field import SearchNoteType, SearchSortType
from .help import TieBaExtractor
from .login import BaiduTieBaLogin


class TieBaCrawler(AbstractCrawler):

    def __init__(self) -> None:
        self.index_url = "https://tieba.baidu.com"
        self.user_agent = utils.get_user_agent()
        self._page_extractor = TieBaExtractor()
        self.account_manager = AccountManager()

    async def start(self) -> None:
        """
        Start the crawler
        Returns:

        """
        async with async_playwright() as playwright:
            chromium = playwright.chromium

            sessions = await self.account_manager.create_sessions(
                platform=config.PLATFORM,
                playwright=playwright,
                chromium=chromium,
                user_agent=self.user_agent,
                launch_browser_fn=self.launch_browser,
                launch_cdp_fn=self.launch_browser_with_cdp,
                stealth_js_path="libs/stealth.min.js",
                index_url=self.index_url,
                post_init_fn=self._tieba_post_init,
            )

            # Login and create client for each session
            for session in sessions:
                session.api_client = await self._create_client_for_session(session)
                if not await session.api_client.pong(browser_context=session.browser_context):
                    login_obj = BaiduTieBaLogin(
                        login_type=session.login_type,
                        login_phone="",
                        browser_context=session.browser_context,
                        context_page=session.context_page,
                        cookie_str=session.cookie_str,
                    )
                    await login_obj.begin()
                    await session.api_client.update_cookies(browser_context=session.browser_context)

            crawler_type_var.set(config.CRAWLER_TYPE)

            # Run crawl tasks in parallel across accounts
            tasks = [
                self._crawl_with_session(session)
                for session in sessions
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.account_manager.close_all()
            utils.logger.info("[BaiduTieBaCrawler.start] Tieba Crawler finished ...")

    async def _tieba_post_init(self, session: AccountSession):
        """Post-init hook for tieba: inject anti-detection scripts and navigate via Baidu homepage."""
        await self._inject_anti_detection_scripts(session)
        await self._navigate_to_tieba_via_baidu(session)

    async def _crawl_with_session(self, session: AccountSession):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
                await self.get_specified_tieba_notes(session)
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_notes(session=session)
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_notes(session)
        except Exception as ex:
            utils.logger.error(
                f"[TieBaCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    async def _create_client_for_session(self, session: AccountSession) -> BaiduTieBaClient:
        """Create BaiduTieBaClient for a specific account session."""
        utils.logger.info(
            f"[TieBaCrawler._create_client_for_session] Creating client for account '{session.account_id}'"
        )

        # Extract User-Agent from real browser to avoid detection
        user_agent = await session.context_page.evaluate("() => navigator.userAgent")
        utils.logger.info(
            f"[TieBaCrawler._create_client_for_session] Extracted User-Agent from browser: {user_agent}"
        )

        cookie_str, cookie_dict = utils.convert_cookies(await session.browser_context.cookies())

        tieba_client = BaiduTieBaClient(
            timeout=10,
            ip_pool=session.proxy_ip_pool if config.ENABLE_IP_PROXY else None,
            default_ip_proxy=session.httpx_proxy,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "User-Agent": user_agent,
                "Cookie": cookie_str,
                "Host": "tieba.baidu.com",
                "Referer": "https://tieba.baidu.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
            playwright_page=session.context_page,
        )
        return tieba_client

    async def search(self, session: Optional[AccountSession] = None) -> None:
        """
        Search for notes and retrieve their comment information.
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(
            f"[BaiduTieBaCrawler.search] Begin search baidu tieba keywords (account: {session.account_id if session else 'default'})"
        )
        tieba_limit_count = 10  # tieba limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < tieba_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = tieba_limit_count
        start_page = config.START_PAGE
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[BaiduTieBaCrawler.search] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[BaiduTieBaCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(
                f"[BaiduTieBaCrawler.search] Current search keyword: {keyword}, start page: {page}"
            )
            while (
                page - start_page + 1
            ) * tieba_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[BaiduTieBaCrawler.search] Skip page {page}")
                    page += 1
                    continue
                try:
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.search] search tieba keyword: {keyword}, page: {page}"
                    )
                    notes_list: List[TiebaNote] = (
                        await client.get_notes_by_keyword(
                            keyword=keyword,
                            page=page,
                            page_size=tieba_limit_count,
                            sort=SearchSortType.TIME_DESC,
                            note_type=SearchNoteType.FIXED_THREAD,
                        )
                    )
                    if not notes_list:
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] Search note list is empty"
                        )
                        break
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.search] Note list len: {len(notes_list)}"
                    )
                    await self.get_specified_notes(
                        note_id_list=[note_detail.note_id for note_detail in notes_list],
                        session=session,
                    )

                    page += 1

                    # 每页成功后保存 checkpoint
                    checkpoint.save_checkpoint(keyword=keyword, page=page)

                    # Sleep after page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[TieBaCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                except Exception as ex:
                    utils.logger.error(
                        f"[BaiduTieBaCrawler.search] Search keywords error, current page: {page}, current keyword: {keyword}, err: {ex}"
                    )
                    break

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def get_specified_tieba_notes(self, session: Optional[AccountSession] = None):
        """
        Get the information and comments of the specified post by tieba name
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        tieba_limit_count = 50
        if config.CRAWLER_MAX_NOTES_COUNT < tieba_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = tieba_limit_count
        for tieba_name in config.TIEBA_NAME_LIST:
            utils.logger.info(
                f"[BaiduTieBaCrawler.get_specified_tieba_notes] Begin get tieba name: {tieba_name}"
            )
            page_number = 0
            while page_number <= config.CRAWLER_MAX_NOTES_COUNT:
                note_list: List[TiebaNote] = (
                    await client.get_notes_by_tieba_name(
                        tieba_name=tieba_name, page_num=page_number
                    )
                )
                if not note_list:
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.get_specified_tieba_notes] Get note list is empty"
                    )
                    break

                utils.logger.info(
                    f"[BaiduTieBaCrawler.get_specified_tieba_notes] tieba name: {tieba_name} note list len: {len(note_list)}"
                )
                await self.get_specified_notes(
                    [note.note_id for note in note_list], session=session
                )

                # Sleep after processing notes
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[TieBaCrawler.get_specified_tieba_notes] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after processing notes from page {page_number}")

                page_number += tieba_limit_count

    async def get_specified_notes(
        self,
        note_id_list: List[str] = config.TIEBA_SPECIFIED_ID_LIST,
        session: Optional[AccountSession] = None,
    ):
        """
        Get the information and comments of the specified post
        Args:
            note_id_list:

        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(note_id=note_id, semaphore=semaphore, client=client)
            for note_id in note_id_list
        ]
        note_details = await asyncio.gather(*task_list)
        note_details_model: List[TiebaNote] = []
        for note_detail in note_details:
            if note_detail is not None:
                note_details_model.append(note_detail)
                await tieba_store.update_tieba_note(note_detail)
        await self.batch_get_note_comments(note_details_model, client=client)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        semaphore: asyncio.Semaphore,
        client: Optional[BaiduTieBaClient] = None,
    ) -> Optional[TiebaNote]:
        """
        Get note detail
        Args:
            note_id: baidu tieba note id
            semaphore: asyncio semaphore
            client: BaiduTieBaClient instance

        Returns:

        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                utils.logger.info(
                    f"[BaiduTieBaCrawler.get_note_detail] Begin get note detail, note_id: {note_id}"
                )
                note_detail: TiebaNote = await _client.get_note_by_id(note_id)

                # Sleep after fetching note details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[TieBaCrawler.get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                if not note_detail:
                    utils.logger.error(
                        f"[BaiduTieBaCrawler.get_note_detail] Get note detail error, note_id: {note_id}"
                    )
                    return None
                return note_detail
            except Exception as ex:
                utils.logger.error(
                    f"[BaiduTieBaCrawler.get_note_detail] Get note detail error: {ex}"
                )
                return None
            except KeyError as ex:
                utils.logger.error(
                    f"[BaiduTieBaCrawler.get_note_detail] have not fund note detail note_id:{note_id}, err: {ex}"
                )
                return None

    async def batch_get_note_comments(
        self,
        note_detail_list: List[TiebaNote],
        client: Optional[BaiduTieBaClient] = None,
    ):
        """
        Batch get note comments
        Args:
            note_detail_list:
            client: BaiduTieBaClient instance

        Returns:

        """
        if not config.ENABLE_GET_COMMENTS:
            return

        _client = client or self.account_manager.sessions[0].api_client
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_detail in note_detail_list:
            task = asyncio.create_task(
                self.get_comments_async_task(note_detail, semaphore, client=_client),
                name=note_detail.note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments_async_task(
        self,
        note_detail: TiebaNote,
        semaphore: asyncio.Semaphore,
        client: Optional[BaiduTieBaClient] = None,
    ):
        """
        Get comments async task
        Args:
            note_detail:
            semaphore:
            client: BaiduTieBaClient instance

        Returns:

        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            utils.logger.info(
                f"[BaiduTieBaCrawler.get_comments] Begin get note id comments {note_detail.note_id}"
            )

            # Sleep before fetching comments
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(f"[TieBaCrawler.get_comments_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_detail.note_id}")

            await _client.get_note_all_comments(
                note_detail=note_detail,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=tieba_store.batch_update_tieba_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

    async def get_creators_and_notes(self, session: Optional[AccountSession] = None) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(
            f"[WeiboCrawler.get_creators_and_notes] Begin get weibo creators (account: {session.account_id if session else 'default'})"
        )
        for creator_url in config.TIEBA_CREATOR_URL_LIST:
            creator_page_html_content = await client.get_creator_info_by_url(
                creator_url=creator_url
            )
            creator_info: TiebaCreator = self._page_extractor.extract_creator_info(
                creator_page_html_content
            )
            if creator_info:
                utils.logger.info(
                    f"[WeiboCrawler.get_creators_and_notes] creator info: {creator_info}"
                )
                if not creator_info:
                    raise Exception("Get creator info error")

                await tieba_store.save_creator(user_info=creator_info)

                # Get all note information of the creator
                all_notes_list = (
                    await client.get_all_notes_by_creator_user_name(
                        user_name=creator_info.user_name,
                        crawl_interval=0,
                        callback=tieba_store.batch_update_tieba_notes,
                        max_note_count=config.CRAWLER_MAX_NOTES_COUNT,
                        creator_page_html_content=creator_page_html_content,
                    )
                )

                await self.batch_get_note_comments(all_notes_list, client=client)

            else:
                utils.logger.error(
                    f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_url:{creator_url}"
                )

    async def _navigate_to_tieba_via_baidu(self, session: AccountSession):
        """
        Simulate real user access path:
        1. First visit Baidu homepage (https://www.baidu.com/)
        2. Wait for page to load
        3. Click "Tieba" link in top navigation bar
        4. Jump to Tieba homepage

        This avoids triggering Baidu's security verification

        Args:
            session: AccountSession to operate on
        """
        utils.logger.info(f"[TieBaCrawler] Simulating real user access path for account '{session.account_id}'...")

        try:
            # Step 1: Visit Baidu homepage
            utils.logger.info("[TieBaCrawler] Step 1: Visiting Baidu homepage https://www.baidu.com/")
            await session.context_page.goto("https://www.baidu.com/", wait_until="domcontentloaded")

            # Step 2: Wait for page loading, using delay setting from config file
            utils.logger.info(f"[TieBaCrawler] Step 2: Waiting {config.CRAWLER_MAX_SLEEP_SEC} seconds to simulate user browsing...")
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

            # Step 3: Find and click "Tieba" link
            utils.logger.info("[TieBaCrawler] Step 3: Finding and clicking 'Tieba' link...")

            # Try multiple selectors to ensure finding the Tieba link
            tieba_selectors = [
                'a[href="http://tieba.baidu.com/"]',
                'a[href="https://tieba.baidu.com/"]',
                'a.mnav:has-text("贴吧")',
                'text=贴吧',
            ]

            tieba_link = None
            for selector in tieba_selectors:
                try:
                    tieba_link = await session.context_page.wait_for_selector(selector, timeout=5000)
                    if tieba_link:
                        utils.logger.info(f"[TieBaCrawler] Found Tieba link (selector: {selector})")
                        break
                except Exception:
                    continue

            if not tieba_link:
                utils.logger.warning("[TieBaCrawler] Tieba link not found, directly accessing Tieba homepage")
                await session.context_page.goto(self.index_url, wait_until="domcontentloaded")
                return

            # Step 4: Click Tieba link (check if it will open in a new tab)
            utils.logger.info("[TieBaCrawler] Step 4: Clicking Tieba link...")

            # Check link's target attribute
            target_attr = await tieba_link.get_attribute("target")
            utils.logger.info(f"[TieBaCrawler] Link target attribute: {target_attr}")

            if target_attr == "_blank":
                # If it's a new tab, need to wait for new page and switch
                utils.logger.info("[TieBaCrawler] Link will open in new tab, waiting for new page...")

                async with session.browser_context.expect_page() as new_page_info:
                    await tieba_link.click()

                # Get newly opened page
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded")

                # Close old Baidu homepage
                await session.context_page.close()

                # Switch to new Tieba page
                session.context_page = new_page
                utils.logger.info("[TieBaCrawler] Successfully switched to new tab (Tieba page)")
            else:
                # If it's same tab navigation, wait for navigation normally
                utils.logger.info("[TieBaCrawler] Link navigates in current tab...")
                async with session.context_page.expect_navigation(wait_until="domcontentloaded"):
                    await tieba_link.click()

            # Step 5: Wait for page to stabilize, using delay setting from config file
            utils.logger.info(f"[TieBaCrawler] Step 5: Page loaded, waiting {config.CRAWLER_MAX_SLEEP_SEC} seconds...")
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

            current_url = session.context_page.url
            utils.logger.info(f"[TieBaCrawler] Successfully entered Tieba via Baidu homepage! Current URL: {current_url}")

        except Exception as e:
            utils.logger.error(f"[TieBaCrawler] Failed to access Tieba via Baidu homepage: {e}")
            utils.logger.info("[TieBaCrawler] Fallback: directly accessing Tieba homepage")
            await session.context_page.goto(self.index_url, wait_until="domcontentloaded")

    async def _inject_anti_detection_scripts(self, session: AccountSession):
        """
        Inject anti-detection JavaScript scripts
        For Baidu Tieba's special detection mechanism

        Args:
            session: AccountSession whose browser_context to inject into
        """
        utils.logger.info(f"[TieBaCrawler] Injecting anti-detection scripts for account '{session.account_id}'...")

        # Lightweight anti-detection script, only covering key detection points
        anti_detection_js = """
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });

        // Override window.navigator.chrome
        if (!window.navigator.chrome) {
            window.navigator.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        }

        // Override Permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Override plugins length (make it look like there are plugins)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
            configurable: true
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
            configurable: true
        });

        // Remove window.cdc_ and other ChromeDriver remnants
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        console.log('[Anti-Detection] Scripts injected successfully');
        """

        await session.browser_context.add_init_script(anti_detection_js)
        utils.logger.info(f"[TieBaCrawler] Anti-detection scripts injected for account '{session.account_id}'")

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
        account_id: str = "",
    ) -> BrowserContext:
        """
        Launch browser and create browser
        Args:
            chromium:
            playwright_proxy:
            user_agent:
            headless:
            account_id: Account identifier for user_data_dir isolation

        Returns:

        """
        utils.logger.info(
            "[BaiduTieBaCrawler.launch_browser] Begin create browser context ..."
        )
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
            # Use account-specific user_data_dir for multi-account isolation
            dir_name = f"{config.PLATFORM}_{account_id}" if account_id else config.USER_DATA_DIR % config.PLATFORM
            user_data_dir = os.path.join(
                os.getcwd(), "browser_data", dir_name
            )  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
                channel="chrome",  # Use system's stable Chrome version
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")  # type: ignore
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
        """
        Launch browser using CDP mode
        """
        try:
            cdp_manager = CDPBrowserManager()
            browser_context = await cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await cdp_manager.get_browser_info()
            utils.logger.info(f"[TieBaCrawler] CDP browser info: {browser_info}")

            # Store cdp_manager on the session for cleanup
            for s in self.account_manager.sessions:
                if s.account_id == account_id:
                    s.cdp_manager = cdp_manager
                    break

            return browser_context

        except Exception as e:
            utils.logger.error(f"[TieBaCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(
                chromium, playwright_proxy, user_agent, headless, account_id
            )

    async def close(self):
        """
        Close browser context
        Returns:

        """
        await self.account_manager.close_all()
        utils.logger.info("[BaiduTieBaCrawler.close] All browser contexts closed ...")
