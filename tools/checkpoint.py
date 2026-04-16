# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/checkpoint.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1

import json
import os
from datetime import datetime
from typing import Optional, Dict

import config
from tools.utils import utils

CHECKPOINT_DIR = "data/.checkpoint"


class CheckpointManager:
    """断点续爬检查点管理器

    将爬取进度保存为 JSON 文件，支持中断后恢复。
    存储路径: data/.checkpoint/{platform}_{crawler_type}.json
    """

    def __init__(self, platform: str, crawler_type: str):
        self.platform = platform
        self.crawler_type = crawler_type
        self.file_path = os.path.join(CHECKPOINT_DIR, f"{platform}_{crawler_type}.json")
        self._cache: Optional[Dict] = None

    def _ensure_dir(self):
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    def has_checkpoint(self) -> bool:
        """是否存在未完成的检查点"""
        if not config.ENABLE_CHECKPOINT:
            return False
        if not os.path.exists(self.file_path):
            return False
        data = self._load_file()
        if data is None:
            return False
        # 检查是否所有关键词都已完成（全部完成则视为无检查点）
        keyword_progress = data.get("keyword_progress", {})
        all_completed = all(
            v.get("completed", False) for v in keyword_progress.values()
        )
        return not all_completed

    def _load_file(self) -> Optional[Dict]:
        """从文件加载检查点数据"""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            utils.logger.warning(f"[CheckpointManager] 加载检查点文件失败: {e}")
            return None

    def load_checkpoint(self) -> Optional[Dict]:
        """加载检查点并校验配置一致性

        如果 keywords / crawler_type / max_notes_count 与当前配置不一致，
        则忽略旧检查点并删除文件。
        """
        if not config.ENABLE_CHECKPOINT:
            return None

        data = self._load_file()
        if data is None:
            return None

        # 校验配置一致性
        if data.get("crawler_type") != self.crawler_type:
            utils.logger.warning(
                f"[CheckpointManager] 检查点 crawler_type='{data.get('crawler_type')}' "
                f"与当前 '{self.crawler_type}' 不一致，忽略检查点"
            )
            self.remove_checkpoint()
            return None

        if data.get("keywords") != config.KEYWORDS:
            utils.logger.warning(
                "[CheckpointManager] 检查点 keywords 与当前配置不一致，忽略检查点"
            )
            self.remove_checkpoint()
            return None

        if data.get("max_notes_count") != config.CRAWLER_MAX_NOTES_COUNT:
            utils.logger.warning(
                "[CheckpointManager] 检查点 max_notes_count 与当前配置不一致，忽略检查点"
            )
            self.remove_checkpoint()
            return None

        self._cache = data

        # 打印恢复信息
        keyword_progress = data.get("keyword_progress", {})
        for kw, progress in keyword_progress.items():
            status = "已完成" if progress.get("completed") else f"第 {progress.get('page', 1)} 页"
            utils.logger.info(f"[CheckpointManager] 关键词 '{kw}': {status}")

        return data

    def get_keyword_progress(self, keyword: str) -> Optional[Dict]:
        """获取某个关键词的爬取进度"""
        if self._cache is None:
            data = self._load_file()
            if data is None:
                return None
            self._cache = data
        return self._cache.get("keyword_progress", {}).get(keyword)

    def save_checkpoint(self, keyword: str, page: int, cursor_token: str = "", completed: bool = False):
        """保存检查点

        Args:
            keyword: 当前关键词
            page: 下一次应该开始的页码
            cursor_token: 平台特有的游标 token（如抖音的 search_id、快手的 search_session_id）
            completed: 该关键词是否已完成
        """
        if not config.ENABLE_CHECKPOINT:
            return

        self._ensure_dir()

        # 构建或更新数据
        if self._cache is None:
            self._cache = {
                "platform": self.platform,
                "crawler_type": self.crawler_type,
                "keywords": config.KEYWORDS,
                "max_notes_count": config.CRAWLER_MAX_NOTES_COUNT,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "keyword_progress": {},
            }

        self._cache["updated_at"] = datetime.now().isoformat()

        if "keyword_progress" not in self._cache:
            self._cache["keyword_progress"] = {}

        self._cache["keyword_progress"][keyword] = {
            "page": page,
            "cursor_token": cursor_token,
            "completed": completed,
        }

        self._write_file()

    def mark_keyword_completed(self, keyword: str):
        """标记某个关键词已爬完"""
        self.save_checkpoint(keyword=keyword, page=0, cursor_token="", completed=True)

    def clear_checkpoint(self):
        """清理检查点（全部爬取完成后调用）"""
        self._cache = None
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
            utils.logger.info("[CheckpointManager] 检查点已清理")

    def remove_checkpoint(self):
        """删除检查点文件"""
        self._cache = None
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def _write_file(self):
        """将缓存数据写入文件"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except IOError as e:
            utils.logger.error(f"[CheckpointManager] 写入检查点文件失败: {e}")
