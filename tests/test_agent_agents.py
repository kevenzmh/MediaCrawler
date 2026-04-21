# -*- coding: utf-8 -*-
"""Unit tests for ContentAgent and CommentAgent."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from agent.content_agent import ContentAgent
from agent.comment_agent import CommentAgent
from agent.base_agent import ContentAnalysis, CommentAnalysis


class TestContentAgent:
    def test_not_configured_returns_error(self):
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = ""
        agent._model = ""

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze({"title": "test", "desc": "test desc"})
        )
        assert not result.success
        assert "not configured" in result.error

    def test_parse_response_valid_json(self):
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        valid_json = json.dumps({
            "title_score": 8.5,
            "title_analysis": "Good hook with numbers",
            "content_structure": "Intro -> Main points -> CTA",
            "key_points": ["point 1", "point 2"],
            "engagement_hooks": ["hook 1"],
            "suggested_tags": ["python", "coding"],
            "content_type": "tutorial",
            "sentiment": "positive",
        })
        result = agent._parse_response(valid_json)
        assert result.success
        assert result.title_score == 8.5
        assert result.title_analysis == "Good hook with numbers"
        assert result.content_structure == "Intro -> Main points -> CTA"
        assert result.key_points == ["point 1", "point 2"]
        assert result.engagement_hooks == ["hook 1"]
        assert result.suggested_tags == ["python", "coding"]
        assert result.content_type == "tutorial"
        assert result.sentiment == "positive"

    def test_parse_response_with_markdown_code_block(self):
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        response = "```json\n" + json.dumps({
            "title_score": 7.0,
            "title_analysis": "Decent",
            "content_structure": "Simple",
            "key_points": ["one"],
            "engagement_hooks": [],
            "suggested_tags": [],
            "content_type": "review",
            "sentiment": "neutral",
        }) + "\n```"
        result = agent._parse_response(response)
        assert result.success
        assert result.title_score == 7.0

    def test_parse_response_invalid_json(self):
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        result = agent._parse_response("not valid json at all")
        assert not result.success
        assert "Parse error" in result.error

    def test_parse_response_missing_fields(self):
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        sparse_json = json.dumps({"title_score": 5.0})
        result = agent._parse_response(sparse_json)
        assert result.success
        assert result.title_score == 5.0
        assert result.title_analysis == ""
        assert result.key_points == []

    def test_content_extraction(self):
        """Test that ContentAgent correctly extracts fields from various content formats."""
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        # Mock _call_llm to return valid JSON
        valid_response = json.dumps({
            "title_score": 9.0,
            "title_analysis": "Excellent",
            "content_structure": "Structured",
            "key_points": ["key"],
            "engagement_hooks": ["hook"],
            "suggested_tags": ["tag"],
            "content_type": "video",
            "sentiment": "positive",
        })

        import asyncio

        async def mock_call(*args, **kwargs):
            return valid_response

        agent._call_llm = mock_call

        # Test with xhs-style note data
        xhs_content = {
            "title": "Test Note",
            "desc": "Description here",
            "tags": ["tag1", "tag2"],
            "type": "normal",
            "liked_count": 100,
            "collected_count": 50,
            "comment_count": 20,
            "share_count": 10,
        }
        result = asyncio.get_event_loop().run_until_complete(agent.analyze(xhs_content))
        assert result.success
        assert result.title_score == 9.0

    def test_analyze_exception_handling(self):
        """Test that exceptions during API call are caught properly."""
        agent = ContentAgent.__new__(ContentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        async def mock_call(*args, **kwargs):
            raise ConnectionError("Network error")

        agent._call_llm = mock_call

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze({"title": "test", "desc": "desc"})
        )
        assert not result.success
        assert "Network error" in result.error


class TestCommentAgent:
    def test_not_configured_returns_error(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = ""
        agent._model = ""

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze([{"content": "test"}])
        )
        assert not result.success
        assert "not configured" in result.error

    def test_empty_comments_returns_no_comment(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(agent.analyze([]))
        assert result.success
        assert "无评论" in result.key_themes
        assert result.sentiment_distribution == {"positive": 0, "neutral": 0, "negative": 0}

    def test_extract_comment_text(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        assert agent._extract_comment_text({"content": "hello"}) == "hello"
        assert agent._extract_comment_text({"text": "world"}) == "world"
        assert agent._extract_comment_text({"comment_text": "test"}) == "test"
        assert agent._extract_comment_text({}) != ""  # Falls back to str({})

    def test_parse_response_valid_json(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        valid_json = json.dumps({
            "sentiment_distribution": {"positive": 0.7, "neutral": 0.2, "negative": 0.1},
            "key_themes": ["price", "quality"],
            "user_intents": ["purchase", "inquiry"],
            "engagement_insights": "Users are very engaged",
            "top_comments_summary": "Top comments praise quality",
            "suggestions": "Consider adding discount",
        })
        result = agent._parse_response(valid_json)
        assert result.success
        assert result.sentiment_distribution["positive"] == 0.7
        assert result.key_themes == ["price", "quality"]
        assert result.user_intents == ["purchase", "inquiry"]
        assert result.engagement_insights == "Users are very engaged"
        assert result.top_comments_summary == "Top comments praise quality"
        assert result.suggestions == "Consider adding discount"

    def test_parse_response_with_code_block(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        response = "```json\n" + json.dumps({
            "sentiment_distribution": {"positive": 0.5, "neutral": 0.3, "negative": 0.2},
            "key_themes": ["test"],
            "user_intents": [],
            "engagement_insights": "Insight",
            "top_comments_summary": "Summary",
            "suggestions": "Suggestion",
        }) + "\n```"
        result = agent._parse_response(response)
        assert result.success
        assert result.sentiment_distribution["positive"] == 0.5

    def test_parse_response_invalid_json(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        result = agent._parse_response("not json")
        assert not result.success
        assert "Parse error" in result.error

    def test_analyze_with_content_context(self):
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        valid_response = json.dumps({
            "sentiment_distribution": {"positive": 0.8, "neutral": 0.1, "negative": 0.1},
            "key_themes": ["theme"],
            "user_intents": ["intent"],
            "engagement_insights": "Great engagement",
            "top_comments_summary": "Positive reception",
            "suggestions": "Keep it up",
        })

        async def mock_call(*args, **kwargs):
            return valid_response

        agent._call_llm = mock_call

        import asyncio
        comments = [{"content": "Great post!"}, {"content": "Very helpful"}]
        context = {"title": "My Post", "type": "normal", "liked_count": 50}
        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze(comments, context)
        )
        assert result.success
        assert result.sentiment_distribution["positive"] == 0.8

    def test_comment_limit(self):
        """Test that comments are limited to max_comments (50)."""
        agent = CommentAgent.__new__(CommentAgent)
        agent._api_key = "sk-test"
        agent._model = ""

        captured_message = []

        async def mock_call(system, user_message):
            captured_message.append(user_message)
            return json.dumps({
                "sentiment_distribution": {"positive": 1.0, "neutral": 0, "negative": 0},
                "key_themes": [],
                "user_intents": [],
                "engagement_insights": "",
                "top_comments_summary": "",
                "suggestions": "",
            })

        agent._call_llm = mock_call

        import asyncio
        # Create 60 comments
        comments = [{"content": f"Comment {i}"} for i in range(60)]
        asyncio.get_event_loop().run_until_complete(agent.analyze(comments))

        # The user_message should only contain up to 50 comments
        assert "51." not in captured_message[0]
        assert "50." in captured_message[0]
