# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py
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
from typing import Any, Dict, List, Optional, Tuple

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
from store import douyin as douyin_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import DouYinClient
from .exception import DataFetchError
from .field import PublishTimeType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import DouYinLogin


class DouYinCrawler(AbstractCrawler):

    def __init__(self) -> None:
        self.index_url = "https://www.douyin.com"
        self.account_manager = AccountManager()

    async def start(self) -> None:
        async with async_playwright() as playwright:
            chromium = playwright.chromium
            sessions = await self.account_manager.create_sessions(
                platform="dy",
                playwright=playwright,
                chromium=chromium,
                user_agent=None,
                launch_browser_fn=self.launch_browser,
                launch_cdp_fn=self.launch_browser_with_cdp,
                stealth_js_path="libs/stealth.min.js",
                index_url=self.index_url,
            )

            # Login and create client for each session
            for session in sessions:
                session.api_client = await self._create_client_for_session(session)
                if not await session.api_client.pong(browser_context=session.browser_context):
                    login_obj = DouYinLogin(
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
            semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
            tasks = [
                self._crawl_with_session(session, semaphore)
                for session in sessions
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.account_manager.close_all()
            utils.logger.info("[DouYinCrawler.start] Douyin Crawler finished ...")

    async def _crawl_with_session(self, session: AccountSession, semaphore: asyncio.Semaphore):
        """Run crawl logic for a single account session."""
        try:
            if config.CRAWLER_TYPE == "search":
                await self.search(session)
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_awemes(session)
            elif config.CRAWLER_TYPE == "creator":
                await self.get_creators_and_videos(session)
        except Exception as ex:
            utils.logger.error(
                f"[DouYinCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    async def _create_client_for_session(self, session: AccountSession) -> DouYinClient:
        """Create DouYin client for a specific account session."""
        utils.logger.info(
            f"[DouYinCrawler._create_client_for_session] Creating client for account '{session.account_id}'"
        )
        cookie_str, cookie_dict = utils.convert_cookies(
            await session.browser_context.cookies()
        )
        douyin_client = DouYinClient(
            proxy=session.httpx_proxy,
            headers={
                "User-Agent": await session.context_page.evaluate("() => navigator.userAgent"),
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=session.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return douyin_client

    async def search(self, session: Optional[AccountSession] = None) -> None:
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[DouYinCrawler.search] Begin search douyin keywords (account: {session.account_id if session else 'default'})")
        dy_limit_count = 10  # douyin limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < dy_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = dy_limit_count
        start_page = config.START_PAGE  # start page number
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[DouYinCrawler.search] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[DouYinCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            aweme_list: List[str] = []
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            dy_search_id = keyword_progress.get("cursor_token", "") if keyword_progress else ""
            utils.logger.info(f"[DouYinCrawler.search] Current keyword: {keyword}, start page: {page}")
            while (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[DouYinCrawler.search] Skip {page}")
                    page += 1
                    continue
                try:
                    utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page}")
                    posts_res = await client.search_info_by_keyword(
                        keyword=keyword,
                        offset=page * dy_limit_count - dy_limit_count,
                        publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                        search_id=dy_search_id,
                    )
                    if posts_res.get("data") is None or posts_res.get("data") == []:
                        utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page} is empty,{posts_res.get('data')}`")
                        break
                except DataFetchError:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed")
                    break

                page += 1
                if "data" not in posts_res:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed，账号也许被风控了。")
                    break
                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                page_aweme_list = []
                for post_item in posts_res.get("data"):
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    # 视频时长过滤
                    if config.DY_MIN_VIDEO_DURATION > 0 or config.DY_MAX_VIDEO_DURATION > 0:
                        duration_sec = aweme_info.get("video", {}).get("duration", 0) / 1000
                        if config.DY_MIN_VIDEO_DURATION > 0 and duration_sec < config.DY_MIN_VIDEO_DURATION:
                            utils.logger.info(f"[DouYinCrawler.search] 视频时长 {duration_sec:.0f}s 不满足最小 {config.DY_MIN_VIDEO_DURATION}s，跳过: {aweme_info.get('aweme_id')}")
                            continue
                        if config.DY_MAX_VIDEO_DURATION > 0 and duration_sec > config.DY_MAX_VIDEO_DURATION:
                            utils.logger.info(f"[DouYinCrawler.search] 视频时长 {duration_sec:.0f}s 超过最大 {config.DY_MAX_VIDEO_DURATION}s，跳过: {aweme_info.get('aweme_id')}")
                            continue
                    aweme_list.append(aweme_info.get("aweme_id", ""))
                    page_aweme_list.append(aweme_info.get("aweme_id", ""))
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    await self.get_aweme_media(aweme_item=aweme_info, client=client)

                # Batch get note comments for the current page
                await self.batch_get_note_comments(page_aweme_list, client=client)

                # 每页成功后保存 checkpoint（含 dy_search_id）
                checkpoint.save_checkpoint(keyword=keyword, page=page, cursor_token=dy_search_id)

                # Sleep after each page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
            utils.logger.info(f"[DouYinCrawler.search] keyword:{keyword}, aweme_list:{aweme_list}")

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def get_specified_awemes(self, session: Optional[AccountSession] = None):
        """Get the information and comments of the specified post from URLs or IDs"""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info("[DouYinCrawler.get_specified_awemes] Parsing video URLs...")
        aweme_id_list = []
        for video_url in config.DY_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)

                # Handling short links
                if video_info.url_type == "short":
                    utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Resolving short link: {video_url}")
                    resolved_url = await client.resolve_short_url(video_url)
                    if resolved_url:
                        # Extract video ID from parsed URL
                        video_info = parse_video_info_from_url(resolved_url)
                        utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Short link resolved to aweme ID: {video_info.aweme_id}")
                    else:
                        utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to resolve short link: {video_url}")
                        continue

                aweme_id_list.append(video_info.aweme_id)
                utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Parsed aweme ID: {video_info.aweme_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(aweme_id=aweme_id, semaphore=semaphore, client=client) for aweme_id in aweme_id_list]
        aweme_details = await asyncio.gather(*task_list)
        for aweme_detail in aweme_details:
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                await self.get_aweme_media(aweme_item=aweme_detail, client=client)
        await self.batch_get_note_comments(aweme_id_list, client=client)

    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore, client: Optional[DouYinClient] = None) -> Any:
        """Get note detail"""
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                result = await _client.get_video_by_id(aweme_id)
                # Sleep after fetching aweme detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.get_aweme_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching aweme {aweme_id}")
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] Get aweme detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] have not fund note detail aweme_id:{aweme_id}, err: {ex}")
                return None

    async def batch_get_note_comments(self, aweme_list: List[str], client: Optional[DouYinClient] = None) -> None:
        """
        Batch get note comments
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for aweme_id in aweme_list:
            task = asyncio.create_task(self.get_comments(aweme_id, semaphore, client=_client), name=aweme_id)
            task_list.append(task)
        if len(task_list) > 0:
            await asyncio.wait(task_list)

    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore, client: Optional[DouYinClient] = None) -> None:
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            try:
                # Pass the list of keywords to the get_aweme_all_comments method
                # Use fixed crawling interval
                crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
                await _client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=crawl_interval,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=douyin_store.batch_update_dy_aweme_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                # Sleep after fetching comments
                await asyncio.sleep(crawl_interval)
                utils.logger.info(f"[DouYinCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for aweme {aweme_id}")
                utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} comments have all been obtained and filtered ...")
            except DataFetchError as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed, error: {e}")

    async def get_creators_and_videos(self, session: Optional[AccountSession] = None) -> None:
        """
        Get the information and videos of the specified creator from URLs or IDs
        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Begin get douyin creators")
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Parsing creator URLs...")

        for creator_url in config.DY_CREATOR_ID_LIST:
            try:
                creator_info_parsed = parse_creator_info_from_url(creator_url)
                user_id = creator_info_parsed.sec_user_id
                utils.logger.info(f"[DouYinCrawler.get_creators_and_videos] Parsed sec_user_id: {user_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            creator_info: Dict = await client.get_user_info(user_id)
            if creator_info:
                await douyin_store.save_creator(user_id, creator=creator_info)

            # Get all video information of the creator
            all_video_list = await client.get_all_user_aweme_posts(sec_user_id=user_id, callback=self.fetch_creator_video_detail)

            video_ids = [video_item.get("aweme_id") for video_item in all_video_list]
            await self.batch_get_note_comments(video_ids, client=client)

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        # Note: when called from client callback, uses the session's client
        # This method is called internally by client, client reference is implicit
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(post_item.get("aweme_id"), semaphore) for post_item in video_list]

        note_details = await asyncio.gather(*task_list)
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                await self.get_aweme_media(aweme_item=aweme_item)

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
        account_id: str = "",
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        if config.SAVE_LOGIN_STATE:
            # Use account-specific user_data_dir for multi-account isolation
            dir_name = f"{config.PLATFORM}_{account_id}" if account_id else config.USER_DATA_DIR % config.PLATFORM  # type: ignore
            user_data_dir = os.path.join(os.getcwd(), "browser_data", dir_name)
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )  # type: ignore
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
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
        使用CDP模式启动浏览器
        """
        try:
            cdp_manager = CDPBrowserManager()
            browser_context = await cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Add anti-detection script
            await cdp_manager.add_stealth_script()

            # Show browser information
            browser_info = await cdp_manager.get_browser_info()
            utils.logger.info(f"[DouYinCrawler] CDP浏览器信息: {browser_info}")

            # Store cdp_manager on the session for cleanup
            for s in self.account_manager.sessions:
                if s.account_id == account_id:
                    s.cdp_manager = cdp_manager
                    break

            return browser_context

        except Exception as e:
            utils.logger.error(f"[DouYinCrawler] CDP模式启动失败，回退到标准模式: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless, account_id)

    async def close(self) -> None:
        """Close all browser contexts"""
        await self.account_manager.close_all()
        utils.logger.info("[DouYinCrawler.close] All browser contexts closed ...")

    async def get_aweme_media(self, aweme_item: Dict, client: Optional[DouYinClient] = None):
        """
        获取抖音媒体，自动判断媒体类型是短视频还是帖子图片并下载

        Args:
            aweme_item (Dict): 抖音作品详情
            client (Optional[DouYinClient]): DouYin client instance
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[DouYinCrawler.get_aweme_media] Crawling image mode is not enabled")
            return
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)
        # The video URL will always exist, but when it is a short video type, the file is actually an audio file.
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)
        # TODO: Douyin does not adopt the audio and video separation strategy, so the audio can be separated from the original video and will not be extracted for the time being.
        if note_download_url:
            await self.get_aweme_images(aweme_item, client=client)
        else:
            await self.get_aweme_video(aweme_item, client=client)

    async def get_aweme_images(self, aweme_item: Dict, client: Optional[DouYinClient] = None):
        """
        get aweme images. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
            client (Optional[DouYinClient]): DouYin client instance
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)

        if not note_download_url:
            return
        picNum = 0
        for url in note_download_url:
            if not url:
                continue
            content = await _client.get_aweme_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum:>03d}.jpeg"
            picNum += 1
            await douyin_store.update_dy_aweme_image(aweme_id, content, extension_file_name)

    async def get_aweme_video(self, aweme_item: Dict, client: Optional[DouYinClient] = None):
        """
        get aweme videos. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
            client (Optional[DouYinClient]): DouYin client instance
        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")

        # The video URL will always exist, but when it is a short video type, the file is actually an audio file.
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)

        if not video_download_url:
            return
        content = await _client.get_aweme_media(video_download_url)
        await asyncio.sleep(random.random())
        if content is None:
            return
        extension_file_name = f"video.mp4"
        await douyin_store.update_dy_aweme_video(aweme_id, content, extension_file_name)
