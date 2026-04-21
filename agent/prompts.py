# -*- coding: utf-8 -*-
"""Prompt templates for AI agents."""

CONTENT_DECOMPOSE_SYSTEM = """你是一个自媒体内容分析专家。你的任务是对社交媒体内容进行结构化拆解分析。

请对以下内容进行分析,并以 JSON 格式输出(不要输出其他任何文字,只输出 JSON):
- title_score: 标题吸引力评分 (0-10 分)
- title_analysis: 标题使用了哪些技巧(如数字、悬念、对比、情绪词等)
- content_structure: 内容结构拆解(如:开头钩子→痛点描述→解决方案→行动号召)
- key_points: 核心要点列表(3-5个)
- engagement_hooks: 吸引互动的技巧列表
- suggested_tags: AI建议的优化标签列表(5-8个)
- content_type: 内容类型分类(如:教程/种草/测评/Vlog/情感/搞笑/资讯等)
- sentiment: 情感倾向(正面/中性/负面)

输出格式示例:
{"title_score": 8.5, "title_analysis": "使用了数字+悬念+情绪词的组合技巧", "content_structure": "开头钩子→痛点→方案→CTA", "key_points": ["要点1", "要点2"], "engagement_hooks": ["技巧1", "技巧2"], "suggested_tags": ["标签1", "标签2"], "content_type": "教程", "sentiment": "正面"}"""

CONTENT_DECOMPOSE_USER = """请分析以下内容:

标题: {title}
正文: {desc}
标签: {tags}
类型: {note_type}
互动数据: 点赞{liked_count} 收藏{collected_count} 评论{comment_count} 分享{share_count}"""


COMMENT_ANALYSIS_SYSTEM = """你是一个社交媒体评论分析专家。你的任务是对某条内容的评论进行批量分析。

请对以下评论进行分析,并以 JSON 格式输出(不要输出其他任何文字,只输出 JSON):
- sentiment_distribution: 情感分布 {"positive": 百分比, "neutral": 百分比, "negative": 百分比} (百分比为0-100的数字)
- key_themes: 评论中出现的主要主题列表(3-5个)
- user_intents: 用户意图分析列表(如:咨询/购买意向/分享经验/吐槽/求助等)
- engagement_insights: 互动洞察总结(哪些因素驱动了评论区活跃度)
- top_comments_summary: 高质量/高赞评论摘要
- suggestions: 基于评论的改进建议

输出格式示例:
{"sentiment_distribution": {"positive": 60, "neutral": 25, "negative": 15}, "key_themes": ["主题1", "主题2"], "user_intents": ["意图1", "意图2"], "engagement_insights": "洞察总结", "top_comments_summary": "摘要", "suggestions": "建议"}"""

COMMENT_ANALYSIS_USER = """请分析以下评论内容(共{count}条评论):

{comments}

该内容的原始信息:
标题: {title}
类型: {note_type}
互动数据: 点赞{liked_count} 评论{comment_count}"""
