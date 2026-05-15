#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 发布模块

发布模式：
1. 话题发布（短内容）：POST /v2/groups/{group_id}/topics
2. 文章发布（长内容）：先 POST /v2/articles 创建文章，再 POST topics 引用文章

内部实现：底层通过 zsxq-cli api raw 调用官方 API，不再依赖 auth.json。
"""

from __future__ import annotations

import json
import mimetypes
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


def _sh(cmd: List[str]) -> str:
    """执行 shell 命令，失败则抛异常"""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p.stdout


# ── zsxq-cli 封装层 ────────────────────────────────────────────

def auth_status() -> Dict[str, Any]:
    """通过 zsxq-cli 检查登录状态"""
    out = _sh(["zsxq-cli", "auth", "status", "--json"])
    return json.loads(out)


def ensure_auth() -> None:
    """确保已登录，未登录则抛出异常提示"""
    data = auth_status()
    if not ((data.get("ok") is True) and ((data.get("data") or {}).get("loggedIn") is True)):
        raise RuntimeError(
            "未登录知识星球，请先运行：zsxq-cli auth login\n"
            "或在 Skill 环境中使用 zsxq-shared 技能的 login 流程。"
        )


def api_call(tool: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """通过 zsxq-cli 调用 MCP 工具"""
    cmd = ["zsxq-cli", "api", "call", tool]
    if params:
        cmd += ["--params", json.dumps(params, ensure_ascii=False)]
    out = _sh(cmd)
    data = json.loads(out)
    return data.get("result", {}).get("body", {})


def api_raw(method: str, path: str, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """通过 zsxq-cli raw 调用 API（灵活调用任意端点）"""
    cmd = ["zsxq-cli", "api", "raw", "--method", method, "--path", path]
    if body is not None:
        cmd += ["--body", json.dumps(body, ensure_ascii=False)]
    if query is not None:
        cmd += ["--query", json.dumps(query, ensure_ascii=False)]
    out = _sh(cmd)
    data = json.loads(out)
    return data.get("result", {}).get("body", {})


def get_upload_token() -> str:
    """申请七牛云图片上传 token（通过官方 upload 端点）"""
    body = api_raw("POST", "/v2/uploads", {
        "req_data": {"type": "image", "usage": "article", "name": "", "hash": "", "size": ""}
    })
    token = ((body.get("resp_data") or {}).get("upload_token"))
    if not token:
        raise RuntimeError(f"获取 upload_token 失败: {json.dumps(body, ensure_ascii=False)[:300]}")
    return token


def upload_image(image_path: Path) -> Dict[str, Any]:
    """上传单张图片到知识星球 CDN，返回 image_id 和 url"""
    token = get_upload_token()
    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "application/octet-stream"
    files = {"file": (image_path.name, image_path.read_bytes(), mime_type)}
    resp = requests.post("https://upload-z1.qiniup.com/", files=files, data={"token": token}, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("succeeded"):
        raise RuntimeError(f"图片上传失败: {json.dumps(body, ensure_ascii=False)[:300]}")
    return {
        "image_id": body["resp_data"]["image_id"],
        "url": body.get("link", ""),
    }


# ── Markdown 转换 ────────────────────────────────────────────

ZSXQ_IMG_PATTERN = re.compile(r"^https://article-images\.zsxq\.com/[A-Za-z0-9_-]+$")
MARKDOWN_IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """处理内联 Markdown 格式：内联代码、加粗、斜体、链接。"""
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def markdown_to_article_html(md_text: str) -> str:
    """将 Markdown 转换为知识星球文章 HTML。

    支持：标题、段落、无序/有序列表、引用、代码块、表格、图片、内联格式。
    """
    lines = md_text.splitlines()
    html: List[str] = []
    in_ul = False
    in_ol = False
    i = 0

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            html.append("</ul>")
            in_ul = False
        if in_ol:
            html.append("</ol>")
            in_ol = False

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # 空行
        if not line:
            close_lists()
            i += 1
            continue

        # 代码块
        if line.startswith("```"):
            close_lists()
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结束 ```
            code = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html.append(f"<pre><code>{code}</code></pre>")
            continue

        # 表格（标题行 + 分隔行）
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s|:-]+\|\s*$", lines[i + 1]):
            close_lists()
            table_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            headers = [_inline(c.strip()) for c in table_lines[0].strip("|").split("|")]
            rows = [
                [_inline(c.strip()) for c in l.strip("|").split("|")]
                for l in table_lines[2:]
            ]
            t = "<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
            t += "</tbody></table>"
            html.append(t)
            continue

        # 引用块（连续 > 行合并为一个 blockquote）
        if line.startswith(">"):
            close_lists()
            quote_lines: List[str] = []
            while i < len(lines) and (lines[i].strip().startswith(">") or lines[i].strip() == ">"):
                stripped = lines[i].strip()
                quote_lines.append(stripped[2:] if stripped.startswith("> ") else stripped[1:])
                i += 1
            content = "<br>".join(_inline(l) for l in quote_lines)
            html.append(f"<blockquote>{content}</blockquote>")
            continue

        # 知识星球图片 CDN URL
        if ZSXQ_IMG_PATTERN.match(line):
            close_lists()
            html.append(f'<img src="{line}" />')
            i += 1
            continue

        # HTML <img> 标签
        if line.startswith("<img"):
            close_lists()
            html.append(line)
            i += 1
            continue

        # 标题
        if line.startswith("### "):
            close_lists()
            html.append(f"<h3>{_inline(line[4:].strip())}</h3>")
            i += 1
            continue
        if line.startswith("## "):
            close_lists()
            html.append(f"<h2>{_inline(line[3:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("# "):
            close_lists()
            html.append(f"<h1>{_inline(line[2:].strip())}</h1>")
            i += 1
            continue

        # 无序列表
        if re.match(r"^[-*] ", line):
            if in_ol:
                html.append("</ol>")
                in_ol = False
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            html.append(f"<li>{_inline(line[2:].strip())}</li>")
            i += 1
            continue

        # 有序列表
        ol_m = re.match(r"^\d+\.\s+(.+)$", line)
        if ol_m:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            if not in_ol:
                html.append("<ol>")
                in_ol = True
            html.append(f"<li>{_inline(ol_m.group(1))}</li>")
            i += 1
            continue

        # 普通段落
        close_lists()
        html.append(f"<p>{_inline(line)}</p>")
        i += 1

    close_lists()
    return "\n".join(html)


def markdown_to_topic_text(md_text: str, title: str = "") -> str:
    """将 Markdown 转为知识星球话题纯文本（保留结构和标签）"""
    lines = []
    if title:
        lines.append(f"**{title}**\n")
    for raw in md_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            lines.append(f"• {line[2:].strip()}")
        else:
            lines.append(line)
    return "\n".join(lines)


def extract_title_from_markdown(md_text: str) -> Tuple[str, str]:
    """从 Markdown 中提取标题和正文"""
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = m.group(1).strip() if m else "未命名"
    body = re.sub(r"^#.+\n", "", md_text, count=1).strip()
    return title, body


def format_hashtags(tags: List[str]) -> str:
    return " ".join(f"#{t}" for t in tags)


# ── 发布器 ──────────────────────────────────────────────────

class ZsxqPublisher:
    """知识星球内容发布器（基于 zsxq-cli）"""

    def __init__(self):
        ensure_auth()  # 初始化时即检查认证

    def publish_topic(
        self,
        text: str,
        title: str = "",
        group_id: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """发布话题（短内容）

        Args:
            text: 话题正文
            title: 可选标题（加粗显示）
            group_id: 目标星球 ID，不填则使用默认
            tags: 可选标签列表
        Returns:
            API 响应数据（含 topic_id）
        """
        topic_text = markdown_to_topic_text(text, title=title)
        if tags:
            topic_text += "\n" + format_hashtags(tags)

        gid = group_id or self._get_default_group_id()
        payload = {"req_data": {"type": "talk", "text": topic_text}}

        result = api_raw("POST", f"/v2/groups/{gid}/topics", body=payload)

        if result and result.get("succeeded"):
            topic_data = ((result.get("resp_data") or {}).get("topic") or {})
            print(f"  [OK] 话题发布成功 topic_id={topic_data.get('topic_id')}")
        else:
            print(f"  [FAIL] 话题发布失败: {json.dumps(result, ensure_ascii=False)[:300]}")

        return result or {}

    def publish_article(
        self,
        md_content: str,
        title: str = "",
        group_id: str = "",
        tags: Optional[List[str]] = None,
        image_path: Optional[Path] = None,
        base_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """发布文章（长内容，两步流程）

        Step 1: POST /v2/articles 创建文章（含图片上传）
        Step 2: POST /v2/groups/{id}/topics 创建引用文章的主题

        Args:
            md_content: Markdown 格式文章内容
            title: 文章标题（默认从 Markdown 提取）
            group_id: 目标星球 ID，不填则使用默认
            tags: 可选标签列表
            image_path: 可选本地长图路径（会先上传到 CDN 再插入文章）
            base_dir: 本地图片基准目录
        Returns:
            API 响应（含 article_id、topic_id）
        """
        # 提取标题和正文
        if not title:
            title, body = extract_title_from_markdown(md_content)
        else:
            _, body = extract_title_from_markdown(md_content)

        if not title:
            title = "未命名文章"

        gid = group_id or self._get_default_group_id()
        image_ids: List[int] = []
        image_url: Optional[str] = None

        # Step 0: 处理配图（可选）
        if image_path and Path(image_path).exists():
            print(f"  [图] 上传长图...")
            up = upload_image(Path(image_path))
            image_ids.append(up["image_id"])
            image_url = up.get("url")
            print(f"  [OK] 图片已上传 image_id={up['image_id']} url={image_url}")

        # Step 0b: 处理 md_content 里的图片引用（如果有）
        if base_dir:
            md_content, extra_ids = self._process_md_images(md_content, Path(base_dir))
            image_ids.extend(extra_ids)

        # Step 1: 创建文章
        print(f"  [Step 1] 创建文章 '{title}'...")
        article_html = markdown_to_article_html(md_content)
        article_payload = {
            "req_data": {
                "group_id": gid,
                "title": title,
                "content": article_html,
                "original_content": md_content,
                "image_ids": image_ids,
            }
        }

        article_result = None
        for attempt in range(1, 6):
            article_result = api_raw("POST", "/v2/articles", body=article_payload)
            if article_result and article_result.get("succeeded"):
                break
            code = (article_result or {}).get("code")
            if code in (429, 1059) or article_result is None:
                print(f"    创建文章瞬时失败(code={code})，第{attempt}次重试...")
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if not article_result or not article_result.get("succeeded"):
            print(f"  [FAIL] 文章创建失败: {json.dumps(article_result, ensure_ascii=False)[:300]}")
            return article_result or {}

        article_data = article_result.get("resp_data") or {}
        article_id = article_data.get("article_id")
        article_url = article_data.get("article_url")
        print(f"  [OK] 文章已创建 article_id={article_id} url={article_url}")

        # 适当延迟
        time.sleep(random.uniform(0.5, 1.5))

        # Step 2: 创建普通话题（摘要 + 文章链接）
        print(f"  [Step 2] 创建话题摘要与链接...")
        summary = self._build_article_summary(md_content, max_chars=180)
        topic_lines = [f"<b>{title}</b>"]
        if summary:
            topic_lines.extend(["", summary])
        topic_lines.extend(["", "详细步骤见文章：", article_url])
        if tags:
            topic_lines.extend(["", format_hashtags(tags)])
        topic_text = "\n".join(topic_lines)

        topic_payload = {
            "req_data": {
                "type": "talk",
                "text": topic_text,
            }
        }

        topic_result = None
        for attempt in range(1, 6):
            topic_result = api_raw("POST", f"/v2/groups/{gid}/topics", body=topic_payload)
            if topic_result and topic_result.get("succeeded"):
                break
            code = (topic_result or {}).get("code")
            if code in (429, 1059) or topic_result is None:
                time.sleep(min(12.0, 2.5 * attempt))
                continue
            break

        if not topic_result or not topic_result.get("succeeded"):
            print(f"  [FAIL] 话题创建失败（文章已建）: {json.dumps(topic_result, ensure_ascii=False)[:300]}")
            return {"succeeded": True, "article_id": article_id, "article_url": article_url, "topic_fail": True}

        topic_data = ((topic_result.get("resp_data") or {}).get("topic") or {})
        print(f"  [OK] 话题已发布 topic_id={topic_data.get('topic_id')}")

        return {
            "succeeded": True,
            "article_id": article_id,
            "article_url": article_url,
            "topic_id": topic_data.get("topic_id"),
            "process_status": topic_data.get("process_status"),
        }

    def _process_md_images(self, md_content: str, base_dir: Path) -> Tuple[str, List[int]]:
        """处理 Markdown 中的图片引用，上传到 CDN 并替换为 HTML <img> 标签"""
        image_ids: List[int] = []
        # 匹配 markdown 图片语法：![alt](url)
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

        def replace_match(m: re.Match) -> str:
            """上传图片并替换为 <img src=ZSXQ_CDN_URL>"""
            url = m.group(2)
            if url.startswith(("http://", "https://")):
                return m.group(0)  # 远程图片保留原样
            img_path = base_dir / url if not Path(url).is_absolute() else Path(url)
            if not img_path.exists():
                return m.group(0)  # 文件不存在保留原样
            try:
                up = upload_image(img_path)
                image_ids.append(up["image_id"])
                print(f"    [OK] 图片已上传: {img_path.name} → image_id={up['image_id']}")
                up_url = up.get("url", url)
                return f'<img src="{up_url}" />'
            except Exception as e:
                print(f"    [WARN] 图片上传失败({img_path}): {e}")
                return m.group(0)

        new_content = pattern.sub(replace_match, md_content)
        return new_content, image_ids

    def _build_article_summary(self, md_content: str, max_chars: int = 180) -> str:
        """从 Markdown 中提取 100-200 字左右的简要介绍，用于话题摘要。"""
        text = md_content
        text = re.sub(r'<img[^>]*>', ' ', text, flags=re.I)
        text = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', ' ', text)
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.M)
        text = re.sub(r'^[-*+]\s*', '', text, flags=re.M)
        text = re.sub(r'^\d+\.\s*', '', text, flags=re.M)
        text = re.sub(r'`{1,3}[^`]*`{1,3}', ' ', text)
        # 将 Markdown 加粗/斜体渲染为 HTML（平台支持 HTML 标签）
        text = re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*([^*]+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars].rstrip('，。、；：,.;: ')
        return cut + '…'

    def _get_default_group_id(self) -> str:
        """优先读取 ~/.private_key/zsxq-publish/user_config.json，回退到 zsxq-cli 列表第一项"""
        config_path = Path.home() / ".private_key/zsxq-publish/user_config.json"
        try:
            data = json.loads(config_path.read_text())
            gid = str(data.get("group_id", "")).strip()
            if gid:
                return gid
        except Exception:
            pass
        try:
            out = _sh(["zsxq-cli", "group", "+list", "--json"])
            data = json.loads(out)
            groups = data.get("groups", [])
            if groups:
                return str(groups[0].get("group_id", ""))
        except Exception:
            pass
        return ""