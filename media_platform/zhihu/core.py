# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zhihu/core.py
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


# -*- coding: utf-8 -*-
import asyncio
import os
from asyncio import Task
from typing import Dict, List, Optional, cast

import config
from account import AccountManager, AccountSession
from constant import zhihu as constant
from base.base_crawler import AbstractCrawler
from model.m_zhihu import ZhihuContent, ZhihuCreator
from store import zhihu as zhihu_store
from tools import utils
from tools.checkpoint import CheckpointManager
from var import crawler_type_var, source_keyword_var

from .client import ZhiHuClient
from .exception import DataFetchError
from .help import ZhihuExtractor, judge_zhihu_url
from .login import ZhiHuLogin


class ZhihuCrawler(AbstractCrawler):

    def __init__(self) -> None:
        self.index_url = "https://www.zhihu.com"
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        self._extractor = ZhihuExtractor()
        self.account_manager = AccountManager()

    async def start(self) -> None:
        """Start the crawler"""
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
        utils.logger.info("[ZhihuCrawler.start] Zhihu Crawler finished ...")

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
                login_obj_factory=lambda s: ZhiHuLogin(
                    login_type=s.login_type,
                    login_phone="",
                    browser_context=s.browser_context,
                    context_page=s.context_page,
                    cookie_str=s.cookie_str,
                ),
                index_url=self.index_url,
                stealth_js_path="libs/stealth.min.js",
                post_login_hook=self._zhihu_search_page_hook,
            )
        return cookie_str, cookie_dict

    async def _zhihu_search_page_hook(self, session):
        """Navigate to search page after login to obtain search-specific cookies."""
        utils.logger.info(
            "[ZhihuCrawler._zhihu_search_page_hook] Navigating to search page to get search page cookies, this process takes about 5 seconds"
        )
        await session.context_page.goto(
            f"{self.index_url}/search?q=python&search_source=Guess&utm_content=search_hot&type=content"
        )
        await asyncio.sleep(5)

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
                f"[ZhihuCrawler._crawl_with_session] Account '{session.account_id}' error: {ex}"
            )

    def _create_client_from_cookies(self, session: AccountSession, cookie_str: str, cookie_dict: Dict) -> ZhiHuClient:
        """Create zhihu client from cookie string and dict (no browser required)."""
        utils.logger.info(
            f"[ZhihuCrawler._create_client_from_cookies] Creating client for account '{session.account_id}'"
        )
        zhihu_client_obj = ZhiHuClient(
            proxy=session.httpx_proxy,
            headers={
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cookie": cookie_str,
                "priority": "u=1, i",
                "referer": "https://www.zhihu.com/search?q=python&time_interval=a_year&type=content",
                "user-agent": self.user_agent,
                "x-api-version": "3.0.91",
                "x-app-za": "OS=Web",
                "x-requested-with": "fetch",
                "x-zse-93": "101_3_3.0",
            },
            cookie_dict=cookie_dict,
            proxy_ip_pool=session.proxy_ip_pool,
        )
        return zhihu_client_obj

    async def search(self, session: Optional[AccountSession] = None) -> None:
        """Search for notes and retrieve their comment information."""
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(f"[ZhihuCrawler.search] Begin search zhihu keywords (account: {session.account_id if session else 'default'})")
        zhihu_limit_count = 20  # zhihu limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < zhihu_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = zhihu_limit_count
        start_page = config.START_PAGE
        checkpoint = CheckpointManager(platform=config.PLATFORM, crawler_type=config.CRAWLER_TYPE)
        if checkpoint.has_checkpoint():
            checkpoint.load_checkpoint()
            utils.logger.info("[ZhihuCrawler.search] 发现断点续爬记录，从上次进度恢复")
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            # 从 checkpoint 恢复该关键词的进度
            keyword_progress = checkpoint.get_keyword_progress(keyword)
            if keyword_progress and keyword_progress.get("completed"):
                utils.logger.info(f"[ZhihuCrawler.search] 关键词 '{keyword}' 已完成，跳过")
                continue
            page = keyword_progress.get("page", start_page) if keyword_progress else start_page
            utils.logger.info(
                f"[ZhihuCrawler.search] Current search keyword: {keyword}, start page: {page}"
            )
            while (
                page - start_page + 1
            ) * zhihu_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[ZhihuCrawler.search] Skip page {page}")
                    page += 1
                    continue

                try:
                    utils.logger.info(
                        f"[ZhihuCrawler.search] search zhihu keyword: {keyword}, page: {page}"
                    )
                    content_list: List[ZhihuContent] = (
                        await client.get_note_by_keyword(
                            keyword=keyword,
                            page=page,
                        )
                    )
                    utils.logger.info(
                        f"[ZhihuCrawler.search] Search contents :{content_list}"
                    )
                    if not content_list:
                        utils.logger.info("No more content!")
                        break

                    # Sleep after page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[ZhihuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                    page += 1
                    for content in content_list:
                        await zhihu_store.update_zhihu_content(content)

                    # 每页成功后保存 checkpoint
                    checkpoint.save_checkpoint(keyword=keyword, page=page)

                    await self.batch_get_content_comments(content_list, client)
                except DataFetchError:
                    utils.logger.error("[ZhihuCrawler.search] Search content error")
                    return

            # 关键词爬完，标记 completed
            checkpoint.mark_keyword_completed(keyword)

        # 全部完成，清理 checkpoint
        checkpoint.clear_checkpoint()

    async def batch_get_content_comments(self, content_list: List[ZhihuContent], client: Optional[ZhiHuClient] = None):
        """
        Batch get content comments
        Args:
            content_list:
            client:

        Returns:

        """
        _client = client or self.account_manager.sessions[0].api_client
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(
                f"[ZhihuCrawler.batch_get_content_comments] Crawling comment mode is not enabled"
            )
            return

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for content_item in content_list:
            task = asyncio.create_task(
                self.get_comments(content_item, semaphore, _client), name=content_item.content_id
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(
        self, content_item: ZhihuContent, semaphore: asyncio.Semaphore, client: Optional[ZhiHuClient] = None
    ):
        """
        Get note comments with keyword filtering and quantity limitation
        Args:
            content_item:
            semaphore:
            client:

        Returns:

        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            utils.logger.info(
                f"[ZhihuCrawler.get_comments] Begin get note id comments {content_item.content_id}"
            )

            # Sleep before fetching comments
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            utils.logger.info(f"[ZhihuCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for content {content_item.content_id}")

            await _client.get_note_all_comments(
                content=content_item,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=zhihu_store.batch_update_zhihu_note_comments,
            )

    async def get_creators_and_notes(self, session: Optional[AccountSession] = None) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        utils.logger.info(
            "[ZhihuCrawler.get_creators_and_notes] Begin get zhihu creators"
        )
        for user_link in config.ZHIHU_CREATOR_URL_LIST:
            utils.logger.info(
                f"[ZhihuCrawler.get_creators_and_notes] Begin get creator {user_link}"
            )
            user_url_token = user_link.split("/")[-1]
            # get creator detail info from web html content
            createor_info: ZhihuCreator = await client.get_creator_info(
                url_token=user_url_token
            )
            if not createor_info:
                utils.logger.info(
                    f"[ZhihuCrawler.get_creators_and_notes] Creator {user_url_token} not found"
                )
                continue

            utils.logger.info(
                f"[ZhihuCrawler.get_creators_and_notes] Creator info: {createor_info}"
            )
            await zhihu_store.save_creator(creator=createor_info)

            # By default, only answer information is extracted, uncomment below if articles and videos are needed

            # Get all anwser information of the creator
            all_content_list = await client.get_all_anwser_by_creator(
                creator=createor_info,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=zhihu_store.batch_update_zhihu_contents,
            )

            # Get all articles of the creator's contents
            # all_content_list = await client.get_all_articles_by_creator(
            #     creator=createor_info,
            #     crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
            #     callback=zhihu_store.batch_update_zhihu_contents
            # )

            # Get all videos of the creator's contents
            # all_content_list = await client.get_all_videos_by_creator(
            #     creator=createor_info,
            #     crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
            #     callback=zhihu_store.batch_update_zhihu_contents
            # )

            # Get all comments of the creator's contents
            await self.batch_get_content_comments(all_content_list, client)

    async def get_note_detail(
        self, full_note_url: str, semaphore: asyncio.Semaphore, client: Optional[ZhiHuClient] = None
    ) -> Optional[ZhihuContent]:
        """
        Get note detail
        Args:
            full_note_url: str
            semaphore:
            client:

        Returns:

        """
        _client = client or self.account_manager.sessions[0].api_client
        async with semaphore:
            utils.logger.info(
                f"[ZhihuCrawler.get_specified_notes] Begin get specified note {full_note_url}"
            )
            # Judge note type
            note_type: str = judge_zhihu_url(full_note_url)
            if note_type == constant.ANSWER_NAME:
                question_id = full_note_url.split("/")[-3]
                answer_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get answer info, question_id: {question_id}, answer_id: {answer_id}"
                )
                result = await _client.get_answer_info(question_id, answer_id)

                # Sleep after fetching answer details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching answer details {answer_id}")

                return result

            elif note_type == constant.ARTICLE_NAME:
                article_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get article info, article_id: {article_id}"
                )
                result = await _client.get_article_info(article_id)

                # Sleep after fetching article details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching article details {article_id}")

                return result

            elif note_type == constant.VIDEO_NAME:
                video_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get video info, video_id: {video_id}"
                )
                result = await _client.get_video_info(video_id)

                # Sleep after fetching video details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {video_id}")

                return result

    async def get_specified_notes(self, session: Optional[AccountSession] = None):
        """
        Get the information and comments of the specified post
        Returns:

        """
        client = session.api_client if session else self.account_manager.sessions[0].api_client
        get_note_detail_task_list = []
        for full_note_url in config.ZHIHU_SPECIFIED_ID_LIST:
            # remove query params
            full_note_url = full_note_url.split("?")[0]
            crawler_task = self.get_note_detail(
                full_note_url=full_note_url,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
                client=client,
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_notes: List[ZhihuContent] = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for index, note_detail in enumerate(note_details):
            if not note_detail:
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Note {config.ZHIHU_SPECIFIED_ID_LIST[index]} not found"
                )
                continue

            note_detail = cast(ZhihuContent, note_detail)  # only for type check
            need_get_comment_notes.append(note_detail)
            await zhihu_store.update_zhihu_content(note_detail)

        await self.batch_get_content_comments(need_get_comment_notes, client)

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
        """Close all browser contexts"""
        await self.account_manager.close_all()
        utils.logger.info("[ZhihuCrawler.close] All browser contexts closed ...")
