# MediaCrawler Pro 功能测试指南

本文档说明如何测试 Pro 版三大功能模块。

## 前置条件

- Python 3.11+ 已安装，`uv` 已安装
- 已运行 `uv sync` 安装所有依赖（包括 `anthropic`）
- 浏览器已安装（登录需要）
- Docker & Docker Compose（测试 Docker 部署需要）
- Claude API Key（测试 AI Agent 需要，从 https://console.anthropic.com/ 获取）

---

## 一、单元测试（自动化）

直接运行所有单元测试：

```bash
uv run pytest tests/ -v
```

预期输出：`148 passed, 0 failed`

测试覆盖：
- **Agent 基础** (test_agent_base.py): dataclass、BaseAgent 配置
- **Agent 解析** (test_agent_agents.py): ContentAgent/CommentAgent JSON 解析、错误处理
- **Agent Runner** (test_agent_runner.py): 单例模式、配置开关
- **API Schema** (test_api_schemas.py): Pydantic 模型验证
- **HomeFeed 枚举** (test_homefeed.py): 5 平台 FeedType 定义
- **Docker 基础设施** (test_docker.py): Dockerfile、docker-compose、.dockerignore 结构验证

---

## 二、HomeFeed 信息流爬取测试

### 2.1 小红书 (XHS)

```bash
# 推荐信息流（默认 recommend）
uv run main.py --platform xhs --type feed --feed_category recommend --crawl_limit 5

# 其他分类
uv run main.py --platform xhs --type feed --feed_category homefeed.fashion_v3 --crawl_limit 5
uv run main.py --platform xhs --type feed --feed_category homefeed.food_v3 --crawl_limit 5
```

**验证点：**
- 浏览器弹出 → 扫码登录 → 自动开始爬取首页推荐笔记
- 检查 `data/xhs/` 目录是否有新的 JSONL 文件
- 日志中应出现 `[XhsCrawler.feed]` 相关日志

### 2.2 抖音 (Douyin)

```bash
# 推荐视频流
uv run main.py --platform dy --type feed --feed_category 0 --crawl_limit 5

# 热门视频流
uv run main.py --platform dy --type feed --feed_category 1 --crawl_limit 5
```

### 2.3 B站 (Bilibili)

```bash
# 热门视频
uv run main.py --platform bili --type feed --feed_category popular --crawl_limit 5

# 推荐视频
uv run main.py --platform bili --type feed --feed_category recommend --crawl_limit 5
```

### 2.4 微博 (Weibo)

```bash
# 热门微博
uv run main.py --platform wb --type feed --feed_category 102803 --crawl_limit 5

# 推荐微博
uv run main.py --platform wb --type feed --feed_category 102803_ctg1_600059 --crawl_limit 5
```

### 2.5 快手 (Kuaishou)

```bash
# 推荐视频
uv run main.py --platform ks --type feed --feed_category recommend --crawl_limit 5

# 热门视频
uv run main.py --platform ks --type feed --feed_category hot --crawl_limit 5
```

---

## 三、AI Agent 测试

### 3.1 内容拆解 Agent（命令行）

需要先配置 Claude API Key：

```bash
# 方式1: 在 config/base_config.py 中设置
CLAUDE_API_KEY = "sk-ant-api03-xxx"

# 方式2: 命令行参数
uv run main.py --platform xhs --type detail --specified_id xxx \
  --enable_content_agent \
  --claude_api_key "sk-ant-api03-xxx"
```

**验证点：**
- 爬取笔记后，日志中出现 `[ContentAgent] Analyzing content: ...`
- 保存的 JSONL 文件中包含 `ai_analysis` 字段
- `ai_analysis` 包含: `title_score`, `title_analysis`, `content_structure`, `key_points`, `engagement_hooks`, `suggested_tags`, `content_type`, `sentiment`

### 3.2 评论分析 Agent（命令行）

```bash
uv run main.py --platform xhs --type detail --specified_id xxx \
  --enable_comment_agent \
  --claude_api_key "sk-ant-api03-xxx"
```

**验证点：**
- 评论爬取完成后，日志中出现 `[CommentAgent] Analyzing N comments for: ...`
- `data/xhs/comment_analysis_xhs.jsonl` 文件中保存了分析结果
- 分析结果包含: `sentiment_distribution`, `key_themes`, `user_intents`, `engagement_insights`, `top_comments_summary`, `suggestions`

### 3.3 AI Agent 通过 API 测试

先启动 API 服务：

```bash
uv run python api/main.py
```

**内容拆解 API：**
```bash
curl -X POST http://localhost:8080/api/crawler/analyze-content \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "xhs",
    "content_id": "test_123",
    "title": "Python 入门教程：10分钟学会写第一个程序",
    "desc": "这是一篇详细的 Python 入门教程，涵盖变量、循环、函数等基础概念",
    "tags": ["Python", "编程入门", "教程"],
    "content_type": "normal",
    "liked_count": 500,
    "collected_count": 200,
    "comment_count": 50,
    "share_count": 30
  }'
```

**评论分析 API：**
```bash
curl -X POST http://localhost:8080/api/crawler/analyze-comments \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "xhs",
    "content_id": "test_123",
    "content_title": "Python 入门教程",
    "content_type": "normal",
    "comments": [
      {"content": "写得太好了，终于看懂了！"},
      {"content": "请问有没有进阶教程推荐？"},
      {"content": "收藏了，慢慢学"},
      {"content": "这个教程对新手很友好"},
      {"content": "第三步有个小错误，变量名应该是 a 不是 b"}
    ]
  }'
```

**验证点：**
- 返回 JSON 中 `success: true`
- `analysis` 字段包含结构化分析结果

**未配置 API Key 时的错误处理：**
```bash
# 如果 CLAUDE_API_KEY 未设置，应返回 400
curl -X POST http://localhost:8080/api/crawler/analyze-content \
  -H "Content-Type: application/json" \
  -d '{"platform": "xhs", "content_id": "test"}'
# 预期: {"detail": "CLAUDE_API_KEY not configured"}
```

---

## 四、Docker 部署测试

### 4.1 构建镜像

```bash
docker build -t mediacrawler:test .
```

**验证点：**
- 构建成功，无报错
- 镜像大小合理（约 1-2GB）

### 4.2 基础运行

```bash
# 简单运行（需要宿主机 .env 配置）
docker run --rm \
  -v $(pwd)/.env:/app/.env \
  -v $(pwd)/data:/app/data \
  mediacrawler:test \
  --platform xhs --type search --keywords "Python" --crawl_limit 3
```

### 4.3 Docker Compose

```bash
# 仅主服务
docker compose up -d mediacrawler

# 主服务 + MySQL
docker compose --profile db up -d

# 全服务（MySQL + Redis + MongoDB + WebUI）
docker compose --profile full up -d
```

**验证点：**
```bash
# 检查容器状态
docker compose ps

# 查看爬虫日志
docker compose logs -f mediacrawler

# 检查数据卷
docker volume ls | grep mediacrawler

# 进入容器检查
docker compose exec mediacrawler ls /app/data/
```

### 4.4 清理

```bash
docker compose down
docker compose --profile full down
```

---

## 五、快速验证清单

| 功能 | 测试方式 | 预期结果 |
|------|---------|---------|
| 单元测试 | `pytest tests/ -v` | 148 passed |
| XHS Feed | `--type feed --feed_category recommend` | 爬取首页推荐笔记 |
| Douyin Feed | `--platform dy --type feed` | 爬取推荐视频 |
| Bilibili Feed | `--platform bili --type feed` | 爬取热门/推荐视频 |
| Weibo Feed | `--platform wb --type feed` | 爬取热门/推荐微博 |
| Kuaishou Feed | `--platform ks --type feed` | 爬取推荐视频 |
| Content Agent | `--enable_content_agent` | JSONL 含 ai_analysis 字段 |
| Comment Agent | `--enable_comment_agent` | 生成 comment_analysis.jsonl |
| Agent API | curl /api/crawler/analyze-content | 返回结构化分析 |
| Docker 构建 | `docker build` | 镜像构建成功 |
| Docker Compose | `docker compose up` | 容器正常运行 |

---

## 六、常见问题

### Agent 不工作？
1. 检查 `CLAUDE_API_KEY` 是否正确设置
2. 检查 `ENABLE_CONTENT_AGENT` / `ENABLE_COMMENT_AGENT` 是否为 True
3. 查看日志是否有 `[ContentAgent]` / `[CommentAgent]` 输出

### Feed 爬取失败？
1. 确认已登录（扫码登录成功）
2. 检查 feed_category 值是否正确（XHS 用 `homefeed_recommend` 而不是 `recommend`）
3. 查看日志中 API 请求是否返回数据

### Docker 构建失败？
1. 确认 Docker 版本 >= 20.10（支持多阶段构建）
2. 网络问题：Playwright chromium 下载可能需要代理
3. 检查 `.env` 文件是否正确配置
