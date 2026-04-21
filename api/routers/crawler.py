# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/crawler.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from fastapi import APIRouter, HTTPException

from ..schemas import (
    CrawlerStartRequest, CrawlerStatusResponse,
    AgentContentRequest, AgentCommentsRequest, AgentAnalysisResponse,
)
from ..services import crawler_manager

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start crawler task"""
    success = await crawler_manager.start(request)
    if not success:
        # Handle concurrent/duplicate requests: if process is already running, return 400 instead of 500
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=400, detail="Crawler is already running")
        raise HTTPException(status_code=500, detail="Failed to start crawler")

    return {"status": "ok", "message": "Crawler started successfully"}


@router.post("/stop")
async def stop_crawler():
    """Stop crawler task"""
    success = await crawler_manager.stop()
    if not success:
        # Handle concurrent/duplicate requests: if process already exited/doesn't exist, return 400 instead of 500
        if not crawler_manager.process or crawler_manager.process.poll() is not None:
            raise HTTPException(status_code=400, detail="No crawler is running")
        raise HTTPException(status_code=500, detail="Failed to stop crawler")

    return {"status": "ok", "message": "Crawler stopped successfully"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status():
    """Get crawler status"""
    return crawler_manager.get_status()


@router.get("/logs")
async def get_logs(limit: int = 100):
    """Get recent logs"""
    logs = crawler_manager.logs[-limit:] if limit > 0 else crawler_manager.logs
    return {"logs": [log.model_dump() for log in logs]}


# ============================================================
# AI Agent endpoints
# ============================================================

@router.post("/analyze-content", response_model=AgentAnalysisResponse)
async def analyze_content(request: AgentContentRequest):
    """Analyze content using AI Content Decomposition Agent (Claude API).

    Returns structured analysis: title score, content structure, key points,
    engagement hooks, suggested tags, content type, and sentiment.
    """
    import config
    from agent.content_agent import ContentAgent

    if not config.CLAUDE_API_KEY:
        raise HTTPException(status_code=400, detail="CLAUDE_API_KEY not configured")

    content = {
        "title": request.title,
        "desc": request.desc,
        "tags": request.tags,
        "type": request.content_type,
        "liked_count": request.liked_count,
        "collected_count": request.collected_count,
        "comment_count": request.comment_count,
        "share_count": request.share_count,
    }

    agent = ContentAgent()
    result = await agent.analyze(content)

    if result.success:
        return AgentAnalysisResponse(success=True, analysis=result.to_dict())
    return AgentAnalysisResponse(success=False, error=result.error)


@router.post("/analyze-comments", response_model=AgentAnalysisResponse)
async def analyze_comments(request: AgentCommentsRequest):
    """Analyze comments using AI Comment Analysis Agent (Claude API).

    Returns structured analysis: sentiment distribution, key themes, user intents,
    engagement insights, top comments summary, and improvement suggestions.
    """
    import config
    from agent.comment_agent import CommentAgent

    if not config.CLAUDE_API_KEY:
        raise HTTPException(status_code=400, detail="CLAUDE_API_KEY not configured")

    content_context = {
        "title": request.content_title,
        "type": request.content_type,
        "liked_count": 0,
        "comment_count": len(request.comments),
    }

    agent = CommentAgent()
    result = await agent.analyze(request.comments, content_context)

    if result.success:
        return AgentAnalysisResponse(success=True, analysis=result.to_dict())
    return AgentAnalysisResponse(success=False, error=result.error)
