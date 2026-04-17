# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

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
import random
from asyncio import Task
from typing import Dict, List, Optional

from tenacity import RetryError

import config
from account import AccountManager, AccountSession
from base.base_crawler import AbstractCrawler
from model.m_xiaohongshu import NoteUrlInfo, CreatorUrlInfo
from store import xhs as xhs_store
from tools import utils
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import XiaoHongShuClient
from .exception import DataFetchError, NoteNotFoundError
from .field import SearchSortType
from .help import parse_note_info_from_note_url, parse_creator_info_from_url, get_search_id
from .login import XiaoHongShuLogin


class XiaoHongShuCrawler(AbstractCrawler):

    def __init__(self) -> None:
        self.index_url = "https://www.rednote.com" if config.XHS_INTERNATIONAL else "https://www.xiaohongshu.com"
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.account_manager = AccountManager()

    async def start(self) -> None:
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
        utils.logger.info("[XiaoHongShuCrawler.start] Xhs Crawler finished ...")

    async def _login_via_playwright(self, session):
        """Launch Playwright for login only, extract cookies, close browser."""
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            chromium = playwright.chromium
            cookie_str, cookie_dict = await self.account_manager.login_via_playwright(
                session=session,
                playwright=playwright,
                chromium=chromium,
                user_agent=self.user_agent,
                launch_browser_fn=self._launch_browser,
                login_obj_factory=lambda s: XiaoHongShuLogin(
                    login_type=s.login_type,
                    login_phone="",
                    browser_context=s.browser_context,
                    context_page=s.context_page,
                    cookie_str=s.cookie_str,
                ),
                index_url=self.index_url,
                stealth_js_path="libs/stealth.min.js",
            )
        return cookie_str, cookie_dict

    async def _crawl_with_session(self, session: AccountSession, semaphore: asyncio.Semaphore):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_notes(session)
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_notes(session)
        except Exception as ex:
            utils.logger.error(
                f"[XiaoHongShuCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    def _create_client_from_cookies(self, session: AccountSession, cookie_str: str, cookie_dict: Dict) -> XiaoHongShuClient:
        """Create XHS client from cookie string and dict (no browser required)."""
        utils.logger.info(
            f"[XiaoHongShuCrawler._create_client_from_cookies] Creating client for account '{session.account_id}'"
        )
        client = XiaoHongShuClient(
            proxy=session.httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": self.index_url,
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": f"{self.index_url}/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return client

    async def search(self, session: Optional[AccountSession] = None) -> None:
        """Search for notes and retrieve their comment information."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[XiaoHongShuCrawler.search] Begin search (account: {session.account_id if session else 'default'})")
        xhs_limit_count = 20
        if config.CRAWLER_MAX_NOTES_COUNT < xhs_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = xhs_limit_count
        start_page = config.START_PAGE
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[XiaoHongShuCrawler.search] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[XiaoHongShuCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(f"[XiaoHongShuCrawler.search] Current search keyword: {keyword}, start page: {page}")
            search_id = get_search_id()
            while (page - start_page + 1) * xhs_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Skip page {page}")
                    page += 1
                    continue

                try:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] search Xiaohongshu keyword: {keyword}, page: {page}")
                    note_ids: List[str] = []
                    xsec_tokens: List[str] = []
                    notes_res = await client.get_note_by_keyword(
                        keyword=keyword,
                        search_id=search_id,
                        page=page,
                        sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE != "" else SearchSortType.GENERAL),
                    )
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Search notes response: {notes_res}")
                    if not notes_res or not notes_res.get("has_more", False):
                        utils.logger.info("[XiaoHongShuCrawler.search] No more content!")
                        break
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
                        self.get_note_detail_async_task(
                            note_id=post_item.get("id"),
                            xsec_source=post_item.get("xsec_source"),
                            xsec_token=post_item.get("xsec_token"),
                            semaphore=semaphore,
                            client=client,
                        ) for post_item in notes_res.get("items", {}) if post_item.get("model_type") not in ("rec_query", "hot_query")
                    ]
                    note_details = await asyncio.gather(*task_list)
                    for note_detail in note_details:
                        if note_detail:
                            await xhs_store.update_xhs_note(note_detail)
                            await self.get_notice_media(note_detail, client)
                            note_ids.append(note_detail.get("note_id"))
                            xsec_tokens.append(note_detail.get("xsec_token"))
                    page += 1
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Note details: {note_details}")
                    await self.batch_get_note_comments(note_ids, xsec_tokens, client)

                    checkpoint.save_checkpoint(keyword=keyword, page=page)

                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
                except DataFetchError:
                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")
                    break

            checkpoint.mark_keyword_completed(keyword)

        checkpoint.clear_checkpoint()

    async def get_creators_and_notes(self, session: Optional[AccountSession] = None) -> None:
        """Get creator's notes and retrieve their comment information."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] Begin get Xiaohongshu creators")
        for creator_url in config.XHS_CREATOR_ID_LIST:
            try:
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                createor_info: Dict = await client.get_creator_info(
                    user_id=user_id,
                    xsec_token=creator_info.xsec_token,
                    xsec_source=creator_info.xsec_source
                )
                if createor_info:
                    await xhs_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[XiaoHongShuCrawler.get_creators_and_notes] Failed to parse creator URL: {e}")
                continue

            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            all_notes_list = await client.get_all_notes_by_creator(
                user_id=user_id,
                crawl_interval=crawl_interval,
                callback=self.fetch_creator_notes_detail,
                xsec_token=creator_info.xsec_token,
                xsec_source=creator_info.xsec_source,
            )

            note_ids = []
            xsec_tokens = []
            for note_item in all_notes_list:
                note_ids.append(note_item.get("note_id"))
                xsec_tokens.append(note_item.get("xsec_token"))
            await self.batch_get_note_comments(note_ids, xsec_tokens, client)

    async def fetch_creator_notes_detail(self, note_list: List[Dict]):
        """Concurrently obtain the specified post list and save the data"""
        # Note: when called from client callback, uses the session's client
        # This method is called internally by client, client reference is implicit
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(
                note_id=post_item.get("note_id"),
                xsec_source=post_item.get("xsec_source"),
                xsec_token=post_item.get("xsec_token"),
                semaphore=semaphore,
            ) for post_item in note_list
        ]

        note_details = await asyncio.gather(*task_list)
        for note_detail in note_details:
            if note_detail:
                await xhs_store.update_xhs_note(note_detail)
                await self.get_notice_media(note_detail)

    async def get_specified_notes(self, session: Optional[AccountSession] = None):
        """Get the information and comments of the specified post"""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        get_note_detail_task_list = []
        for full_note_url in config.XHS_SPECIFIED_NOTE_URL_LIST:
            note_url_info: NoteUrlInfo = parse_note_info_from_note_url(full_note_url)
            utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Parse note url info: {note_url_info}")
            crawler_task = self.get_note_detail_async_task(
                note_id=note_url_info.note_id,
                xsec_source=note_url_info.xsec_source,
                xsec_token=note_url_info.xsec_token,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
                client=client,
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_note_ids = []
        xsec_tokens = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for note_detail in note_details:
            if note_detail:
                need_get_comment_note_ids.append(note_detail.get("note_id", ""))
                xsec_tokens.append(note_detail.get("xsec_token", ""))
                await xhs_store.update_xhs_note(note_detail)
                await self.get_notice_media(note_detail, client)
        await self.batch_get_note_comments(need_get_comment_note_ids, xsec_tokens, client)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        semaphore: asyncio.Semaphore,
        client: Optional[XiaoHongShuClient] = None,
    ) -> Optional[Dict]:
        """Get note detail"""
        _client = client or self.account_manager.sessions[0].api_client
        note_detail = None
        utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")
        async with semaphore:
            try:
                try:
                    note_detail = await _client.get_note_by_id(note_id, xsec_source, xsec_token)
                except RetryError:
                    pass

                if not note_detail:
                    note_detail = await _client.get_note_by_id_from_html(note_id, xsec_source, xsec_token,
                                                                                 enable_cookie=True)
                    if not note_detail:
                        raise Exception(f"[get_note_detail_async_task] Failed to get note detail, Id: {note_id}")

                note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note {note_id}")

                return note_detail

            except NoteNotFoundError as ex:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_async_task] Note not found: {note_id}, {ex}")
                return None
            except DataFetchError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def batch_get_note_comments(self, note_list: List[str], xsec_tokens: List[str], client: Optional[XiaoHongShuClient] = None):
        """Batch get note comments"""
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Begin batch get note comments, note list: {note_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for index, note_id in enumerate(note_list):
            task = asyncio.create_task(
                self.get_comments(note_id=note_id, xsec_token=xsec_tokens[index], semaphore=semaphore, client=_client),
                name=note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, note_id: str, xsec_token: str, semaphore: asyncio.Semaphore, client: Optional[XiaoHongShuClient] = None):
        """Get note comments with keyword filtering and quantity limitation"""
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Begin get note id comments {note_id}")
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            await _client.get_note_all_comments(
                note_id=note_id,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=xhs_store.batch_update_xhs_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

            await asyncio.sleep(crawl_interval)
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for note {note_id}")

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
            user_data_dir = os.path.join(os.getcwd(), "browser_data", dir_name)
            return await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
            )
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)
            return await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)

    async def close(self):
        """Close all browser contexts"""
        await self.account_manager.close_all()
        utils.logger.info("[XiaoHongShuCrawler.close] All browser contexts closed ...")

    async def get_notice_media(self, note_detail: Dict, client: Optional[XiaoHongShuClient] = None):
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[XiaoHongShuCrawler.get_notice_media] Crawling image mode is not enabled")
            return
        await self.get_note_images(note_detail, _client)
        await self.get_notice_video(note_detail, _client)

    async def get_note_images(self, note_item: Dict, client: Optional[XiaoHongShuClient] = None):
        """Get note images."""
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")
        image_list: List[Dict] = note_item.get("image_list", [])

        for img in image_list:
            if img.get("url_default") != "":
                img.update({"url": img.get("url_default")})

        if not image_list:
            return
        picNum = 0
        for pic in image_list:
            url = pic.get("url")
            if not url:
                continue
            content = await _client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum}.jpg"
            picNum += 1
            await xhs_store.update_xhs_note_image(note_id, content, extension_file_name)

    async def get_notice_video(self, note_item: Dict, client: Optional[XiaoHongShuClient] = None):
        """Get note videos."""
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")

        videos = xhs_store.get_video_url_arr(note_item)

        if not videos:
            return
        videoNum = 0
        for url in videos:
            content = await _client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{videoNum}.mp4"
            videoNum += 1
            await xhs_store.update_xhs_note_video(note_id, content, extension_file_name)
