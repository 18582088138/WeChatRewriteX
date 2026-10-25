"""三层配置：代码默认值 < config/settings.yaml < 数据库 settings 表（GUI 修改）。

密钥只从 .env / 环境变量读（`get_env`），不进入本模块的值体系。
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")

DEFAULTS: dict[str, Any] = {
    "collect": {
        "search_window_days": 3,
        "allow_foundational": True,
        "ref_count": {"min": 3, "max": 5, "scarce_min": 1},
        "image_min_width": 400,
        "watermark_check": "heuristic",
    },
    "create": {"style_pack": "tech-evangelist", "target_word_count": 1500, "originality_guard": True},
    "review": {
        "block_on_blocker": True,
        "originality": {"simhash_warn": 0.35, "simhash_block": 0.55, "embedding_warn": 0.75, "embedding_block": 0.85},
        "ai_flavor_score_max": 3,
        "recheck_on_edit": {"enabled": True, "min_changed_blocks": 3, "min_word_delta_pct": 20},
    },
    "pipeline": {"auto": False, "concurrency": {"llm": 2, "download": 4}},
    "dev": {"mode": False},
    "cards": {"theme": "tech-note", "width": 1080, "height": 1440, "max_chars_per_page": 380, "min_font_px": 26},
    "variants": {
        "wechat_mp": {"word_range": [1200, 1800]},
        "xhs": {"max_chars": 1000, "pages": [3, 9]},
        "weibo": {"max_chars": 140},
        "x": {"max_tweets": 6},
    },
    "llm": {
        "channels": [
            {"name": "deepseek", "provider": "deepseek", "env_key": "DEEPSEEK_API_KEY", "priority": 1},
            {"name": "ark", "provider": "volcengine", "env_key": "ARK_API_KEY", "priority": 2},
            {"name": "openai", "provider": "openai", "env_key": "OPENAI_API_KEY", "priority": 3},
        ],
        "routing": {
            "summarize": {"model": "deepseek/deepseek-chat", "temperature": 0.3},
            "create": {"model": "deepseek/deepseek-chat", "temperature": 0.7},
            "compress": {"model": "deepseek/deepseek-chat", "temperature": 0.3},
            "review": {"model": "deepseek/deepseek-chat", "temperature": 0.2},
            "vision": {"model": "volcengine/doubao-vision-pro-32k", "temperature": 0.2},
        },
        "embedding": {"model": "volcengine/doubao-embedding-large", "dimension": 2560},
        "cost_log": True,
    },
    "storage": {"data_dir": "resource", "material_size_limit_mb": 500},
    "hooks": {},
}

_db_overlay: Callable[[], dict[str, Any]] | None = None
_cache: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml() -> dict:
    path = CONFIG_DIR / "settings.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload() -> None:
    global _cache
    _cache = None


def _expand_flat(d: dict) -> dict:
    """DB 覆盖是扁平点号键（'a.b.c' -> v），展开为嵌套 dict 再合并。"""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if "." not in k:
            out[k] = v
            continue
        node = out
        parts = k.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return out


def all_settings() -> dict:
    global _cache
    if _cache is None:
        merged = _deep_merge(DEFAULTS, _load_yaml())
        if _db_overlay:
            merged = _deep_merge(merged, _expand_flat(_db_overlay()))
        _cache = merged
    return _cache


def get(path: str, default: Any = None) -> Any:
    node: Any = all_settings()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_env(key: str) -> str | None:
    v = os.environ.get(key)
    return v if v else None


def set_db_overlay(provider: Callable[[], dict[str, Any]]) -> None:
    """storage 层启动时注册，提供 DB 设置覆盖（扁平 dict: 'a.b.c' -> value 或嵌套 dict）。"""
    global _db_overlay
    _db_overlay = provider
    reload()


def style_dir(pack_name: str | None = None) -> Path:
    name = pack_name or get("create.style_pack", "tech-evangelist")
    return CONFIG_DIR / "styles" / name


def data_dir() -> Path:
    env = os.environ.get("WRA_DATA_DIR")     # 测试/便携模式可覆盖数据目录
    if env:
        return Path(env)
    d = Path(get("storage.data_dir", "data"))
    return d if d.is_absolute() else PROJECT_ROOT / d
