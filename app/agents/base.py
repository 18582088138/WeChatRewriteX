"""Agent 基类：prompt 模板加载（config/prompts/）、风格包加载、LLM 调用封装。

LLM 可注入（测试用 FakeLLM 替换 router.complete），保证无 key 也能跑通流程逻辑。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Type

import yaml
from jinja2 import Template
from pydantic import BaseModel

from ..core import config
from ..services.llm import router

LLMCallable = Callable[..., router.LLMResult]


class AgentBase:
    name = "base"

    def __init__(self, llm: LLMCallable | None = None) -> None:
        self.llm: LLMCallable = llm or router.complete
        self._llm_injected = llm is not None

    # ---- prompt / style ----

    def prompt(self, template_name: str, **ctx: Any) -> str:
        path = config.CONFIG_DIR / "prompts" / self.name / f"{template_name}.j2"
        if not path.exists():
            raise FileNotFoundError(f"缺少 prompt 模板: {path}")
        return Template(path.read_text(encoding="utf-8")).render(**ctx)

    @staticmethod
    def load_style_pack(pack_name: str | None = None) -> dict[str, Any]:
        d = config.style_dir(pack_name)
        pack: dict[str, Any] = {"name": d.name, "system": "", "rules": "", "banlist": [],
                                "fewshots": "", "meta": {}}
        if (d / "style.yaml").exists():
            pack["meta"] = yaml.safe_load((d / "style.yaml").read_text(encoding="utf-8")) or {}
        for fname, key in (("system.md", "system"), ("rules.md", "rules")):
            p = d / fname
            if p.exists():
                pack[key] = p.read_text(encoding="utf-8")
        bl = d / "banlist.txt"
        if bl.exists():
            pack["banlist"] = [x.strip() for x in bl.read_text(encoding="utf-8").splitlines()
                               if x.strip()]
        fs_dir = d / "fewshots"
        if fs_dir.exists():
            parts = [f.read_text(encoding="utf-8") for f in sorted(fs_dir.glob("*.md"))]
            pack["fewshots"] = "\n\n---\n\n".join(parts)
        return pack

    # ---- llm ----

    def complete(self, purpose: str, messages: list[dict],
                 schema: Type[BaseModel] | None = None,
                 article_id: str | None = None, stage: str = "",
                 max_tokens: int | None = None) -> router.LLMResult:
        return self.llm(purpose=purpose, messages=messages, schema=schema,
                        article_id=article_id, stage=stage or f"{self.name}",
                        max_tokens=max_tokens)

    def llm_available(self) -> bool:
        return self._llm_injected or router.available({"creator": "create", "reviewer": "review", "collector": "summarize"}.get(self.name))

    # ---- 进度事件（对齐收集 Agent：前端等待动画 + 文字日志 + 文件日志） ----

    def progress(self, article_id: str, message: str) -> None:
        from ..core import events
        events.bus.publish(events.STAGE_PROGRESS, article_id,
                           stage=self.name, message=message)
        from .. import logging_setup
        logging_setup.log("info", "[%s] %s (article=%s)", self.name, message, article_id)
