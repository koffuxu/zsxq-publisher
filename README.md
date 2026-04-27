# zsxq-publisherer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

知识星球内容发布工具 — Claude Code Skill

将本地 Markdown 文件或文本内容一键发布到知识星球，支持话题和长文章两种模式。

## 功能特性

- **话题发布**：短内容直接发布，支持加粗标题 + 标签
- **文章发布**：长内容自动走两步流程（创建文章 → 创建话题引用）
- **图片上传**：自动检测 Markdown 中的本地/远程图片，上传至知识星球 CDN
- **自动判断**：根据内容长度自动选择话题/文章模式（阈值 500 字符）
- **Markdown 转换**：自动将 Markdown 转为知识星球富文本格式
- **浏览器登录**：Cookie 过期时自动打开 Chrome 扫码登录，登录后持久化保存
- **发布历史**：本地记录每次发布的话题ID、文章链接、时间等信息

## 环境要求

- Python 3.9+
- Chrome 浏览器（用于扫码登录）
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI

## 安装

```bash
git clone https://github.com/koffuxu/zsxq-publisherer.git ~/.claude/skills/zsxq-publisherer
```

## 首次配置

### 1. 运行配置向导

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py setup
```

按提示输入：
- **星球 ID**：从星球页面 URL 中获取（`https://wx.zsxq.com/group/这里的数字`）
- **auth.json 路径**：Cookie 认证文件存放位置，留空使用默认路径 `~/.private_key/zsxq-publisher/auth.json`

### 2. 登录授权

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py login
```

自动打开 Chrome 浏览器到知识星球登录页，用微信扫码后 Cookie 会自动保存。登录一次后长期有效（通常数周到数月）。

### 3. 验证

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py check-auth
```

看到 `[OK] 认证有效` 即可开始使用。

## 使用方式

### 在 Claude Code 中使用（推荐）

安装完成后，在 Claude Code 对话中直接说：

- "把 xxx.md 发布到知识星球"
- "发布一个话题，标题是xxx，内容是xxx"
- "检查知识星球认证状态"
- "查看发布历史"

Claude 会自动调用此技能完成操作。

### 命令行使用

```bash
# 简写
RUN="~/.claude/skills/zsxq-publisher/scripts/run.py"

# 发布文件（自动判断话题/文章）
python $RUN main.py publish --file "文章.md" --tags "标签1,标签2"

# 发布话题（短内容）
python $RUN main.py topic --text "话题内容" --title "标题" --tags "标签"

# 发布文章（长内容）
python $RUN main.py article --file "长文.md" --title "文章标题"

# 查看发布历史
python $RUN main.py history

# 检查认证状态
python $RUN main.py check-auth

# 重新登录
python $RUN main.py login

# 重新配置
python $RUN main.py setup
```

## 文件结构

```
zsxq-publisher/
├── SKILL.md                    # Claude Code 技能定义
├── README.md                   # 本文件
├── requirements.txt            # Python 依赖（requests, markdown, selenium）
├── .gitignore
├── scripts/
│   ├── run.py                 # 虚拟环境自动管理运行器
│   ├── main.py                # CLI 入口（7 个子命令）
│   ├── config.py              # 可移植配置模块（首次交互式设置）
│   ├── auth.py                # Cookie 认证管理
│   ├── login.py               # Selenium 浏览器自动登录
│   ├── publisher.py           # 核心发布逻辑
│   └── markdown_converter.py  # Markdown → 知识星球格式转换
└── data/                       # 运行时数据（gitignored）
    └── publish_history.json   # 发布历史记录

敏感配置统一保存在 `~/.private_key/zsxq-publisher/`：

```text
~/.private_key/zsxq-publisher/
├── auth.json                  # Cookie 认证信息
├── user_config.json           # 当前默认星球配置
└── groups.json                # 星球列表
```


## 工作原理

### 知识星球 API

本工具通过逆向工程的知识星球 Web API 实现发布功能：

- **话题发布**：`POST /v2/groups/{group_id}/topics`
- **文章发布**：`POST /v2/articles`（创建文章）→ `POST /v2/groups/{group_id}/topics`（创建引用话题）
- **认证方式**：Cookie（`zsxq_access_token`）

### 内容格式

- **话题**：纯文本 + XML 标签（`<e type="text_bold"/>` 加粗、`<e type="hashtag"/>` 标签）
- **文章**：标准 HTML（`<p>`、`<h3>`、`<strong>`、`<a>` 等）

### 虚拟环境

`run.py` 运行器会自动：
1. 创建 `.venv/` 虚拟环境
2. 安装 `requirements.txt` 中的依赖
3. 在隔离环境中执行目标脚本

无需手动管理依赖。

## 常见问题

**Q: 发布后状态显示 `in_review` 是什么意思？**
A: 这是正常的，知识星球会对内容进行审核，审核通过后自动展示。

**Q: Cookie 多久过期？**
A: 通常数周到数月。过期后运行 `login` 命令重新扫码即可。

**Q: 支持图片上传吗？**
A: 支持。文章模式会自动检测 Markdown 中的图片引用（本地相对/绝对路径或远程 URL），上传至知识星球 CDN 并在文章中正确渲染。

**Q: 除了 Chrome 还支持什么浏览器？**
A: 支持 Chrome 和 Edge，优先使用 Chrome，Chrome 不可用时自动回退到 Edge。

## Star 增长

[![Star History Chart](https://api.star-history.com/svg?repos=koffuxu/zsxq-publisher&type=Date)](https://star-history.com/#koffuxu/zsxq-publisher&Date)

## 作者

| 平台 | 链接 |
|---|---|
| X（Twitter） | [@koffuxu](https://x.com/koffuxu) |
| 微信公众号 | 可夫小子 |

## License

[MIT](LICENSE)
