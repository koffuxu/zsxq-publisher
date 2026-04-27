#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识星球发布工具 - 配置模块

敏感配置统一存储在 ~/.private_key/zsxq-publish/ 下，
首次运行时自动引导设置；发布历史仍保留在技能 data/ 目录。
"""

import json
import sys
from pathlib import Path

# 目录配置（固定，不随用户变化）
SKILL_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
DATA_DIR = SKILL_DIR / "data"
PRIVATE_DIR = Path.home() / ".private_key" / "zsxq-publish"
PUBLISH_HISTORY_FILE = DATA_DIR / "publish_history.json"
USER_CONFIG_FILE = PRIVATE_DIR / "user_config.json"
AUTH_FILE = PRIVATE_DIR / "auth.json"
GROUPS_FILE = PRIVATE_DIR / "groups.json"
LEGACY_USER_CONFIG_FILE = DATA_DIR / "user_config.json"
LEGACY_AUTH_FILE = DATA_DIR / "auth.json"
LEGACY_GROUPS_FILE = Path.home() / ".private_key" / "zsxq_groups.json"

# 确保存储目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
PRIVATE_DIR.mkdir(parents=True, exist_ok=True)

# 知识星球 API 固定配置
API_BASE = "https://api.zsxq.com/v2"
QINIU_UPLOAD_URL = "https://upload-z1.qiniup.com/"
API_VERSION = "2.89.0"
ARTICLE_THRESHOLD = 500
TOPIC_MAX_TEXT_LENGTH = 10000
TOPIC_MAX_IMAGE_COUNT = 9


def _migrate_file(src: Path, dst: Path) -> bool:
    """将旧位置文件迁移到新位置。仅在目标不存在时复制。"""
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    return False


def _ensure_private_storage_layout() -> None:
    """兼容旧版 data/ 存储布局，统一迁移到 ~/.private_key/zsxq-publish/。"""
    _migrate_file(LEGACY_AUTH_FILE, AUTH_FILE)
    _migrate_file(LEGACY_GROUPS_FILE, GROUPS_FILE)

    if LEGACY_USER_CONFIG_FILE.exists():
        legacy = json.loads(LEGACY_USER_CONFIG_FILE.read_text(encoding="utf-8"))
        changed = False
        if legacy.get("auth_file") and Path(legacy["auth_file"]) != AUTH_FILE:
            changed = True
        legacy["auth_file"] = str(AUTH_FILE)

        if not USER_CONFIG_FILE.exists():
            USER_CONFIG_FILE.write_text(
                json.dumps(legacy, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif changed:
            current = json.loads(USER_CONFIG_FILE.read_text(encoding="utf-8"))
            current["auth_file"] = str(AUTH_FILE)
            USER_CONFIG_FILE.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


_ensure_private_storage_layout()


def _load_user_config() -> dict:
    """加载用户配置，不存在则返回空字典"""
    if USER_CONFIG_FILE.exists():
        with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_user_config(config: dict) -> None:
    """保存用户配置"""
    config = {**config, "auth_file": str(AUTH_FILE)}
    with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def setup_wizard() -> dict:
    """交互式配置向导，首次运行时调用"""
    print("=" * 50)
    print("  知识星球发布工具 - 首次配置")
    print("=" * 50)
    print()

    # 1. 星球 ID
    print("请输入你的知识星球 ID（从星球页面 URL 中获取）:")
    print("  例如: https://wx.zsxq.com/group/15554418212152")
    print("  星球ID就是 group/ 后面的数字")
    group_id = input("  星球ID: ").strip()
    if not group_id.isdigit():
        print("[error] 星球ID必须是纯数字")
        sys.exit(1)

    # 2. auth.json 路径
    print()
    print("请输入 auth.json 文件的存放路径:")
    print("  (Cookie 认证文件，留空则存在 ~/.private_key/zsxq-publish/ 下)")
    auth_path = input("  路径: ").strip()
    if not auth_path:
        auth_path = str(AUTH_FILE)
    else:
        auth_path = str(Path(auth_path).resolve())

    config = {
        "group_id": group_id,
        "auth_file": auth_path,
    }

    _save_user_config(config)
    print()
    print(f"[OK] 配置已保存到 {USER_CONFIG_FILE}")
    print(f"  星球ID: {group_id}")
    print(f"  认证文件: {auth_path}")
    print()
    return config


def get_user_config() -> dict:
    """获取用户配置，不存在则运行配置向导"""
    config = _load_user_config()
    if config and config.get("auth_file") != str(AUTH_FILE):
        config["auth_file"] = str(AUTH_FILE)
        _save_user_config(config)
    if not config.get("group_id"):
        config = setup_wizard()
    return config


# --- 加载用户配置并构建运行时常量 ---
_user_config = _load_user_config()
if _user_config and _user_config.get("auth_file") != str(AUTH_FILE):
    _user_config["auth_file"] = str(AUTH_FILE)
    _save_user_config(_user_config)

GROUP_ID = _user_config.get("group_id", "")

ENDPOINTS = {
    "create_article": f"{API_BASE}/articles",
    "create_topic": f"{API_BASE}/groups/{GROUP_ID}/topics",
    "settings": f"{API_BASE}/settings",
    "hashtags": f"{API_BASE}/users/self/groups/{GROUP_ID}/hashtags",
    "upload_image": f"{API_BASE}/uploads",
}
