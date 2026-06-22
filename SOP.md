# South Bay Newsbot SOP

本文档是 `/Users/chuxuanfu/newsbot` 项目的结构化运行手册。目标是让这台 Mac Studio 本地 24/7 自动扫描信息源，只把“新出现”的内容推送到一个 Telegram bot，并对需要 AI 处理的来源生成简体中文摘要。

## 1. 项目目标

- 自动发现 South Bay / Bay Area 相关交通、天气、地震、火灾、本地新闻、Reddit、移民和裁员信息。
- 只推送从上一次抓取到本次抓取之间新增的内容，避免重复刷屏。
- 能立即判断的来源直接发 Telegram；需要 AI 摘要的来源进入 Ollama 处理后再发。
- 全部服务运行在本机 Mac Studio，可通过 `launchd` 开机自启和后台常驻。

## 2. 项目目录

```text
/Users/chuxuanfu/newsbot
├── app/                         # Python 应用代码
│   ├── main.py                  # CLI、daemon 主循环
│   ├── fetchers.py              # 各类信息源抓取
│   ├── storage.py               # SQLite 数据读写
│   ├── notifier.py              # Telegram 推送
│   ├── summarizer.py            # Ollama / AI 摘要
│   ├── classifier.py            # 事件分类与优先级逻辑
│   └── geo.py                   # 距离判断、地理编码、CHP 地图截图
├── config.yaml                  # 主配置
├── .env                         # 本机密钥和模型配置，不要公开
├── data/
│   ├── newsbot.sqlite3          # SQLite 数据库
│   └── maps/                    # CHP 地图截图缓存
├── logs/
│   ├── newsbot.out.log          # stdout
│   └── newsbot.err.log          # 应用日志 / stderr
├── launchd/
│   └── com.chuxuanfu.newsbot.plist.template
├── start_24_7.sh                # 安装并启动 launchd 后台服务
├── stop_24_7.sh                 # 停止 launchd 后台服务
├── SOURCES.md                   # 信息源清单
└── SOP.md                       # 本文件
```

## 3. 运行架构

```text
launchd
  -> /Users/chuxuanfu/newsbot/.venv/bin/python -m app.main daemon
      -> 按 config.yaml 的 interval 抓取 sources
      -> 新 raw item 写入 SQLite
      -> 不需要 AI 的 raw item 立即推送 Telegram
      -> Reddit / RSS / local_news 用 Ollama 摘要
      -> 处理完成后推送 Telegram
```

关键点：

- `launchd` 负责后台常驻和重启后自动启动。
- `daemon` 循环负责定时抓取、处理、推送。
- SQLite 负责去重、记录处理状态、记录通知历史。
- Telegram 是唯一通知入口。

## 4. 配置文件

主配置文件：

```bash
/Users/chuxuanfu/newsbot/config.yaml
```

本机密钥文件：

```bash
/Users/chuxuanfu/newsbot/.env
```

`.env` 常见字段：

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OLLAMA_MODEL=qwen3.6:27b
NEWSBOT_DB=/Users/chuxuanfu/newsbot/data/newsbot.sqlite3
NEWSBOT_CONFIG=/Users/chuxuanfu/newsbot/config.yaml
```

注意：

- 不要把 `.env` 发给别人。
- 不要把 Telegram token、OpenAI key、chat id 写进文档或聊天窗口。
- 改完 `.env` 或 `config.yaml` 后，建议重启后台服务。

## 5. 信息源 SOP

信息源完整清单维护在：

```bash
/Users/chuxuanfu/newsbot/SOURCES.md
```

当前类别：

- CHP Bay Area incident page
- NWS weather alerts
- USGS earthquake feed
- CalFire active incidents
- Visa Bulletin
- CA WARN
- Reddit subreddit feeds
- Bay Area local news RSS feeds

新增信息源流程：

1. 在 `config.yaml` 的 `sources` 中添加 source。
2. 如果是已有 fetcher 类型，复用现有字段。
3. 如果是新类型，在 `app/fetchers.py` 添加解析逻辑。
4. 在 `SOURCES.md` 增加说明、频率、限制和风险。
5. 手动跑一次 `fetch` 或 `run-once` 验证。
6. 确认 Telegram 推送格式正确。

## 6. 推送规则

默认策略：

- 新 raw item 入库后，如果该来源不需要 AI，立即推送 Telegram。
- Reddit / RSS / local_news 需要 Ollama 摘要，处理完一条发一条。
- Telegram 内容必须包含可直接打开的原始链接。
- AI 摘要只保留简体中文新闻摘要和链接，不展示 priority、urgency、relevance、credibility、why matters、action 等字段。
- 首次启用新 RSS 源时，默认只建立 baseline，避免把大量旧闻推给 Telegram。

旧新闻控制：

- RSS / local_news 默认只推送发布时间在 `rss_max_age_hours` 内的内容。
- 当前配置通常使用 12 小时窗口。
- 如果 RSS 本身返回旧文章，即使它是首次被抓到，也会被跳过。

## 7. CHP 交通事件 SOP

CHP 特殊规则：

- 只关注 San Jose 中心点附近约 25 miles 范围。
- 事故位置需要通过 `app/geo.py` 判断。
- 符合范围的事故会生成地图截图并随 Telegram 消息发送。
- 外区关键词会硬排除，避免 Marin、Napa、San Francisco、Oakland 等同名道路误推。

CHP 地图依赖：

- 地理编码：Nominatim / OpenStreetMap。
- 地图瓦片：OpenStreetMap tile。
- 距离计算：本地 Haversine 公式。

这意味着距离判断不是靠联网搜索新闻，而是：

- 先从 CHP 文本抽取 road / cross street / city。
- 必要时调用地理编码服务拿经纬度。
- 再用本地距离公式判断是否在半径内。

排查 CHP 没有推送：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m app.main status
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

如果日志里 CHP 有 `inserted=0`，通常代表 CHP 页面没有新事故或新事故已被去重。

如果 CHP 有新 raw item 但没通知，重点看：

- 是否被 25 miles 范围过滤。
- 是否被外区关键词过滤。
- 地理编码是否失败。
- Telegram 发送是否失败。

## 8. USGS 地震 SOP

当前规则：

- 只关注 San Jose 附近约 50 miles。
- 只推送 magnitude >= 3.0 的地震。
- USGS feed 抓取频率较高，但仍通过数据库去重。

如果要调整范围或震级：

1. 打开 `config.yaml`。
2. 找到 USGS source。
3. 修改 `max_distance_km` 或 `min_magnitude`。
4. 重启 daemon。

## 9. Reddit / RSS AI 摘要 SOP

AI 处理目标：

- 用 Ollama 本地模型生成简体中文摘要。
- 不输出 thinking 内容。
- 不输出模型分析字段。
- 保留原始链接。

当前模型通过 `.env` 控制：

```bash
OLLAMA_MODEL=qwen3.6:27b
```

Ollama 注意事项：

- 两个进程同时使用同一个模型通常可以工作，但会竞争显存、内存和 CPU/GPU。
- 如果 AI 长时间占用但 Telegram 没推送，通常是 backlog、模型慢、或某条内容处理超时。
- `process_batch_size` 控制每轮最多处理多少条 AI item，避免 AI 堵住抓取循环。

查看 AI 是否在处理：

```bash
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

常见日志：

```text
processed raw_id=123 event=True category=local priority=...
```

## 10. 后台运行 SOP

启动 24/7 后台服务：

```bash
cd /Users/chuxuanfu/newsbot
./start_24_7.sh
```

停止后台服务：

```bash
cd /Users/chuxuanfu/newsbot
./stop_24_7.sh
```

检查 launchd 是否在运行：

```bash
launchctl print gui/$(id -u)/com.chuxuanfu.newsbot | grep -E "state =|pid ="
```

查看日志：

```bash
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.out.log
```

查看应用状态：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m app.main status
```

## 11. 手动操作 SOP

进入项目环境：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
```

测试 Telegram：

```bash
python -m app.main test-telegram
```

手动跑一轮：

```bash
python -m app.main run-once
```

只抓取：

```bash
python -m app.main fetch
```

只处理 AI 队列：

```bash
python -m app.main process
```

只发送待发送通知：

```bash
python -m app.main notify
```

查看状态：

```bash
python -m app.main status
```

每个 RSS 源补发 2 条：

```bash
python -m app.main backfill-rss --limit-per-source 2
```

## 12. 变更发布 SOP

改代码或配置前：

1. 先确认当前服务状态。
2. 必要时停止后台服务。
3. 修改代码或配置。
4. 运行语法检查。
5. 手动跑一轮验证。
6. 重启后台服务。
7. 看日志确认没有异常。

推荐命令：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m compileall app
python -m app.main run-once
./start_24_7.sh
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

如果只是修改部分配置，仍建议重启：

```bash
cd /Users/chuxuanfu/newsbot
./start_24_7.sh
```

`start_24_7.sh` 会安装 / 重新加载 LaunchAgent，并启动服务。

## 13. 数据库和去重 SOP

数据库位置：

```bash
/Users/chuxuanfu/newsbot/data/newsbot.sqlite3
```

核心数据概念：

- raw item：从信息源抓到的原始内容。
- event：AI 或规则处理后的事件记录。
- notification：已经发给 Telegram 的记录。
- source state：每个 source 的最近运行时间、状态和错误。

不要随便删除数据库。删除数据库会导致系统失去去重历史，可能重新推送大量旧内容。

备份数据库：

```bash
cp /Users/chuxuanfu/newsbot/data/newsbot.sqlite3 /Users/chuxuanfu/newsbot/data/newsbot.sqlite3.bak
```

## 14. 排障 SOP

### Telegram 没有收到消息

检查：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m app.main test-telegram
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

可能原因：

- `.env` 里的 token 或 chat id 错误。
- Telegram API 临时失败。
- 没有新 item。
- item 被旧新闻过滤或地理范围过滤。

### Reddit 报 429 或抓取少

Reddit 多个 subreddit 共享同一个来源域名和 IP 限制。多个 subreddit 不是完全独立额度，频率过高会触发限流。

处理方式：

- 增大 Reddit source interval。
- 增大 `reddit_request_delay_seconds`。
- 减少 subreddit 数量。
- 接入 Reddit 官方 API，但需要 API key / OAuth。

### RSS 没有新内容

RSS 经常返回旧文章或延迟更新。系统会：

- 首次抓取建立 baseline。
- 之后只推送新增 item。
- 如果发布时间超过 `rss_max_age_hours`，即使首次看到也会跳过。

### AI 摘要不是简体中文

处理方式：

1. 检查 `OLLAMA_MODEL` 是否正确。
2. 查看日志是否有 retry。
3. 手动处理一批：

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m app.main process
```

### AI 一直占用但没有新 Telegram

可能原因：

- Ollama 模型慢。
- AI 队列里有旧 backlog。
- 某条内容摘要超时。
- 多个进程同时调用 Ollama。

查看：

```bash
python -m app.main status
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

### CHP 没有推送

检查 CHP source 是否有新 item：

```bash
python -m app.main status
```

如果 `chp_bay_area` 持续 `inserted=0`，说明没有新可入库 item 或都已去重。

如果有新 item 但没推送，检查：

- 是否超出 25 miles。
- 是否被外区关键词排除。
- Nominatim 是否返回错误地点。
- 地图截图是否生成失败。

## 15. 安全和隐私

- `.env` 是敏感文件，不要公开。
- Telegram 消息会经过 Telegram 服务。
- CHP 地图截图和地理编码会调用 OpenStreetMap / Nominatim 相关服务。
- Reddit / RSS / 政府信息源都是外部 HTTP 请求。
- 本地 SQLite 会保存抓取标题、摘要、链接和状态。

## 16. 日常维护

建议每周检查一次：

```bash
launchctl print gui/$(id -u)/com.chuxuanfu.newsbot | grep -E "state =|pid ="
python -m app.main status
tail -n 100 /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

建议每月做一次：

- 备份 `data/newsbot.sqlite3`。
- 检查 `SOURCES.md` 是否和 `config.yaml` 一致。
- 检查 RSS 源是否仍可访问。
- 检查 Reddit 是否频繁 429。
- 检查 Ollama 模型是否仍适合速度和质量要求。

## 17. 恢复 SOP

如果服务挂了：

```bash
cd /Users/chuxuanfu/newsbot
./start_24_7.sh
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

如果数据库损坏：

1. 停止服务。
2. 备份损坏数据库。
3. 恢复最近的 `.bak`。
4. 启动服务。

```bash
cd /Users/chuxuanfu/newsbot
./stop_24_7.sh
cp data/newsbot.sqlite3 data/newsbot.sqlite3.bad
cp data/newsbot.sqlite3.bak data/newsbot.sqlite3
./start_24_7.sh
```

如果 `.env` 丢失：

1. 重新创建 `.env`。
2. 填入 Telegram token、chat id、Ollama model。
3. 重启服务。

## 18. 常用命令速查

```bash
# 进入项目
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate

# 启动后台服务
./start_24_7.sh

# 停止后台服务
./stop_24_7.sh

# 检查 launchd 状态
launchctl print gui/$(id -u)/com.chuxuanfu.newsbot | grep -E "state =|pid ="

# 查看 app 状态
python -m app.main status

# 测试 Telegram
python -m app.main test-telegram

# 手动跑一轮
python -m app.main run-once

# 查看日志
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log

# 语法检查
python -m compileall app
```

