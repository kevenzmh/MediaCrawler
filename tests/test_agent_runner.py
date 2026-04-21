# -*- coding: utf-8 -*-
"""Unit tests for Agent runner - singleton pattern and config gating."""

import json
import pytest
from unittest.mock import patch, AsyncMock

# Reset singletons before each test
@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset agent singletons before each test."""
    import agent.runner as runner
    runner._content_agent = None
    runner._comment_agent = None
    yield
    runner._content_agent = None
    runner._comment_agent = None


class TestContentAgentGetter:
    def test_returns_none_when_disabled(self):
        with patch('config.ENABLE_CONTENT_AGENT', False):
            from agent.runner import _get_content_agent
            result = _get_content_agent()
            assert result is None

    def test_returns_agent_when_enabled_and_configured(self):
        with patch('config.ENABLE_CONTENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test-key'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'):
            from agent.runner import _get_content_agent
            result = _get_content_agent()
            assert result is not None
            assert result.is_configured

    def test_returns_none_when_enabled_but_no_key(self):
        with patch('config.ENABLE_CONTENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', ''):
            from agent.runner import _get_content_agent
            result = _get_content_agent()
            assert result is None

    def test_singleton_returns_same_instance(self):
        with patch('config.ENABLE_CONTENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test-key'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'):
            from agent.runner import _get_content_agent
            agent1 = _get_content_agent()
            agent2 = _get_content_agent()
            assert agent1 is agent2


class TestCommentAgentGetter:
    def test_returns_none_when_disabled(self):
        with patch('config.ENABLE_COMMENT_AGENT', False):
            from agent.runner import _get_comment_agent
            result = _get_comment_agent()
            assert result is None

    def test_returns_agent_when_enabled_and_configured(self):
        with patch('config.ENABLE_COMMENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test-key'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'):
            from agent.runner import _get_comment_agent
            result = _get_comment_agent()
            assert result is not None

    def test_singleton_returns_same_instance(self):
        with patch('config.ENABLE_COMMENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test-key'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'):
            from agent.runner import _get_comment_agent
            agent1 = _get_comment_agent()
            agent2 = _get_comment_agent()
            assert agent1 is agent2


class TestAnalyzeContentRunner:
    def test_returns_none_when_disabled(self):
        import asyncio
        with patch('config.ENABLE_CONTENT_AGENT', False):
            from agent.runner import analyze_content
            result = asyncio.get_event_loop().run_until_complete(
                analyze_content({"title": "test"})
            )
            assert result is None

    def test_returns_analysis_when_enabled(self):
        import asyncio
        valid_response = json.dumps({
            "title_score": 8.0,
            "title_analysis": "Good",
            "content_structure": "Simple",
            "key_points": ["point"],
            "engagement_hooks": ["hook"],
            "suggested_tags": ["tag"],
            "content_type": "tutorial",
            "sentiment": "positive",
        })

        with patch('config.ENABLE_CONTENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'), \
             patch('agent.content_agent.ContentAgent._call_llm', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = valid_response

            from agent.runner import analyze_content
            result = asyncio.get_event_loop().run_until_complete(
                analyze_content({"title": "Test", "desc": "Description", "tags": []})
            )
            assert result is not None
            assert result["title_score"] == 8.0
            assert result["content_type"] == "tutorial"


class TestAnalyzeCommentsRunner:
    def test_returns_none_when_disabled(self):
        import asyncio
        with patch('config.ENABLE_COMMENT_AGENT', False):
            from agent.runner import analyze_comments
            result = asyncio.get_event_loop().run_until_complete(
                analyze_comments([{"content": "test"}])
            )
            assert result is None

    def test_returns_analysis_when_enabled(self):
        import asyncio
        valid_response = json.dumps({
            "sentiment_distribution": {"positive": 0.6, "neutral": 0.3, "negative": 0.1},
            "key_themes": ["theme"],
            "user_intents": ["intent"],
            "engagement_insights": "Good engagement",
            "top_comments_summary": "Summary",
            "suggestions": "Improve",
        })

        with patch('config.ENABLE_COMMENT_AGENT', True), \
             patch('config.CLAUDE_API_KEY', 'sk-test'), \
             patch('config.CLAUDE_MODEL', 'claude-sonnet-4-5-20250514'), \
             patch('agent.comment_agent.CommentAgent._call_llm', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = valid_response

            from agent.runner import analyze_comments
            result = asyncio.get_event_loop().run_until_complete(
                analyze_comments(
                    [{"content": "Great!"}, {"content": "Nice post"}],
                    {"title": "My Post"}
                )
            )
            assert result is not None
            assert result["sentiment_distribution"]["positive"] == 0.6
            assert result["key_themes"] == ["theme"]
