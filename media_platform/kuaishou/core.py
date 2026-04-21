# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/kuaishou/core.py
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
import time
from asyncio import Task
from typing import Dict, List, Optional

import config
from account import AccountManager, AccountSession
from base.base_crawler import AbstractCrawler
from model.m_kuaishou import CreatorUrlInfo
from store import kuaishou as kuaishou_store
from tools import utils
from tools.checkpoint import CheckpointManager
from var import comment_tasks_var, crawler_type_var, source_keyword_var

from .client import KuaiShouClient
from .exception import DataFetchError
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import KuaishouLogin


class KuaishouCrawler(AbstractCrawler):

    def __init__(self):
        self.index_url = "https://www.kuaishou.com"
        self.user_agent = utils.get_user_agent()
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
        utils.logger.info("[KuaishouCrawler.start] Kuaishou Crawler finished ...")

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
                login_obj_factory=lambda s: KuaishouLogin(
                    login_type=s.login_type,
                    login_phone="",
                    browser_context=s.browser_context,
                    context_page=s.context_page,
                    cookie_str=s.cookie_str,
                ),
                index_url=f"{self.index_url}?isHome=1",
                stealth_js_path="libs/stealth.min.js",
            )
        return cookie_str, cookie_dict

    async def _crawl_with_session(self, session: AccountSession, semaphore: asyncio.Semaphore):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_videos(session)
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_videos(session)
            elif config.CRAWLER_TYPE == "feed":
                await self.feed(session)
        except Exception as ex:
            utils.logger.error(
                f"[KuaishouCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    def _create_client_from_cookies(self, session: AccountSession, cookie_str: str, cookie_dict: Dict) -> KuaiShouClient:
        """Create KuaiShou client from cookie string and dict (no browser required)."""
        utils.logger.info(
            f"[KuaishouCrawler._create_client_from_cookies] Creating client for account '{session.account_id}'"
        )
        client = KuaiShouClient(
            proxy=session.httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": self.index_url,
                "Referer": self.index_url,
                "Content-Type": "application/json;charset=UTF-8",
            },
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return client

    async def search(self, session: Optional[AccountSession] = None):
        utils.logger.info("[KuaishouCrawler.search] Begin search kuaishou keywords")
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        ks_limit_count = 20  # kuaishou limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < ks_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = ks_limit_count
        start_page = config.START_PAGE
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[KuaishouCrawler.search] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[KuaishouCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            search_session_id = keyword_progress.get("cursor_token", "") if keyword_progress else ""
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(
                f"[KuaishouCrawler.search] Current search keyword: {keyword}, start page: {page}"
            )
            while (
                page - start_page + 1
            ) * ks_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[KuaishouCrawler.search] Skip page: {page}")
                    page += 1
                    continue
                utils.logger.info(
                    f"[KuaishouCrawler.search] search kuaishou keyword: {keyword}, page: {page}"
                )
                video_id_list: List[str] = []
                videos_res = await client.search_info_by_keyword(
                    keyword=keyword,
                    pcursor=str(page),
                    search_session_id=search_session_id,
                )
                if not videos_res:
                    utils.logger.error(
                        f"[KuaishouCrawler.search] search info by keyword:{keyword} not found data"
                    )
                    continue

                vision_search_photo: Dict = videos_res.get("visionSearchPhoto")
                if vision_search_photo.get("result") != 1:
                    utils.logger.error(
                        f"[KuaishouCrawler.search] search info by keyword:{keyword} not found data "
                    )
                    continue
                search_session_id = vision_search_photo.get("searchSessionId", "")
                for video_detail in vision_search_photo.get("feeds"):
                    video_id_list.append(video_detail.get("photo", {}).get("id"))
                    await kuaishou_store.update_kuaishou_video(video_item=video_detail)

                # batch fetch video comments
                page += 1

                # 每页成功后保存 checkpoint（含 search_session_id）
                checkpoint.save_checkpoint(keyword=keyword, page=page, cursor_token=search_session_id)

                # Sleep after page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                await self.batch_get_video_comments(video_id_list, session=session)

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def get_specified_videos(self, session: Optional[AccountSession] = None):
        """Get the information and comments of the specified post"""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info("[KuaishouCrawler.get_specified_videos] Parsing video URLs...")
        video_ids = []
        for video_url in config.KS_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)
                video_ids.append(video_info.video_id)
                utils.logger.info(f"Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_video_info_task(video_id=video_id, semaphore=semaphore, client=client)
            for video_id in video_ids
        ]
        video_details = await asyncio.gather(*task_list)
        for video_detail in video_details:
            if video_detail is not None:
                await kuaishou_store.update_kuaishou_video(video_detail)
        await self.batch_get_video_comments(video_ids, session=session)

    async def get_video_info_task(
        self, video_id: str, semaphore: asyncio.Semaphore, client: Optional[KuaiShouClient] = None
    ) -> Optional[Dict]:
        """Get video detail task"""
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                result = await _client.get_video_info(video_id)

                # Sleep after fetching video details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.get_video_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {video_id}")

                utils.logger.info(
                    f"[KuaishouCrawler.get_video_info_task] Get video_id:{video_id} info result: {result} ..."
                )
                return result.get("visionVideoDetail")
            except DataFetchError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_video_info_task] Get video detail error: {ex}"
                )
                return None
            except KeyError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_video_info_task] have not fund video detail video_id:{video_id}, err: {ex}"
                )
                return None

    async def batch_get_video_comments(self, video_id_list: List[str], session: Optional[AccountSession] = None):
        """
        batch get video comments
        :param video_id_list:
        :param session: Account session for multi-account support
        :return:
        """
        _session = session or (self.account_manager.sessions[0] if self.account_manager.sessions else None)
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(
                f"[KuaishouCrawler.batch_get_video_comments] Crawling comment mode is not enabled"
            )
            return

        utils.logger.info(
            f"[KuaishouCrawler.batch_get_video_comments] video ids:{video_id_list}"
        )
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for video_id in video_id_list:
            task = asyncio.create_task(
                self.get_comments(video_id, semaphore, session=_session), name=video_id
            )
            task_list.append(task)

        comment_tasks_var.set(task_list)
        await asyncio.gather(*task_list)

    async def get_comments(self, video_id: str, semaphore: asyncio.Semaphore, session: Optional[AccountSession] = None):
        """
        get comment for video id
        :param video_id:
        :param semaphore:
        :param session: Account session for multi-account support
        :return:
        """
        _session = session or (self.account_manager.sessions[0] if self.account_manager.sessions else None)
        _client = _session.api_client if _session else self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                utils.logger.info(
                    f"[KuaishouCrawler.get_comments] begin get video_id: {video_id} comments ..."
                )

                # Sleep before fetching comments
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for video {video_id}")

                await _client.get_video_all_comments(
                    photo_id=video_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=kuaishou_store.batch_update_ks_video_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
            except DataFetchError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_comments] get video_id: {video_id} comment error: {ex}"
                )
            except Exception as e:
                utils.logger.error(
                    f"[KuaishouCrawler.get_comments] may be been blocked, err:{e}"
                )
                # use time.sleep block main coroutine instead of asyncio.sleep and cancel running comment task
                # maybe kuaishou block our request, we will take a nap and update the cookie again
                current_running_tasks = comment_tasks_var.get()
                for task in current_running_tasks:
                    task.cancel()
                time.sleep(20)
                utils.logger.error(
                    "[KuaishouCrawler.get_comments] Blocked — cookie refresh via browser is not available in headless mode"
                )

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

    async def get_creators_and_videos(self, session: Optional[AccountSession] = None) -> None:
        """Get creator's videos and retrieve their comment information."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(
            "[KuaiShouCrawler.get_creators_and_videos] Begin get kuaishou creators"
        )
        for creator_url in config.KS_CREATOR_ID_LIST:
            try:
                # Parse creator URL to get user_id
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[KuaiShouCrawler.get_creators_and_videos] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                # get creator detail info from web html content
                createor_info: Dict = await client.get_creator_info(user_id=user_id)
                if createor_info:
                    await kuaishou_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[KuaiShouCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            # Get all video information of the creator
            all_video_list = await client.get_all_videos_by_creator(
                user_id=user_id,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=self.fetch_creator_video_detail,
            )

            video_ids = [
                video_item.get("photo", {}).get("id") for video_item in all_video_list
            ]
            await self.batch_get_video_comments(video_ids, session=session)

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_video_info_task(post_item.get("photo", {}).get("id"), semaphore)
            for post_item in video_list
        ]

        video_details = await asyncio.gather(*task_list)
        for video_detail in video_details:
            if video_detail is not None:
                await kuaishou_store.update_kuaishou_video(video_detail)

    async def feed(self, session: Optional[AccountSession] = None) -> None:
        """Crawl kuaishou home feed videos."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[KuaishouCrawler.feed] Begin crawl kuaishou home feed (account: {session.account_id if session else 'default'})")

        feed_category = config.FEED_CATEGORY.lower()
        feed_type_map = {
            "recommend": "recommend",
            "hot": "hot",
            "follow": "follow",
        }
        feed_type = feed_type_map.get(feed_category, "recommend")
        utils.logger.info(f"[KuaishouCrawler.feed] Feed category: {feed_category}, feed type: {feed_type}")

        pcursor = ""
        total_count = 0
        max_pages = config.FEED_MAX_PAGES

        for page in range(1, max_pages + 1):
            try:
                utils.logger.info(f"[KuaishouCrawler.feed] Crawling home feed page {page}")
                feed_res = await client.get_homefeed_videos(feed_type=feed_type, pcursor=pcursor)

                feeds = feed_res.get("feeds", []) if feed_res else []
                if not feeds:
                    utils.logger.info("[KuaishouCrawler.feed] No more feed videos")
                    break

                photo_ids = []
                for feed_item in feeds:
                    photo_id = feed_item.get("photo", {}).get("id", "") or feed_item.get("id", "")
                    if photo_id:
                        await kuaishou_store.update_kuaishou_video(feed_item)
                        photo_ids.append(photo_id)
                        total_count += 1

                # Get comments
                if config.ENABLE_GET_COMMENTS:
                    await self.batch_get_video_comments(photo_ids, session=session)

                pcursor = feed_res.get("pcursor", "")
                if pcursor == "no_more":
                    break

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.feed] Page {page} done, total: {total_count}")
            except Exception as e:
                utils.logger.error(f"[KuaishouCrawler.feed] Error on page {page}: {e}")
                break

        utils.logger.info(f"[KuaishouCrawler.feed] Home feed crawl finished, total videos: {total_count}")

    async def close(self):
        """Close all browser contexts"""
        await self.account_manager.close_all()
        utils.logger.info("[KuaishouCrawler.close] All browser contexts closed ...")
