"""LLM 薄路由层：OpenAI 兼容客户端 + 渠道优先级/fallback + 成本日志。

- 模型字符串约定 `provider/model`（与 litellm 一致，后续可换 litellm 后端）。
- 渠道 = 某 provider 的一组 key；env key 缺失的渠道自动跳过。
- JSON 模式：response_format=json_object + Pydantic 校验，失败带错误重试一次。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Type

import httpx
from pydantic import BaseModel, ValidationError

from ...core import config
from ..http import client_for
from ...storage import dao

PROVIDER_PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com"},
    "volcengine": {"base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    "openai": {"base_url": "https://api.openai.com/v1"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
}

# 美元 / 1M tokens: (input, output)。未知模型按 0 计，只影响成本估算。
PRICING = {
    "deepseek/deepseek-chat": (0.27, 1.10),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
}


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    parsed: Any = None
    model: str = ""
    channel: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_est: float = 0.0
    raw: dict = field(default_factory=dict)


def _enabled_channels() -> list[dict]:
    channels = config.get("llm.channels", [])
    out = []
    for ch in channels:
        if config.get_env(ch.get("env_key", "")):
            out.append(ch)
    return sorted(out, key=lambda c: c.get("priority", 99))


def _resolve(model_str: str) -> tuple[str, str]:
    provider, _, model = model_str.partition("/")
    return provider, model


def _estimate_cost(model_str: str, pt: int, ct: int) -> float:
    pin, pout = PRICING.get(model_str, (0.0, 0.0))
    return (pt * pin + ct * pout) / 1_000_000


def _chat(channel: dict, model: str, messages: list[dict], temperature: float,
          json_mode: bool, max_tokens: int | None, timeout: float = 120.0) -> dict:
    preset = PROVIDER_PRESETS.get(channel["provider"], {})
    base_url = channel.get("base_url") or preset.get("base_url")
    if not base_url:
        raise LLMError(f"provider {channel['provider']} 缺少 base_url")
    key = config.get_env(channel["env_key"])
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    with client_for(base_url, timeout=timeout) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
        )
    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "choices" not in data or not data["choices"]:
        raise LLMError(f"返回缺少 choices: {str(data)[:300]}")
    return data


def complete(purpose: str, messages: list[dict], schema: Type[BaseModel] | None = None,
             max_tokens: int | None = None, article_id: str | None = None,
             stage: str = "") -> LLMResult:
    """按用途路由调用。schema 给出时启用 JSON 模式并做 Pydantic 校验（失败重试一次）。"""
    route = config.get(f"llm.routing.{purpose}") or config.get("llm.routing.rewrite")
    model_str = route["model"]
    temperature = float(route.get("temperature", 0.7))
    provider, model = _resolve(model_str)

    candidates = [c for c in _enabled_channels() if c["provider"] == provider]
    if not candidates:
        raise LLMError(
            f"没有可用的 {provider} 渠道（检查 .env 中 {purpose} → {model_str} 对应的 key）")

    last_err: Exception | None = None
    for channel in candidates:
        msgs = list(messages)
        for attempt in range(2):  # 第二次为 schema 纠错重试
            t0 = time.time()
            try:
                data = _chat(channel, model, msgs, temperature, json_mode=schema is not None,
                             max_tokens=max_tokens)
                text = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage", {})
                result = LLMResult(
                    text=text, model=model_str, channel=channel["name"],
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=int((time.time() - t0) * 1000),
                )
                result.cost_est = _estimate_cost(model_str, result.prompt_tokens,
                                                 result.completion_tokens)
                if schema is not None:
                    result.parsed = schema.model_validate(_extract_json(text))
                _log(article_id, stage or purpose, result, ok=True)
                return result
            except (LLMError, httpx.HTTPError) as e:
                last_err = e
                _log(article_id, stage or purpose,
                     LLMResult(text="", model=model_str, channel=channel["name"]), ok=False)
                break  # 网络/HTTP 错误 → 换渠道
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                if attempt == 0:
                    msgs = msgs + [
                        {"role": "assistant", "content": data.get("choices", [{}])[0]
                         .get("message", {}).get("content", "")},
                        {"role": "user", "content":
                            f"上次输出不符合要求（{e}）。请只输出符合约定的 JSON，不要输出其他内容。"},
                    ]
                    continue
    raise LLMError(f"所有渠道调用失败: {last_err}")


def _extract_json(text: str) -> Any:
    """容忍模型在 JSON 外包一层 ```json fence。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("输出中找不到 JSON")
    return json.loads(t[start:])


def _log(article_id: str | None, stage: str, r: LLMResult, ok: bool) -> None:
    if not config.get("llm.cost_log", True):
        return
    try:
        dao.log_llm_call(article_id, stage, r.channel, r.model, r.prompt_tokens,
                         r.completion_tokens, r.latency_ms, r.cost_est, ok)
    except Exception:
        pass


def available() -> bool:
    return bool(_enabled_channels())
