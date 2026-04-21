# -*- coding: utf-8 -*-
"""Agent integration helpers - easy functions to call from crawlers."""

import asyncio
from typing import Any, Dict, List, Optional

import config
from tools import utils

from .content_agent import ContentAgent
from .comment_agent import CommentAgent
from .base_agent import ContentAnalysis, CommentAnalysis

# Singleton agent instances
_content_agent: Optional[ContentAgent] = None
_comment_agent: Optional[CommentAgent] = None


def _get_content_agent() -> Optional[ContentAgent]:
    global _content_agent
    if not config.ENABLE_CONTENT_AGENT:
        return None
    if _content_agent is None:
        _content_agent = ContentAgent()
    if not _content_agent.is_configured:
        utils.logger.warning("[AgentRunner] ContentAgent not configured (CLAUDE_API_KEY missing)")
        return None
    return _content_agent


def _get_comment_agent() -> Optional[CommentAgent]:
    global _comment_agent
    if not config.ENABLE_COMMENT_AGENT:
        return None
    if _comment_agent is None:
        _comment_agent = CommentAgent()
    if not _comment_agent.is_configured:
        utils.logger.warning("[AgentRunner] CommentAgent not configured (CLAUDE_API_KEY missing)")
        return None
    return _comment_agent


async def analyze_content(content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Analyze content using ContentAgent. Returns analysis dict or None if disabled.

    This is the main integration point for content decomposition.
    Call this before saving content to store.

    Args:
        content: Content data dict (platform-specific format)

    Returns:
        Dict with analysis results, or None if agent is disabled.
    """
    agent = _get_content_agent()
    if agent is None:
        return None

    result: ContentAnalysis = await agent.analyze(content)
    if result.success:
        return result.to_dict()
    return None


async def analyze_comments(
    comments: List[Dict[str, Any]],
    content_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Analyze comments using CommentAgent. Returns analysis dict or None if disabled.

    This is the main integration point for comment analysis.
    Call this after all comments for a content item have been collected.

    Args:
        comments: List of comment dicts
        content_context: Optional content context (title, type, etc.)

    Returns:
        Dict with analysis results, or None if agent is disabled.
    """
    agent = _get_comment_agent()
    if agent is None:
        return None

    result: CommentAnalysis = await agent.analyze(comments, content_context)
    if result.success:
        return result.to_dict()
    return None
