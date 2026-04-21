# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/core.py
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

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/23 15:41
# @Desc    : Weibo crawler main workflow code

import asyncio
import os
from asyncio import Task
from typing import Dict, List, Optional, Tuple

import config
from account import AccountManager, AccountSession
from base.base_crawler import AbstractCrawler
from store import weibo as weibo_store
from tools import utils
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import WeiboClient
from .exception import DataFetchError
from .field import SearchType
from .help import filter_search_result_card
from .login import WeiboLogin


class WeiboCrawler(AbstractCrawler):

    def __init__(self):
        self.index_url = "https://www.weibo.com"
        self.mobile_index_url = "https://m.weibo.cn"
        self.user_agent = utils.get_user_agent()
        self.mobile_user_agent = utils.get_mobile_user_agent()
        self.account_manager = AccountManager()

    async def start(self):
        sessions = await self.account_manager.create_sessions_headless(platform=config.PLATFORM)

        for session in sessions:
            cookie_str = session.cookie_str
            cookie_dict = utils.convert_str_cookie_to_dict(cookie_str) if cookie_str else {}

            if cookie_str:
                session.api_client = self._create_client_from_cookies(session, cookie_str, cookie_dict)
            else:
                cookie_str, cookie_dict = await self._login_via_playwright(session)
                session.api_client = self._create_client_from_cookies(session, cookie_str, cookie_dict)

            # Verify login
            if not await session.api_client.pong():
                cookie_str, cookie_dict = await self._login_via_playwright(session)
                session.api_client = self._create_client_from_cookies(session, cookie_str, cookie_dict)

        crawler_type_var.set(config.CRAWLER_TYPE)

        # Run crawl tasks in parallel across accounts
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        tasks = [
            self._crawl_with_session(session, semaphore)
            for session in sessions
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.account_manager.close_all()
        utils.logger.info("[WeiboCrawler.start] Weibo Crawler finished ...")

    async def _crawl_with_session(self, session: AccountSession, semaphore: asyncio.Semaphore):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_notes(session)
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_notes(session)
            elif config.CRAWLER_TYPE == "feed":
                await self.feed(session)
        except Exception as ex:
            utils.logger.error(
                f"[WeiboCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    def _create_client_from_cookies(self, session: AccountSession, cookie_str: str, cookie_dict: Dict) -> WeiboClient:
        """Create Weibo client from cookie string and dict (no browser needed)."""
        utils.logger.info(
            f"[WeiboCrawler._create_client_from_cookies] Creating client for account '{session.account_id}'"
        )
        weibo_client_obj = WeiboClient(
            proxy=session.httpx_proxy,
            headers={
                "User-Agent": self.mobile_user_agent,
                "Cookie": cookie_str,
                "Origin": "https://m.weibo.cn",
                "Referer": "https://m.weibo.cn",
                "Content-Type": "application/json;charset=UTF-8",
            },
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return weibo_client_obj

    async def _login_via_playwright(self, session: AccountSession) -> Tuple[str, Dict]:
        """Launch Playwright only for login, extract cookies, close browser."""
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            chromium = playwright.chromium

            async def post_login_hook(s: AccountSession):
                """After login, navigate to mobile site to get mobile cookies."""
                utils.logger.info("[WeiboCrawler._login_via_playwright] Redirecting to mobile homepage for mobile cookies")
                await s.context_page.goto(self.mobile_index_url)
                await asyncio.sleep(3)

            return await self.account_manager.login_via_playwright(
                session=session,
                playwright=playwright,
                chromium=chromium,
                user_agent=self.mobile_user_agent,
                launch_browser_fn=self._launch_browser,
                login_obj_factory=lambda s: WeiboLogin(
                    login_type=s.login_type,
                    login_phone="",
                    browser_context=s.browser_context,
                    context_page=s.context_page,
                    cookie_str=s.cookie_str,
                ),
                index_url=self.index_url,
                stealth_js_path="libs/stealth.min.js",
                post_login_hook=post_login_hook,
            )

    async def search(self, session: Optional[AccountSession] = None):
        """
        search weibo note with keywords
        :return:
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[WeiboCrawler.search] Begin search weibo keywords (account: {session.account_id if session else 'default'})")
        weibo_limit_count = 10  # weibo limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < weibo_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = weibo_limit_count
        start_page = config.START_PAGE

        # Set the search type based on the configuration for weibo
        if config.WEIBO_SEARCH_TYPE == "default":
            search_type = SearchType.DEFAULT
        elif config.WEIBO_SEARCH_TYPE == "real_time":
            search_type = SearchType.REAL_TIME
        elif config.WEIBO_SEARCH_TYPE == "popular":
            search_type = SearchType.POPULAR
        elif config.WEIBO_SEARCH_TYPE == "video":
            search_type = SearchType.VIDEO
        else:
            utils.logger.error(f"[WeiboCrawler.search] Invalid WEIBO_SEARCH_TYPE: {config.WEIBO_SEARCH_TYPE}")
            return

        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[WeiboCrawler.search] 发现断点续爬记录，从上次进度恢复")

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[WeiboCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}, start page: {page}")
            while (page - start_page + 1) * weibo_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[WeiboCrawler.search] Skip page: {page}")
                    page += 1
                    continue
                utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
                search_res = await client.get_note_by_keyword(keyword=keyword, page=page, search_type=search_type)
                note_id_list: List[str] = []
                note_list = filter_search_result_card(search_res.get("cards"))
                # If full text fetching is enabled, batch get full text of posts
                note_list = await self.batch_get_notes_full_text(note_list, client)
                for note_item in note_list:
                    if note_item:
                        mblog: Dict = note_item.get("mblog")
                        if mblog:
                            note_id_list.append(mblog.get("id"))
                            await weibo_store.update_weibo_note(note_item)
                            await self.get_note_images(mblog, client)

                page += 1

                # 每页成功后保存 checkpoint
                checkpoint.save_checkpoint(keyword=keyword, page=page)

                # Sleep after page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                await self.batch_get_notes_comments(note_id_list, client)

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def get_specified_notes(self, session: Optional[AccountSession] = None):
        """
        get specified notes info
        :return:
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_note_info_task(note_id=note_id, semaphore=semaphore, client=client) for note_id in config.WEIBO_SPECIFIED_ID_LIST]
        video_details = await asyncio.gather(*task_list)
        for note_item in video_details:
            if note_item:
                await weibo_store.update_weibo_note(note_item)
        await self.batch_get_notes_comments(config.WEIBO_SPECIFIED_ID_LIST, client)

    async def get_note_info_task(self, note_id: str, semaphore: asyncio.Semaphore, client: Optional[WeiboClient] = None) -> Optional[Dict]:
        """
        Get note detail task
        :param note_id:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                result = await _client.get_note_info_by_id(note_id)

                # Sleep after fetching note details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def batch_get_notes_comments(self, note_id_list: List[str], client: Optional[WeiboClient] = None):
        """
        batch get notes comments
        :param note_id_list:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[WeiboCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[WeiboCrawler.batch_get_notes_comments] note ids:{note_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_id in note_id_list:
            task = asyncio.create_task(self.get_note_comments(note_id, semaphore, _client), name=note_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_note_comments(self, note_id: str, semaphore: asyncio.Semaphore, client: Optional[WeiboClient] = None):
        """
        get comment for note id
        :param note_id:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                utils.logger.info(f"[WeiboCrawler.get_note_comments] begin get note_id: {note_id} comments ...")

                # Sleep before fetching comments
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.get_note_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_id}")

                await _client.get_note_all_comments(
                    note_id=note_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,  # Use fixed interval instead of random
                    callback=weibo_store.batch_update_weibo_note_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] may be been blocked, err:{e}")

    async def get_note_images(self, mblog: Dict, client: Optional[WeiboClient] = None):
        """
        get note images
        :param mblog:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[WeiboCrawler.get_note_images] Crawling image mode is not enabled")
            return

        pics: List = mblog.get("pics")
        if not pics:
            return
        for pic in pics:
            if isinstance(pic, str):
                url = pic
                pid = url.split("/")[-1].split(".")[0]
            elif isinstance(pic, dict):
                url = pic.get("url")
                pid = pic.get("pid", "")
            else:
                continue
            if not url:
                continue
            content = await _client.get_note_image(url)
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(f"[WeiboCrawler.get_note_images] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching image")
            if content != None:
                extension_file_name = url.split(".")[-1]
                await weibo_store.update_weibo_note_image(pid, content, extension_file_name)

    async def get_creators_and_notes(self, session: Optional[AccountSession] = None) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] Begin get weibo creators (account: {session.account_id if session else 'default'})")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            createor_info_res: Dict = await client.get_creator_info_by_id(creator_id=user_id)
            if createor_info_res:
                createor_info: Dict = createor_info_res.get("userInfo", {})
                utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] creator info: {createor_info}")
                if not createor_info:
                    raise DataFetchError("Get creator info error")
                await weibo_store.save_creator(user_id, user_info=createor_info)

                # Create a wrapper callback to get full text before saving data
                # Note: we capture `client` via default argument to avoid late-binding issues
                async def save_notes_with_full_text(note_list: List[Dict], _client: WeiboClient = client):
                    # If full text fetching is enabled, batch get full text first
                    updated_note_list = await self.batch_get_notes_full_text(note_list, _client)
                    await weibo_store.batch_update_weibo_notes(updated_note_list)

                # Get all note information of the creator
                all_notes_list = await client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=f"107603{user_id}",
                    crawl_interval=0,
                    callback=save_notes_with_full_text,
                )

                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes_list if note_item.get("mblog", {}).get("id")]
                await self.batch_get_notes_comments(note_ids, client)

            else:
                utils.logger.error(f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_id:{user_id}")

    async def _launch_browser(
        self,
        chromium,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
        account_id: str = "",
    ):
        """Launch browser for login only (Playwright is an optional dependency for headless crawling)."""
        if config.SAVE_LOGIN_STATE:
            dir_name = f"{config.PLATFORM}_{account_id}" if account_id else config.USER_DATA_DIR % config.PLATFORM
            user_data_dir = os.path.join(os.getcwd(), "browser_data", dir_name)  # type: ignore
            return await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
                channel="chrome",
            )
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")
            return await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)

    async def get_note_full_text(self, note_item: Dict, client: Optional[WeiboClient] = None) -> Dict:
        """
        Get full text content of a post
        If the post content is truncated (isLongText=True), request the detail API to get complete content
        :param note_item: Post data, contains mblog field
        :param client: WeiboClient instance
        :return: Updated post data
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_item

        mblog = note_item.get("mblog", {})
        if not mblog:
            return note_item

        # Check if it's a long text
        is_long_text = mblog.get("isLongText", False)
        if not is_long_text:
            return note_item

        note_id = mblog.get("id")
        if not note_id:
            return note_item

        try:
            utils.logger.info(f"[WeiboCrawler.get_note_full_text] Fetching full text for note: {note_id}")
            full_note = await _client.get_note_info_by_id(note_id)
            if full_note and full_note.get("mblog"):
                # Replace original content with complete content
                note_item["mblog"] = full_note["mblog"]
                utils.logger.info(f"[WeiboCrawler.get_note_full_text] Successfully fetched full text for note: {note_id}")

            # Sleep after request to avoid rate limiting
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        except DataFetchError as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Failed to fetch full text for note {note_id}: {ex}")
        except Exception as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Unexpected error for note {note_id}: {ex}")

        return note_item

    async def batch_get_notes_full_text(self, note_list: List[Dict], client: Optional[WeiboClient] = None) -> List[Dict]:
        """
        Batch get full text content of posts
        :param note_list: List of posts
        :param client: WeiboClient instance
        :return: Updated list of posts
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_list

        result = []
        for note_item in note_list:
            updated_note = await self.get_note_full_text(note_item, _client)
            result.append(updated_note)
        return result

    async def feed(self, session: Optional[AccountSession] = None) -> None:
        """Crawl weibo home feed posts."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[WeiboCrawler.feed] Begin crawl weibo home feed (account: {session.account_id if session else 'default'})")

        feed_category = config.FEED_CATEGORY.lower()
        feed_type_map = {
            "hot": "102803",
            "recommend": "102803_ctg1_600059",
        }
        feed_type = feed_type_map.get(feed_category, "102803")
        utils.logger.info(f"[WeiboCrawler.feed] Feed category: {feed_category}, feed type: {feed_type}")

        since_id = ""
        total_count = 0
        max_pages = config.FEED_MAX_PAGES

        for page in range(1, max_pages + 1):
            try:
                utils.logger.info(f"[WeiboCrawler.feed] Crawling home feed page {page}")
                feed_res = await client.get_homefeed_posts(feed_type=feed_type, since_id=since_id, page=page)

                cards = feed_res.get("cards", []) if feed_res else []
                if not cards:
                    utils.logger.info("[WeiboCrawler.feed] No more feed posts")
                    break

                note_ids = []
                for card in cards:
                    mblog = card.get("mblog", {})
                    if mblog and mblog.get("id"):
                        await weibo_store.update_weibo_note(card)
                        await self.get_note_images(mblog, client)
                        note_ids.append(str(mblog.get("id")))
                        total_count += 1

                # Get comments
                if config.ENABLE_GET_COMMENTS:
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
                        self.get_note_comments(note_id=note_id, semaphore=semaphore, client=client)
                        for note_id in note_ids
                    ]
                    await asyncio.gather(*task_list)

                since_id = feed_res.get("cardlistInfo", {}).get("since_id", "")
                if not since_id:
                    break

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[WeiboCrawler.feed] Page {page} done, total: {total_count}")
            except Exception as e:
                utils.logger.error(f"[WeiboCrawler.feed] Error on page {page}: {e}")
                break

        utils.logger.info(f"[WeiboCrawler.feed] Home feed crawl finished, total posts: {total_count}")

    async def close(self):
        """Close all browser contexts"""
        await self.account_manager.close_all()
        utils.logger.info("[WeiboCrawler.close] All browser contexts closed ...")
