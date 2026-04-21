# -*- coding: utf-8 -*-
"""Comment Analysis Agent - Analyze crawled comments using Claude API."""

import json
from typing import Any, Dict, List, Optional

from tools import utils

from .base_agent import BaseAgent, CommentAnalysis
from .prompts import COMMENT_ANALYSIS_SYSTEM, COMMENT_ANALYSIS_USER


class CommentAgent(BaseAgent):
    """AI agent for comment batch analysis."""

    async def analyze(
        self,
        comments: List[Dict[str, Any]],
        content_context: Optional[Dict[str, Any]] = None,
    ) -> CommentAnalysis:
        """Analyze a batch of comments for a single piece of content.

        Args:
            comments: List of comment dicts, each should have at least 'content' or 'text' key.
            content_context: Optional context about the content being commented on.

        Returns:
            CommentAnalysis with structured analysis results.
        """
        if not self.is_configured:
            utils.logger.warning("[CommentAgent] Claude API key not configured, skipping analysis")
            return CommentAnalysis(success=False, error="API key not configured")

        if not comments:
            return CommentAnalysis(success=True, key_themes=["无评论"], sentiment_distribution={"positive": 0, "neutral": 0, "negative": 0})

        # Format comments for the prompt (limit to avoid token overflow)
        max_comments = 50
        selected_comments = comments[:max_comments]
        comments_text = "\n".join(
            f"{i+1}. {self._extract_comment_text(c)}"
            for i, c in enumerate(selected_comments)
        )

        content_context = content_context or {}
        title = content_context.get("title", "") or content_context.get("name", "")
        note_type = content_context.get("type", "") or content_context.get("note_type", "")
        liked_count = content_context.get("liked_count", 0)
        comment_count = len(comments)

        user_message = COMMENT_ANALYSIS_USER.format(
            count=len(selected_comments),
            comments=comments_text[:4000],
            title=title[:200],
            note_type=note_type,
            liked_count=liked_count,
            comment_count=comment_count,
        )

        try:
            utils.logger.info(f"[CommentAgent] Analyzing {len(comments)} comments for: {title[:50]}...")
            response = await self._call_llm(COMMENT_ANALYSIS_SYSTEM, user_message)
            return self._parse_response(response)
        except Exception as e:
            utils.logger.error(f"[CommentAgent] Analysis failed: {e}")
            return CommentAnalysis(success=False, error=str(e))

    def _extract_comment_text(self, comment: Dict[str, Any]) -> str:
        """Extract the text content from a comment dict (platform-agnostic)."""
        return (
            comment.get("content", "")
            or comment.get("text", "")
            or comment.get("comment_text", "")
            or str(comment)
        )

    def _parse_response(self, response: str) -> CommentAnalysis:
        """Parse Claude JSON response into CommentAnalysis."""
        try:
            json_str = response.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1]) if len(lines) > 2 else json_str.strip("`")

            data = json.loads(json_str)
            return CommentAnalysis(
                success=True,
                raw_response=response,
                sentiment_distribution=data.get("sentiment_distribution", {}),
                key_themes=data.get("key_themes", []),
                user_intents=data.get("user_intents", []),
                engagement_insights=data.get("engagement_insights", ""),
                top_comments_summary=data.get("top_comments_summary", ""),
                suggestions=data.get("suggestions", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            utils.logger.warning(f"[CommentAgent] Failed to parse response: {e}")
            return CommentAnalysis(success=False, error=f"Parse error: {e}", raw_response=response)
