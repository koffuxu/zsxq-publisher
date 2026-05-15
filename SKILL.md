---
name: zsxq-publisher
description: |
  知识星球内容发布工具（二次封装版）。
  
  架构原则：
  - 大部分操作直接透传到 OpenClaw 官方 zsxq skills（zsxq-cli / zsxq-group / zsxq-topic / zsxq-user / zsxq-note）
  - 仅"发布带图长文章"需要本 skill 自持编排逻辑（官方 skills 未覆盖此流程）
  
  认证：统一走 zsxq-cli auth login（Keychain 管理），不再依赖 auth.json。
  
  触发词：发布到知识星球、zsxq-publisher、知识星球发布、发布话题、发布文章、带图发布
allowed-tools: Bash, Read, Write, Glob, Grep
mode-command: false
---

# 知识星球发布工具（zxsq-publisher）

## 架构说明

本 skill 是对 OpenClaw 官方 zsxq skills 的**二次封装**：

| 操作类型 | 处理方式 |
|---------|---------|
| 查询星球 / 话题 / 用户 | 透传到 `zsxq-cli` 官方工具 |
| 发布普通帖子（talk） | 透传到 `zsxq-cli topic +create` |
| 发布长文章（article + 配图） | **本 skill 自持**，调用 `zsxq-cli api raw` 实现两步流程 |
| 认证管理 | 统一走 `zsxq-cli auth login`（不再用 auth.json） |

> **为什么文章发布需要自持？** 官方 `zsxq-cli topic +create` 仅支持纯文本/图片混合的 talk 类型。
> 带图长文章需要：①先调 `/v2/articles` 创建文章，②再调 `/v2/groups/{id}/topics` 引用文章。
> 这条两步流程官方 skills 未封装，所以需要本 skill 自行编排。

## 星球配置

配置文件位于 `~/.private_key/zsxq-publish/`：

| 星球名称 | group_id | 类型 |
|---------|---------|------|
| AI编程与自动化 | `28882452841521` | 付费（默认发布目标） |
| 人工智能成长写作 | `51128824585884` | 免费 |

- 默认 group_id 从 `~/.private_key/zsxq-publish/user_config.json` 读取
- 发布标题规则：**使用笔记原标题**，不使用 Notion「发布标题」字段（与其他平台不同）

## 运行器

```bash
RUN = "skills/zsxq-publisher/scripts/run.py"
```

## 命令参考

### 1. 认证相关（透传官方）

```bash
# 检查认证状态
python "${RUN}" main.py check-auth

# 浏览器登录（OAuth 设备码流程）
python "${RUN}" main.py login

# 查看星球列表（官方工具）
zsxq-cli group +list
```

> 认证由 `zsxq-cli` 管理（Keychain），登录一次后长期有效。

### 2. 查询类（透传官方）

```bash
# 搜索话题
zsxq-cli topic +search --group-id <id> --query "<关键词>"

# 查看话题详情
zsxq-cli topic +detail --topic-id <id>

# 查看用户足迹
zsxq-cli api call get_user_footprints --params '{"user_id":"...","group_id":"..."}'
```

### 3. 发布普通话题（透传官方）

```bash
# 通过 zsxq-publisher 快捷发布
python "${RUN}" main.py topic --text "内容" --title "标题" --tags "标签1,标签2"

# 或直接用官方 zsxq-cli
zsxq-cli topic +create --group-id <id> --title "标题" --content "正文"
```

### 4. 发布长文章（含配图）— 本 skill 自持

```bash
# 发布 Markdown 文件为知识星球文章（含图片自动上传）
python "${RUN}" main.py article --file "./weekly_report.md" --title "周报标题" --tags "周报"

# 发布时额外附带一张长图（如海报）
python "${RUN}" main.py article --file "./report.md" --image "./cover.png" --title "标题"
```

**发布流程（两步）：**
1. 上传图片到知识星球 CDN（image_id）
2. `POST /v2/articles` 创建文章（带 image_ids）
3. `POST /v2/groups/{id}/topics` 创建引用文章的主题

> **标题规则**：始终使用 `--title` 传入笔记**原标题**，不使用 Notion「发布标题」字段（与其他平台不同）。

### 5. 话题预览（显式调用，非默认）

发布前可生成本地 HTML 预览确认话题渲染效果，**默认不生成，只在用户明确要求时才执行**。

预览脚本逻辑（内联运行）：

```python
# 生成话题预览 HTML，保存到文章同目录 zsxq_topic_preview.html
import re, sys
sys.path.insert(0, 'skills/zsxq-publisher/scripts')
from publisher import build_summary  # 或内联 build_summary 函数

md = open("<article.md>", encoding="utf-8").read()
title = "<原始笔记标题>"
article_url = "https://articles.zsxq.com/id_<article_id>.html"
summary = build_summary(md)
topic_text = f"<b>{title}</b>\n\n{summary}\n\n详细步骤见文章：\n{article_url}"
# 将 topic_text 写入 HTML 文件并 open 预览
```

确认无误后再调用 api_raw 发布话题。话题摘要中 `**bold**` 会渲染为 `<strong>bold</strong>`（平台支持 HTML 标签）。

### 5. 自动判断模式

```bash
# 根据内容长度自动选择 talk 或 article 模式
python "${RUN}" main.py publish --file "./content.md" --tags "标签"
```

## 认证与权限说明

- **无需 auth.json**：认证统一由 `zsxq-cli` 管理（OAuth → Keychain）
- **登录一次后长期有效**：通常数周到数月
- **权限范围**：当前登录账号有权限的所有星球

## 与官方 zsxq skills 的分工

| 场景 | 使用方式 |
|------|---------|
| 查询星球成员、搜索话题 | 直接用 `zsxq-cli group +list` / `zsxq-cli topic +search` |
| 发布普通帖子 | 直接用 `zsxq-cli topic +create` |
| 发布带图长文章 | **通过 zsxq-publisher**：本 skill 编排两步流程 |
| 管理笔记、回复评论 | 直接用 `zsxq-cli note` / `zsxq-cli topic +reply` |

## 依赖

- `zsxq-cli`（必须，已包含在 OpenClaw 官方技能中）
- Python 3.9+
- `requests`（图片上传用，已在 .venv 中）

## 安全注意

- 发布前确认目标星球和内容（不可撤销的公开操作）
- 不确定 group_id 时先查询再操作