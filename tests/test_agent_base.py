# -*- coding: utf-8 -*-
"""Unit tests for AI Agent infrastructure."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from agent.base_agent import AgentResult, ContentAnalysis, CommentAnalysis, BaseAgent


class TestAgentResult:
    def test_default_success(self):
        result = AgentResult()
        assert result.success is True
        assert result.error == ""
        assert result.raw_response == ""

    def test_error_state(self):
        result = AgentResult(success=False, error="API timeout")
        assert result.success is False
        assert result.error == "API timeout"


class TestContentAnalysis:
    def test_default_values(self):
        analysis = ContentAnalysis()
        assert analysis.success is True
        assert analysis.title_score == 0.0
        assert analysis.title_analysis == ""
        assert analysis.content_structure == ""
        assert analysis.key_points == []
        assert analysis.engagement_hooks == []
        assert analysis.suggested_tags == []
        assert analysis.content_type == ""
        assert analysis.sentiment == ""

    def test_to_dict(self):
        analysis = ContentAnalysis(
            title_score=8.5,
            title_analysis="Strong hook",
            content_structure="Intro-Body-CTA",
            key_points=["point1", "point2"],
            engagement_hooks=["hook1"],
            suggested_tags=["tag1", "tag2"],
            content_type="tutorial",
            sentiment="positive",
        )
        d = analysis.to_dict()
        assert d["title_score"] == 8.5
        assert d["title_analysis"] == "Strong hook"
        assert d["content_structure"] == "Intro-Body-CTA"
        assert d["key_points"] == ["point1", "point2"]
        assert d["engagement_hooks"] == ["hook1"]
        assert d["suggested_tags"] == ["tag1", "tag2"]
        assert d["content_type"] == "tutorial"
        assert d["sentiment"] == "positive"
        assert len(d) == 8

    def test_error_result(self):
        analysis = ContentAnalysis(success=False, error="Parse error")
        assert not analysis.success
        assert analysis.error == "Parse error"
        d = analysis.to_dict()
        assert d["title_score"] == 0.0


class TestCommentAnalysis:
    def test_default_values(self):
        analysis = CommentAnalysis()
        assert analysis.success is True
        assert analysis.sentiment_distribution == {}
        assert analysis.key_themes == []
        assert analysis.user_intents == []
        assert analysis.engagement_insights == ""
        assert analysis.top_comments_summary == ""
        assert analysis.suggestions == ""

    def test_to_dict(self):
        analysis = CommentAnalysis(
            sentiment_distribution={"positive": 0.6, "neutral": 0.3, "negative": 0.1},
            key_themes=["theme1", "theme2"],
            user_intents=["intent1"],
            engagement_insights="High engagement on pricing topic",
            top_comments_summary="Users love the feature",
            suggestions="Add more tutorials",
        )
        d = analysis.to_dict()
        assert d["sentiment_distribution"]["positive"] == 0.6
        assert d["key_themes"] == ["theme1", "theme2"]
        assert d["user_intents"] == ["intent1"]
        assert d["engagement_insights"] == "High engagement on pricing topic"
        assert d["top_comments_summary"] == "Users love the feature"
        assert d["suggestions"] == "Add more tutorials"
        assert len(d) == 6

    def test_error_result(self):
        analysis = CommentAnalysis(success=False, error="API error")
        assert not analysis.success


class TestBaseAgent:
    def test_is_configured_with_key(self):
        agent = BaseAgent.__new__(BaseAgent)
        agent._api_key = "sk-test-key"
        agent._model = "claude-sonnet-4-5-20250514"
        assert agent.is_configured is True

    def test_is_configured_without_key(self):
        agent = BaseAgent.__new__(BaseAgent)
        agent._api_key = ""
        agent._model = ""
        assert agent.is_configured is False

    @patch('config.CLAUDE_API_KEY', 'sk-from-config')
    @patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514')
    def test_uses_config_defaults(self):
        agent = BaseAgent.__new__(BaseAgent)
        import config
        agent._api_key = config.CLAUDE_API_KEY
        agent._model = config.CLAUDE_MODEL
        assert agent._api_key == "sk-from-config"
        assert agent._model == "claude-sonnet-4-5-20250514"

    def test_explicit_key_overrides_config(self):
        agent = BaseAgent.__new__(BaseAgent)
        agent._api_key = "sk-explicit"
        agent._model = "claude-opus-4-7"
        assert agent._api_key == "sk-explicit"
        assert agent._model == "claude-opus-4-7"

    def test_create_client(self):
        with patch('anthropic.Anthropic') as mock_client:
            agent = BaseAgent.__new__(BaseAgent)
            agent._api_key = "sk-test"
            agent._model = "claude-sonnet-4-5-20250514"
            agent._create_client()
            mock_client.assert_called_once_with(api_key="sk-test")
