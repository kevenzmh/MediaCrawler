# -*- coding: utf-8 -*-
"""Unit tests for API schemas - Agent request/response models."""

import pytest
from api.schemas.crawler import (
    PlatformEnum,
    LoginTypeEnum,
    CrawlerTypeEnum,
    SaveDataOptionEnum,
    CrawlerStartRequest,
    AgentContentRequest,
    AgentCommentsRequest,
    AgentAnalysisResponse,
    CrawlerStatusResponse,
    LogEntry,
    DataFileInfo,
)


class TestPlatformEnum:
    def test_all_platforms(self):
        assert PlatformEnum.XHS.value == "xhs"
        assert PlatformEnum.DOUYIN.value == "dy"
        assert PlatformEnum.KUAISHOU.value == "ks"
        assert PlatformEnum.BILIBILI.value == "bili"
        assert PlatformEnum.WEIBO.value == "wb"
        assert PlatformEnum.TIEBA.value == "tieba"
        assert PlatformEnum.ZHIHU.value == "zhihu"


class TestCrawlerTypeEnum:
    def test_feed_included(self):
        """Test that FEED type is included in CrawlerTypeEnum."""
        assert hasattr(CrawlerTypeEnum, 'FEED')
        assert CrawlerTypeEnum.FEED.value == "feed"

    def test_all_types(self):
        assert CrawlerTypeEnum.SEARCH.value == "search"
        assert CrawlerTypeEnum.DETAIL.value == "detail"
        assert CrawlerTypeEnum.CREATOR.value == "creator"
        assert CrawlerTypeEnum.FEED.value == "feed"


class TestSaveDataOptionEnum:
    def test_all_options(self):
        assert SaveDataOptionEnum.CSV.value == "csv"
        assert SaveDataOptionEnum.DB.value == "db"
        assert SaveDataOptionEnum.JSON.value == "json"
        assert SaveDataOptionEnum.JSONL.value == "jsonl"
        assert SaveDataOptionEnum.SQLITE.value == "sqlite"
        assert SaveDataOptionEnum.MONGODB.value == "mongodb"
        assert SaveDataOptionEnum.EXCEL.value == "excel"


class TestCrawlerStartRequest:
    def test_defaults(self):
        request = CrawlerStartRequest(platform=PlatformEnum.XHS)
        assert request.platform == PlatformEnum.XHS
        assert request.login_type == LoginTypeEnum.QRCODE
        assert request.crawler_type == CrawlerTypeEnum.SEARCH
        assert request.keywords == ""
        assert request.start_page == 1
        assert request.enable_comments is True
        assert request.save_option == SaveDataOptionEnum.JSONL
        assert request.headless is False
        assert request.feed_category == "recommend"
        assert request.enable_content_agent is False
        assert request.enable_comment_agent is False

    def test_feed_request(self):
        request = CrawlerStartRequest(
            platform=PlatformEnum.XHS,
            crawler_type=CrawlerTypeEnum.FEED,
            feed_category="recommend",
        )
        assert request.crawler_type == CrawlerTypeEnum.FEED
        assert request.feed_category == "recommend"

    def test_agent_enabled(self):
        request = CrawlerStartRequest(
            platform=PlatformEnum.DOUYIN,
            enable_content_agent=True,
            enable_comment_agent=True,
        )
        assert request.enable_content_agent is True
        assert request.enable_comment_agent is True

    def test_json_serialization(self):
        request = CrawlerStartRequest(
            platform=PlatformEnum.XHS,
            keywords="Python",
            crawler_type=CrawlerTypeEnum.SEARCH,
        )
        data = request.model_dump()
        assert data["platform"] == "xhs"
        assert data["keywords"] == "Python"
        assert data["crawler_type"] == "search"


class TestAgentContentRequest:
    def test_defaults(self):
        request = AgentContentRequest(
            platform=PlatformEnum.XHS,
            content_id="note_123",
        )
        assert request.platform == PlatformEnum.XHS
        assert request.content_id == "note_123"
        assert request.title == ""
        assert request.desc == ""
        assert request.tags == []
        assert request.liked_count == 0

    def test_full_request(self):
        request = AgentContentRequest(
            platform=PlatformEnum.XHS,
            content_id="note_456",
            title="Test Title",
            desc="Test description",
            tags=["python", "coding"],
            content_type="normal",
            liked_count=100,
            collected_count=50,
            comment_count=20,
            share_count=10,
        )
        assert request.title == "Test Title"
        assert request.tags == ["python", "coding"]
        assert request.liked_count == 100

    def test_json_serialization(self):
        request = AgentContentRequest(
            platform=PlatformEnum.DOUYIN,
            content_id="video_789",
            title="My Video",
            tags=["viral"],
        )
        data = request.model_dump()
        assert data["platform"] == "dy"
        assert data["content_id"] == "video_789"
        assert data["tags"] == ["viral"]


class TestAgentCommentsRequest:
    def test_defaults(self):
        request = AgentCommentsRequest(
            platform=PlatformEnum.XHS,
            content_id="note_123",
            comments=[],
        )
        assert request.platform == PlatformEnum.XHS
        assert request.content_id == "note_123"
        assert request.comments == []
        assert request.content_title == ""

    def test_with_comments(self):
        comments = [
            {"content": "Great!", "user_id": "u1"},
            {"content": "Thanks", "user_id": "u2"},
        ]
        request = AgentCommentsRequest(
            platform=PlatformEnum.XHS,
            content_id="note_123",
            comments=comments,
            content_title="My Post",
            content_type="normal",
        )
        assert len(request.comments) == 2
        assert request.content_title == "My Post"


class TestAgentAnalysisResponse:
    def test_success_response(self):
        response = AgentAnalysisResponse(
            success=True,
            analysis={"title_score": 8.5, "sentiment": "positive"},
        )
        assert response.success is True
        assert response.analysis["title_score"] == 8.5
        assert response.error is None

    def test_error_response(self):
        response = AgentAnalysisResponse(
            success=False,
            error="API key not configured",
        )
        assert response.success is False
        assert response.error == "API key not configured"
        assert response.analysis is None

    def test_json_serialization(self):
        response = AgentAnalysisResponse(
            success=True,
            analysis={"key_themes": ["theme1"]},
        )
        data = response.model_dump()
        assert data["success"] is True
        assert data["analysis"]["key_themes"] == ["theme1"]


class TestCrawlerStatusResponse:
    def test_idle_status(self):
        response = CrawlerStatusResponse(status="idle")
        assert response.status == "idle"
        assert response.platform is None

    def test_running_status(self):
        response = CrawlerStatusResponse(
            status="running",
            platform="xhs",
            crawler_type="search",
            started_at="2025-01-01T00:00:00",
        )
        assert response.status == "running"
        assert response.platform == "xhs"

    def test_error_status(self):
        response = CrawlerStatusResponse(
            status="error",
            error_message="Connection timeout",
        )
        assert response.status == "error"
        assert response.error_message == "Connection timeout"

    def test_invalid_status_raises(self):
        with pytest.raises(Exception):
            CrawlerStatusResponse(status="unknown")


class TestLogEntry:
    def test_valid_entry(self):
        entry = LogEntry(
            id=1,
            timestamp="2025-01-01T00:00:00",
            level="info",
            message="Crawler started",
        )
        assert entry.id == 1
        assert entry.level == "info"
        assert entry.message == "Crawler started"

    def test_all_levels(self):
        for level in ["info", "warning", "error", "success", "debug"]:
            entry = LogEntry(id=1, timestamp="", level=level, message="test")
            assert entry.level == level

    def test_invalid_level_raises(self):
        with pytest.raises(Exception):
            LogEntry(id=1, timestamp="", level="critical", message="test")


class TestDataFileInfo:
    def test_basic_info(self):
        info = DataFileInfo(
            name="xhs_notes.jsonl",
            path="/data/xhs/xhs_notes.jsonl",
            size=1024,
            modified_at="2025-01-01T00:00:00",
        )
        assert info.name == "xhs_notes.jsonl"
        assert info.size == 1024
        assert info.record_count is None

    def test_with_record_count(self):
        info = DataFileInfo(
            name="notes.jsonl",
            path="/data/notes.jsonl",
            size=2048,
            modified_at="2025-01-01T00:00:00",
            record_count=100,
        )
        assert info.record_count == 100
