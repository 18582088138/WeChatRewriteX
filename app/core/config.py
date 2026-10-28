"""三层配置：代码默认值 < config/settings.yaml < 数据库 settings 表（GUI 修改）。

密钥只从 .env / 环境变量读（`get_env`），不进入本模块的值体系。

运行根解析（三种部署形态统一）：
- 仓库/开发态：仓库根目录（config/ 就地存在）；
- PyInstaller 冻结态：exe 所在目录（可写），只读资产在 sys._MEIPASS/wenshu_assets；
- pip 安装态：启动时的工作目录（可写），只读资产在包内 app/_assets。
首启时自动把 config/ 与 web/dist 从只读资产播种到运行根（已存在则不覆盖）。
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import yaml
from dotenv import load_dotenv


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


_repo_root = Path(__file__).resolve().parents[2]
if _is_frozen():
    RUNTIME_ROOT = Path(sys.executable).resolve().parent
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS")) / "wenshu_assets"
elif (_repo_root / "config").is_dir():
    RUNTIME_ROOT = BUNDLE_ROOT = _repo_root
else:                                       # pip 安装态：包内资产 → 启动 cwd
    RUNTIME_ROOT = Path.cwd()
    BUNDLE_ROOT = Path(__file__).resolve().parent.parent / "_assets"

PROJECT_ROOT = RUNTIME_ROOT                 # 兼容旧引用（可写运行根）
CONFIG_DIR = RUNTIME_ROOT / "config"
DATA_DIR = RUNTIME_ROOT / "data"


def ensure_runtime_assets() -> None:
    """首启播种：把内置 config/、web/dist、.env.example 铺到运行根（幂等）。"""
    if BUNDLE_ROOT == RUNTIME_ROOT:
        return
    try:
        src_cfg = BUNDLE_ROOT / "config"
        if src_cfg.is_dir() and not (CONFIG_DIR / "settings.yaml").exists():
            shutil.copytree(src_cfg, CONFIG_DIR, dirs_exist_ok=True)
        src_web = BUNDLE_ROOT / "web" / "dist"
        dst_web = RUNTIME_ROOT / "web" / "dist"
        if src_web.is_dir() and not (dst_web / "index.html").exists():
            shutil.copytree(src_web, dst_web, dirs_exist_ok=True)
        src_env = BUNDLE_ROOT / ".env.example"
        if src_env.is_file() and not (RUNTIME_ROOT / ".env").exists():
            shutil.copy(src_env, RUNTIME_ROOT / ".env")
    except OSError:
        pass        # 播种失败不致命：默认值兜底，界面首启再提示


def setup_playwright_browsers() -> None:
    """冻结态：发布包内附带的 playwright-browsers/ 优先于用户目录，
    实现卡片渲染开箱可用（免 playwright install）。"""
    if not _is_frozen() or os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    bundled = RUNTIME_ROOT / "playwright-browsers"
    if bundled.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)


ensure_runtime_assets()
setup_playwright_browsers()
load_dotenv(RUNTIME_ROOT / ".env")

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
    "log": {"level": "INFO", "path": "log", "keep_days": 14},
    "hooks": {},
}

_db_overlay: Callable[[], dict[str, Any]] | None = None
_cache: dict[str, Any] | None = None
_snapshot = ContextVar("settings_snapshot", default=None)


@contextmanager
def using_snapshot(settings: dict):
    token = _snapshot.set(copy.deepcopy(settings))
    try:
        yield
    finally:
        _snapshot.reset(token)


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
    if _snapshot.get() is not None:
        return _snapshot.get()
    if _cache is None:
        merged = _deep_merge(DEFAULTS, _load_yaml())
        if _db_overlay:
            from .settings_policy import MUTABLE
            expanded = _expand_flat(_db_overlay())
            overlay = {}
            for key in MUTABLE:
                value = expanded
                for part in key.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                if value is not None:
                    overlay[key] = value
            merged = _deep_merge(merged, _expand_flat(overlay))
        from .settings_policy import validate
        _cache = validate(merged)
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
    target = (CONFIG_DIR / "styles" / name).resolve()
    if not target.is_relative_to((CONFIG_DIR / "styles").resolve()):
        raise ValueError("风格包路径无效")
    return target


def data_dir() -> Path:
    # 测试/便携模式可覆盖数据目录；旧名 WRA_DATA_DIR 仅作兼容回退
    env = os.environ.get("WENSHU_DATA_DIR") or os.environ.get("WRA_DATA_DIR")
    if env:
        return Path(env)
    d = Path(get("storage.data_dir", "data"))
    return d if d.is_absolute() else RUNTIME_ROOT / d
