"""Embedding：OpenAI 兼容 /embeddings（火山方舟 doubao-embedding 等）。

不可用时（无 key/无配置）降级为 NullEmbedder，语义功能整体退回 FTS（拍板结论 #4）。
"""
from __future__ import annotations

import array
import math

import httpx

from ...core import config
from ..llm.router import PROVIDER_PRESETS, _enabled_channels, _resolve


def pack_vector(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


class NullEmbedder:
    available = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class ApiEmbedder:
    available = True

    def __init__(self, channel: dict, model: str) -> None:
        preset = PROVIDER_PRESETS.get(channel["provider"], {})
        self.base_url = (channel.get("base_url") or preset.get("base_url", "")).rstrip("/")
        self.key = config.get_env(channel["env_key"])
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, "input": texts},
            )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in items]


def get_embedder():
    conf = config.get("llm.embedding") or {}
    model_str = conf.get("model")
    if not model_str:
        return NullEmbedder()
    provider, model = _resolve(model_str)
    for ch in _enabled_channels():
        if ch["provider"] == provider:
            return ApiEmbedder(ch, model)
    return NullEmbedder()
