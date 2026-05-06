# zsxq-publisher

> 知识星球内容发布工具（二次封装版）。  
> 大部分操作透传到 OpenClaw 官方 zsxq skills，仅"发布带图长文章"需要本 skill 自持编排。

## 架构原则

- **查询 / 普通帖子**：透传到 `zsxq-cli` 官方工具
- **带图长文章发布**：本 skill 通过 `zsxq-cli api raw` 实现两步流程（官方 skills 未覆盖）
- **认证**：统一走 `zsxq-cli auth login`（Keychain），不再依赖 auth.json

## 安装

```bash
# 已在 OpenClaw 环境中可用（zsxq-cli 默认已安装）
# 如需独立安装：
git clone https://github.com/koffuxu/zsxq-publisher.git ~/.claude/skills/zsxq-publisher
```

## 快速开始

### 1. 登录认证

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py login
# 或直接
zsxq-cli auth login
```

### 2. 发布文章（含图）

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py article \
  --file "./weekly_report.md" \
  --title "创作周报 2026-05-06" \
  --tags "周报"
```

### 3. 发布普通话题

```bash
python ~/.claude/skills/zsxq-publisher/scripts/run.py main.py topic \
  --text "分享一个 AI 工具使用技巧" \
  --title "技巧分享" \
  --tags "AI"
```

## 与官方 zsxq skills 的分工

| 操作 | 推荐工具 |
|------|---------|
| 查询星球 / 搜索话题 | `zsxq-cli group +list` / `zsxq-cli topic +search` |
| 发布普通帖子 | `zsxq-cli topic +create` |
| 发布带图长文章 | **zsxq-publisher**（两步流程 + 图片上传） |
| 笔记 / 评论 / 回复 | `zsxq-cli note` / `zsxq-cli topic +reply` |

## 文件结构

```
zsxq-publisher/
├── SKILL.md                    # 本 skill 定义（描述/触发词/工作流）
├── README.md                   # 本文件
├── requirements.txt            # Python 依赖
└── scripts/
    ├── run.py                  # 虚拟环境管理运行器
    ├── main.py                 # CLI 入口（7 个子命令）
    ├── auth.py                 # 认证封装（透传 zsxq-cli）
    ├── publisher.py            # 发布核心逻辑（两步流程 + 图片上传）
    └── markdown_converter.py  # Markdown → 知识星球格式转换
```

## 认证说明

- **不再需要 auth.json**：认证由 `zsxq-cli` 管理（OAuth 2.0 → Keychain）
- 登录一次后长期有效，无需频繁登录
- 如认证过期，运行 `zsxq-cli auth login` 重新授权

## 常见问题

**Q: 为什么发布长文章需要专门的 skill，而普通帖子不需要？**  
A: 普通 talk 类型官方 `zsxq-cli topic +create` 已覆盖。
长文章（article）需要两步：先 `POST /v2/articles` 再 `POST /v2/groups/{id}/topics` 引用文章，且需要预先上传图片获得 image_ids。这条流程官方 skills 尚未封装，故由本 skill 承担。

**Q: auth.json 还需要保留吗？**  
A: 不需要。认证已迁移到 zsxq-cli。旧的 auth.json 可以删除。

**Q: 图片上传支持的格式？**  
A: PNG、JPG、GIF、WebP。SVG 暂不支持。