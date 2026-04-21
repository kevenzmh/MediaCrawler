# -*- coding: utf-8 -*-
"""Content Decomposition Agent - Analyze crawled content using Claude API."""

import json
from typing import Any, Dict, Optional

from tools import utils

from .base_agent import BaseAgent, ContentAnalysis
from .prompts import CONTENT_DECOMPOSE_SYSTEM, CONTENT_DECOMPOSE_USER


class ContentAgent(BaseAgent):
    """AI agent for content decomposition and analysis."""

    async def analyze(self, content: Dict[str, Any]) -> ContentAnalysis:
        """Analyze a single piece of content.

        Args:
            content: Content data dict with keys like title, desc, tags, etc.

        Returns:
            ContentAnalysis with structured decomposition results.
        """
        if not self.is_configured:
            utils.logger.warning("[ContentAgent] Claude API key not configured, skipping analysis")
            return ContentAnalysis(success=False, error="API key not configured")

        title = content.get("title", "") or content.get("name", "")
        desc = content.get("desc", "") or content.get("description", "") or content.get("content", "")
        tags = content.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(str(t) for t in tags[:10]) if tags else "无"
        else:
            tags_str = str(tags)
        note_type = content.get("type", "") or content.get("note_type", "")
        liked_count = content.get("liked_count", 0)
        collected_count = content.get("collected_count", 0)
        comment_count = content.get("comment_count", 0)
        share_count = content.get("share_count", 0)

        user_message = CONTENT_DECOMPOSE_USER.format(
            title=title[:200],
            desc=desc[:2000],
            tags=tags_str,
            note_type=note_type,
            liked_count=liked_count,
            collected_count=collected_count,
            comment_count=comment_count,
            share_count=share_count,
        )

        try:
            utils.logger.info(f"[ContentAgent] Analyzing content: {title[:50]}...")
            response = await self._call_llm(CONTENT_DECOMPOSE_SYSTEM, user_message)
            return self._parse_response(response)
        except Exception as e:
            utils.logger.error(f"[ContentAgent] Analysis failed: {e}")
            return ContentAnalysis(success=False, error=str(e))

    def _parse_response(self, response: str) -> ContentAnalysis:
        """Parse Claude JSON response into ContentAnalysis."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = response.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1]) if len(lines) > 2 else json_str.strip("`")

            data = json.loads(json_str)
            return ContentAnalysis(
                success=True,
                raw_response=response,
                title_score=float(data.get("title_score", 0)),
                title_analysis=data.get("title_analysis", ""),
                content_structure=data.get("content_structure", ""),
                key_points=data.get("key_points", []),
                engagement_hooks=data.get("engagement_hooks", []),
                suggested_tags=data.get("suggested_tags", []),
                content_type=data.get("content_type", ""),
                sentiment=data.get("sentiment", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            utils.logger.warning(f"[ContentAgent] Failed to parse response: {e}")
            return ContentAnalysis(success=False, error=f"Parse error: {e}", raw_response=response)
