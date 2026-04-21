# -*- coding: utf-8 -*-
"""Base agent ABC for all AI agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentResult:
    """Base result for all agent analyses."""
    success: bool = True
    error: str = ""
    raw_response: str = ""


@dataclass
class ContentAnalysis(AgentResult):
    """Content decomposition analysis result."""
    title_score: float = 0.0
    title_analysis: str = ""
    content_structure: str = ""
    key_points: List[str] = field(default_factory=list)
    engagement_hooks: List[str] = field(default_factory=list)
    suggested_tags: List[str] = field(default_factory=list)
    content_type: str = ""
    sentiment: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title_score": self.title_score,
            "title_analysis": self.title_analysis,
            "content_structure": self.content_structure,
            "key_points": self.key_points,
            "engagement_hooks": self.engagement_hooks,
            "suggested_tags": self.suggested_tags,
            "content_type": self.content_type,
            "sentiment": self.sentiment,
        }


@dataclass
class CommentAnalysis(AgentResult):
    """Comment analysis result."""
    sentiment_distribution: Dict[str, float] = field(default_factory=dict)
    key_themes: List[str] = field(default_factory=list)
    user_intents: List[str] = field(default_factory=list)
    engagement_insights: str = ""
    top_comments_summary: str = ""
    suggestions: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sentiment_distribution": self.sentiment_distribution,
            "key_themes": self.key_themes,
            "user_intents": self.user_intents,
            "engagement_insights": self.engagement_insights,
            "top_comments_summary": self.top_comments_summary,
            "suggestions": self.suggestions,
        }


class BaseAgent(ABC):
    """Abstract base class for all AI agents."""

    def __init__(self, api_key: str = "", model: str = ""):
        import config
        self._api_key = api_key or config.CLAUDE_API_KEY
        self._model = model or config.CLAUDE_MODEL

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _create_client(self):
        """Create Anthropic client instance."""
        import anthropic
        return anthropic.Anthropic(api_key=self._api_key)

    async def _call_llm(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        """Call Claude API and return the response text."""
        if not self.is_configured:
            raise ValueError("Claude API key is not configured. Set CLAUDE_API_KEY in config or via --claude_api_key")

        client = self._create_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
