# Docker 部署指南

## 快速开始

### 1. 准备环境

确保已安装 Docker 和 Docker Compose:
```bash
docker --version        # 需要 >= 20.10
docker compose version  # 需要 >= 2.0
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件,配置爬虫参数
```

关键配置项:
- `PLATFORM`: 爬取平台 (xhs/dy/ks/bili/wb/tieba/zhihu)
- `CRAWLER_TYPE`: 爬取类型 (search/detail/creator/feed)
- `LOGIN_TYPE`: 登录方式 (qrcode/phone/cookie)
- `COOKIES`: Cookie 字符串(登录方式为 cookie 时必填)
- `SAVE_DATA_OPTION`: 数据存储方式 (jsonl 默认,也支持 db/sqlite/mongodb 等)
- `CLAUDE_API_KEY`: Claude API 密钥(使用 AI Agent 功能时必填)

### 3. 启动爬虫

**基础模式(仅爬虫,JSONL 存储):**
```bash
docker compose up -d
```

**带数据库模式(爬虫 + MySQL):**
```bash
docker compose --profile db up -d
```

**完整模式(爬虫 + MySQL + Redis + MongoDB + API WebUI):**
```bash
docker compose --profile full up -d
```

### 4. 查看日志

```bash
docker compose logs -f mediacrawler
```

### 5. 停止服务

```bash
docker compose down
# 带数据库模式:
docker compose --profile db down
```

---

## 使用方式

### 方式一: 命令行参数覆盖

默认 ENTRYPOINT 为 `uv run python main.py`,可通过 `docker run` 传入任意 CLI 参数:

```bash
# 搜索小红书
docker run --rm \
  -e PLATFORM=xhs \
  -e COOKIES="your_cookie_here" \
  -v $(pwd)/data:/app/data \
  mediacrawler main.py --platform xhs --type search --keywords "Python编程"

# 获取指定帖子详情
docker run --rm \
  -e COOKIES="your_cookie_here" \
  -v $(pwd)/data:/app/data \
  mediacrawler main.py --platform xhs --type detail --specified_id "note_id_1,note_id_2"
```

### 方式二: 修改 docker-compose.yml 中的 command

```yaml
services:
  mediacrawler:
    # 覆盖默认启动命令
    command: ["main.py", "--platform", "dy", "--type", "search", "--keywords", "抖音热门"]
```

### 方式三: 通过 API WebUI

启动完整模式后,访问 `http://localhost:8080` 使用 WebUI 操作。

---

## 数据存储

### JSONL 模式(默认)

数据保存在容器内的 `/app/data` 目录,已映射到宿主机的 `./data` 目录:
```
data/
├── xhs/
│   ├── search_xhs_note_20240101.jsonl
│   └── search_xhs_comment_20240101.jsonl
└── .checkpoint/
    └── xhs_search.json
```

### 数据库模式

需在 `.env` 中配置数据库连接信息,并确保对应的数据库服务已启动:

**MySQL:**
```env
SAVE_DATA_OPTION=db
DB_HOST=mysql
DB_PORT=3306
DB_USER=mediacrawler
DB_PASSWORD=your_password
DB_NAME=mediacrawler
```

**MongoDB:**
```env
SAVE_DATA_OPTION=mongodb
MONGO_URI=mongodb://mongo:27017
```

---

## Cookie 获取

Docker 环境下推荐使用 `cookie` 登录方式:

1. 在本地浏览器中登录对应平台
2. 打开开发者工具(F12) → Application → Cookies
3. 复制所有 Cookie 值,粘贴到 `.env` 文件的 `COOKIES` 变量中
4. 重启容器: `docker compose restart mediacrawler`

---

## 多账号配置

挂载自定义 `accounts.json` 到容器中:

```yaml
services:
  mediacrawler:
    volumes:
      - ./accounts.json:/app/accounts.json:ro
```

参考 `accounts.json` 模板配置多账号和代理绑定。

---

## 构建自定义镜像

```bash
# 构建镜像
docker build -t mediacrawler:latest .

# 使用自定义镜像
docker compose up -d --build
```

---

## 常见问题

### Q: 容器内无法启动浏览器
A: 确保已安装 Playwright 系统依赖。Dockerfile 已自动处理,如果手动构建请确保运行 `playwright install --with-deps chromium`。

### Q: 中文显示乱码
A: Dockerfile 已安装 `fonts-noto-cjk` 中文字体,如仍有问题请检查终端编码设置。

### Q: 数据无法持久化
A: 确保 `./data` 目录有写入权限,且容器挂载路径正确。

### Q: 如何更新镜像
```bash
docker compose pull
docker compose up -d --build
```
