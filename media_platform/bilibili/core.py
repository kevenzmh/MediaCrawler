# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/bilibili/core.py
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
# @Time    : 2023/12/2 18:44
# @Desc    : Bilibili Crawler

import asyncio
import os
# import random  # Removed as we now use fixed config.CRAWLER_MAX_SLEEP_SEC intervals
from asyncio import Task
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
import pandas as pd

import config
from account import AccountManager, AccountSession
from base.base_crawler import AbstractCrawler
from store import bilibili as bilibili_store
from tools import utils
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import BilibiliClient
from .exception import DataFetchError
from .field import SearchOrderType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import BilibiliLogin


class BilibiliCrawler(AbstractCrawler):

    def __init__(self):
        self.index_url = "https://www.bilibili.com"
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
        utils.logger.info("[BilibiliCrawler.start] Bilibili Crawler finished ...")

    async def _crawl_with_session(self, session: AccountSession, semaphore: asyncio.Semaphore):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_videos(config.BILI_SPECIFIED_ID_LIST, session)
            elif config.CRAWLER_TYPE == "creator":
                if config.CREATOR_MODE:
                    for creator_url in config.BILI_CREATOR_ID_LIST:
                        try:
                            creator_info = parse_creator_info_from_url(creator_url)
                            utils.logger.info(f"[BilibiliCrawler._crawl_with_session] Parsed creator ID: {creator_info.creator_id} from {creator_url}")
                            await self.get_creator_videos(int(creator_info.creator_id), session)
                        except ValueError as e:
                            utils.logger.error(f"[BilibiliCrawler._crawl_with_session] Failed to parse creator URL: {e}")
                            continue
                else:
                    await self.get_all_creator_details(config.BILI_CREATOR_ID_LIST, session)
        except Exception as ex:
            utils.logger.error(
                f"[BilibiliCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    def _create_client_from_cookies(self, session: AccountSession, cookie_str: str, cookie_dict: Dict) -> BilibiliClient:
        """Create Bilibili client from cookie string and dict (no browser needed)."""
        utils.logger.info(
            f"[BilibiliCrawler._create_client_from_cookies] Creating client for account '{session.account_id}'"
        )
        client = BilibiliClient(
            proxy=session.httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": "https://www.bilibili.com",
                "Referer": "https://www.bilibili.com",
                "Content-Type": "application/json;charset=UTF-8",
            },
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return client

    async def _login_via_playwright(self, session: AccountSession) -> Tuple[str, Dict]:
        """Launch Playwright only for login, extract cookies, close browser."""
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            chromium = playwright.chromium
            return await self.account_manager.login_via_playwright(
                session=session,
                playwright=playwright,
                chromium=chromium,
                user_agent=self.user_agent,
                launch_browser_fn=self._launch_browser,
                login_obj_factory=lambda s: BilibiliLogin(
                    login_type=s.login_type,
                    login_phone="",
                    browser_context=s.browser_context,
                    context_page=s.context_page,
                    cookie_str=s.cookie_str,
                ),
                index_url=self.index_url,
                stealth_js_path="libs/stealth.min.js",
            )

    async def search(self, session: Optional[AccountSession] = None):
        """
        search bilibili video
        """
        if config.BILI_SEARCH_MODE == "normal":
            await self.search_by_keywords(session)
        elif config.BILI_SEARCH_MODE == "all_in_time_range":
            await self.search_by_keywords_in_time_range(daily_limit=False, session=session)
        elif config.BILI_SEARCH_MODE == "daily_limit_in_time_range":
            await self.search_by_keywords_in_time_range(daily_limit=True, session=session)
        else:
            utils.logger.warning(f"Unknown BILI_SEARCH_MODE: {config.BILI_SEARCH_MODE}")

    @staticmethod
    async def get_pubtime_datetime(
        start: str = config.START_DAY,
        end: str = config.END_DAY,
    ) -> Tuple[str, str]:
        """
        Get bilibili publish start timestamp pubtime_begin_s and publish end timestamp pubtime_end_s
        ---
        :param start: Publish date start time, YYYY-MM-DD
        :param end: Publish date end time, YYYY-MM-DD

        Note
        ---
        - Search time range is from start to end, including both start and end
        - To search content from the same day, to include search content from that day, pubtime_end_s should be pubtime_begin_s plus one day minus one second, i.e., the last second of start day
            - For example, searching only 2024-01-05 content, pubtime_begin_s = 1704384000, pubtime_end_s = 1704470399
              Converted to readable datetime objects: pubtime_begin_s = datetime.datetime(2024, 1, 5, 0, 0), pubtime_end_s = datetime.datetime(2024, 1, 5, 23, 59, 59)
        - To search content from start to end, to include search content from end day, pubtime_end_s should be pubtime_end_s plus one day minus one second, i.e., the last second of end day
            - For example, searching 2024-01-05 - 2024-01-06 content, pubtime_begin_s = 1704384000, pubtime_end_s = 1704556799
              Converted to readable datetime objects: pubtime_begin_s = datetime.datetime(2024, 1, 5, 0, 0), pubtime_end_s = datetime.datetime(2024, 1, 6, 23, 59, 59)
        """
        # Convert start and end to datetime objects
        start_day: datetime = datetime.strptime(start, "%Y-%m-%d")
        end_day: datetime = datetime.strptime(end, "%Y-%m-%d")
        if start_day > end_day:
            raise ValueError("Wrong time range, please check your start and end argument, to ensure that the start cannot exceed end")
        elif start_day == end_day:  # Searching content from the same day
            end_day = (start_day + timedelta(days=1) - timedelta(seconds=1))  # Set end_day to start_day + 1 day - 1 second
        else:  # Searching from start to end
            end_day = (end_day + timedelta(days=1) - timedelta(seconds=1))  # Set end_day to end_day + 1 day - 1 second
        # Convert back to timestamps
        return str(int(start_day.timestamp())), str(int(end_day.timestamp()))

    async def search_by_keywords(self, session: Optional[AccountSession] = None):
        """
        search bilibili video with keywords in normal mode
        :return:
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Begin search bilibli keywords (account: {session.account_id if session else 'default'})")
        bili_limit_count = 20  # bilibili limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < bili_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = bili_limit_count
        start_page = config.START_PAGE  # start page number
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[BilibiliCrawler.search_by_keywords] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] 关键词 '{keyword}' 已完成，跳过")
                continue
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Current search keyword: {keyword}, start page: {page}")
            while (page - start_page + 1) * bili_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Skip page: {page}")
                    page += 1
                    continue

                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] search bilibili keyword: {keyword}, page: {page}")
                video_id_list: List[str] = []
                videos_res = await client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=SearchOrderType.DEFAULT,
                    pubtime_begin_s=0,  # Publish date start timestamp
                    pubtime_end_s=0,  # Publish date end timestamp
                )
                video_list: List[Dict] = videos_res.get("result")

                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                task_list = []
                try:
                    task_list = [self.get_video_info_task(aid=video_item.get("aid"), bvid="", semaphore=semaphore, client=client) for video_item in video_list]
                except Exception as e:
                    utils.logger.warning(f"[BilibiliCrawler.search_by_keywords] error in the task list. The video for this page will not be included. {e}")
                video_items = await asyncio.gather(*task_list)
                for video_item in video_items:
                    if video_item:
                        video_id_list.append(video_item.get("View").get("aid"))
                        await bilibili_store.update_bilibili_video(video_item)
                        await bilibili_store.update_up_info(video_item)
                        await self.get_bilibili_video(video_item, semaphore, client)
                page += 1

                # 每页成功后保存 checkpoint
                checkpoint.save_checkpoint(keyword=keyword, page=page)

                # Sleep after page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                await self.batch_get_video_comments(video_id_list, client)

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def search_by_keywords_in_time_range(self, daily_limit: bool, session: Optional[AccountSession] = None):
        """
        Search bilibili video with keywords in a given time range.
        :param daily_limit: if True, strictly limit the number of notes per day and total.
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Begin search with daily_limit={daily_limit} (account: {session.account_id if session else 'default'})")
        bili_limit_count = 20
        start_page = config.START_PAGE

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Current search keyword: {keyword}")
            total_notes_crawled_for_keyword = 0

            for day in pd.date_range(start=config.START_DAY, end=config.END_DAY, freq="D"):
                if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                    utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}', skipping remaining days.")
                    break

                if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                    utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}', skipping remaining days.")
                    break

                pubtime_begin_s, pubtime_end_s = await self.get_pubtime_datetime(start=day.strftime("%Y-%m-%d"), end=day.strftime("%Y-%m-%d"))
                page = 1
                notes_count_this_day = 0

                while True:
                    if notes_count_this_day >= config.MAX_NOTES_PER_DAY:
                        utils.logger.info(f"[BilibiliCrawler.search] Reached MAX_NOTES_PER_DAY limit for {day.ctime()}.")
                        break
                    if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                        utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}'.")
                        break
                    if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                        break

                    try:
                        utils.logger.info(f"[BilibiliCrawler.search] search bilibili keyword: {keyword}, date: {day.ctime()}, page: {page}")
                        video_id_list: List[str] = []
                        videos_res = await client.search_video_by_keyword(
                            keyword=keyword,
                            page=page,
                            page_size=bili_limit_count,
                            order=SearchOrderType.DEFAULT,
                            pubtime_begin_s=pubtime_begin_s,
                            pubtime_end_s=pubtime_end_s,
                        )
                        video_list: List[Dict] = videos_res.get("result")

                        if not video_list:
                            utils.logger.info(f"[BilibiliCrawler.search] No more videos for '{keyword}' on {day.ctime()}, moving to next day.")
                            break

                        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                        task_list = [self.get_video_info_task(aid=video_item.get("aid"), bvid="", semaphore=semaphore, client=client) for video_item in video_list]
                        video_items = await asyncio.gather(*task_list)

                        for video_item in video_items:
                            if video_item:
                                if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                                    break
                                if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                                    break
                                if notes_count_this_day >= config.MAX_NOTES_PER_DAY:
                                    break
                                notes_count_this_day += 1
                                total_notes_crawled_for_keyword += 1
                                video_id_list.append(video_item.get("View").get("aid"))
                                await bilibili_store.update_bilibili_video(video_item)
                                await bilibili_store.update_up_info(video_item)
                                await self.get_bilibili_video(video_item, semaphore, client)

                        page += 1

                        # Sleep after page navigation
                        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                        utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                        await self.batch_get_video_comments(video_id_list, client)

                    except Exception as e:
                        utils.logger.error(f"[BilibiliCrawler.search] Error searching on {day.ctime()}: {e}")
                        break

    async def batch_get_video_comments(self, video_id_list: List[str], client: Optional[BilibiliClient] = None):
        """
        batch get video comments
        :param video_id_list:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[BilibiliCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[BilibiliCrawler.batch_get_video_comments] video ids:{video_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for video_id in video_id_list:
            task = asyncio.create_task(self.get_comments(video_id, semaphore, client=_client), name=video_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, video_id: str, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        get comment for video id
        :param video_id:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_comments] begin get video_id: {video_id} comments ...")
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[BilibiliCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching comments for video {video_id}")
                await _client.get_video_all_comments(
                    video_id=video_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=bilibili_store.batch_update_bilibili_video_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_comments] get video_id: {video_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_comments] may be been blocked, err:{e}")
                # Propagate the exception to be caught by the main loop
                raise

    async def get_creator_videos(self, creator_id: int, session: Optional[AccountSession] = None):
        """
        get videos for a creator
        :return:
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        ps = 30
        pn = 1
        while True:
            result = await client.get_creator_videos(creator_id, pn, ps)
            video_bvids_list = [video["bvid"] for video in result["list"]["vlist"]]
            await self.get_specified_videos(video_bvids_list, session)
            if int(result["page"]["count"]) <= pn * ps:
                break
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(f"[BilibiliCrawler.get_creator_videos] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {pn}")
            pn += 1

    async def get_specified_videos(self, video_url_list: List[str], session: Optional[AccountSession] = None):
        """
        get specified videos info from URLs or BV IDs
        :param video_url_list: List of video URLs or BV IDs
        :param session:
        :return:
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info("[BilibiliCrawler.get_specified_videos] Parsing video URLs...")
        bvids_list = []
        for video_url in video_url_list:
            try:
                video_info = parse_video_info_from_url(video_url)
                bvids_list.append(video_info.video_id)
                utils.logger.info(f"[BilibiliCrawler.get_specified_videos] Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_specified_videos] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_video_info_task(aid=0, bvid=video_id, semaphore=semaphore, client=client) for video_id in bvids_list]
        video_details = await asyncio.gather(*task_list)
        video_aids_list = []
        for video_detail in video_details:
            if video_detail is not None:
                video_item_view: Dict = video_detail.get("View")
                video_aid: str = video_item_view.get("aid")
                if video_aid:
                    video_aids_list.append(video_aid)
                await bilibili_store.update_bilibili_video(video_detail)
                await bilibili_store.update_up_info(video_detail)
                await self.get_bilibili_video(video_detail, semaphore, client)
        await self.batch_get_video_comments(video_aids_list, client)

    async def get_video_info_task(self, aid: int, bvid: str, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None) -> Optional[Dict]:
        """
        Get video detail task
        :param aid:
        :param bvid:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                result = await _client.get_video_info(aid=aid, bvid=bvid)

                # Sleep after fetching video details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[BilibiliCrawler.get_video_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {bvid or aid}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] Get video detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] have not fund note detail video_id:{bvid}, err: {ex}")
                return None

    async def get_video_play_url_task(self, aid: int, cid: int, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None) -> Union[Dict, None]:
        """
        Get video play url
        :param aid:
        :param cid:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                result = await _client.get_video_play_url(aid=aid, cid=cid)
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_play_url_task] Get video play url error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_play_url_task] have not fund play url from :{aid}|{cid}, err: {ex}")
                return None

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
            dir_name = f"{config.PLATFORM}_{account_id}" if account_id else config.USER_DATA_DIR % config.PLATFORM  # type: ignore
            user_data_dir = os.path.join(os.getcwd(), "browser_data", dir_name)
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

    async def close(self):
        """Close browser context"""
        await self.account_manager.close_all()
        utils.logger.info("[BilibiliCrawler.close] Browser context closed ...")

    async def get_bilibili_video(self, video_item: Dict, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        download bilibili video
        :param video_item:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[BilibiliCrawler.get_bilibili_video] Crawling image mode is not enabled")
            return
        video_item_view: Dict = video_item.get("View")
        aid = video_item_view.get("aid")
        cid = video_item_view.get("cid")
        result = await self.get_video_play_url_task(aid, cid, semaphore, client=_client)
        if result is None:
            utils.logger.info("[BilibiliCrawler.get_bilibili_video] get video play url failed")
            return
        durl_list = result.get("durl")
        max_size = -1
        video_url = ""
        for durl in durl_list:
            size = durl.get("size")
            if size > max_size:
                max_size = size
                video_url = durl.get("url")
        if video_url == "":
            utils.logger.info("[BilibiliCrawler.get_bilibili_video] get video url failed")
            return

        content = await _client.get_video_media(video_url)
        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        utils.logger.info(f"[BilibiliCrawler.get_bilibili_video] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video {aid}")
        if content is None:
            return
        extension_file_name = f"video.mp4"
        await bilibili_store.store_video(aid, content, extension_file_name)

    async def get_all_creator_details(self, creator_url_list: List[str], session: Optional[AccountSession] = None):
        """
        creator_url_list: get details for creator from creator URL list
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Crawling the details of creators")
        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Parsing creator URLs...")

        creator_id_list = []
        for creator_url in creator_url_list:
            try:
                creator_info = parse_creator_info_from_url(creator_url)
                creator_id_list.append(int(creator_info.creator_id))
                utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Parsed creator ID: {creator_info.creator_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_all_creator_details] Failed to parse creator URL: {e}")
                continue

        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] creator ids:{creator_id_list}")

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        try:
            for creator_id in creator_id_list:
                task = asyncio.create_task(self.get_creator_details(creator_id, semaphore, client=client), name=str(creator_id))
                task_list.append(task)
        except Exception as e:
            utils.logger.warning(f"[BilibiliCrawler.get_all_creator_details] error in the task list. The creator will not be included. {e}")

        await asyncio.gather(*task_list)

    async def get_creator_details(self, creator_id: int, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        get details for creator id
        :param creator_id:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            creator_unhandled_info: Dict = await _client.get_creator_info(creator_id)
            creator_info: Dict = {
                "id": creator_id,
                "name": creator_unhandled_info.get("name"),
                "sign": creator_unhandled_info.get("sign"),
                "avatar": creator_unhandled_info.get("face"),
            }
        await self.get_fans(creator_info, semaphore, client=_client)
        await self.get_followings(creator_info, semaphore, client=_client)
        await self.get_dynamics(creator_info, semaphore, client=_client)

    async def get_fans(self, creator_info: Dict, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        get fans for creator id
        :param creator_info:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_fans] begin get creator_id: {creator_id} fans ...")
                await _client.get_creator_all_fans(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_fans,
                    max_count=config.CRAWLER_MAX_CONTACTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_fans] get creator_id: {creator_id} fans error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_fans] may be been blocked, err:{e}")

    async def get_followings(self, creator_info: Dict, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        get followings for creator id
        :param creator_info:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_followings] begin get creator_id: {creator_id} followings ...")
                await _client.get_creator_all_followings(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_followings,
                    max_count=config.CRAWLER_MAX_CONTACTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_followings] get creator_id: {creator_id} followings error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_followings] may be been blocked, err:{e}")

    async def get_dynamics(self, creator_info: Dict, semaphore: asyncio.Semaphore, client: Optional[BilibiliClient] = None):
        """
        get dynamics for creator id
        :param creator_info:
        :param semaphore:
        :param client:
        :return:
        """
        _client = client or self.account_manager.sessions[0].api_client
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_dynamics] begin get creator_id: {creator_id} dynamics ...")
                await _client.get_creator_all_dynamics(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_dynamics,
                    max_count=config.CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_dynamics] get creator_id: {creator_id} dynamics error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_dynamics] may be been blocked, err:{e}")
