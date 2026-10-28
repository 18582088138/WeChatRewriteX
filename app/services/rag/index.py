"""素材检索：FTS5 全文（always）+ 向量语义（embedding 可用时）。

用途：洗稿选图/取证、审稿 claims 找证据、撞稿语义比对。
向量存 embeddings 表（float32 blob），维度与配置不一致的存量自动重建。
"""
from __future__ import annotations

import hashlib
import json

from ...core import config
from ...storage import dao, db
from ..embed.embedder import cosine, get_embedder, pack_vector, unpack_vector


def index_materials(material_ids: list[str] | None = None,
                    article_id: str | None = None) -> int:
    """为文本素材建立向量索引（无 embedding 渠道时静默返回 0）。返回新增条数。"""
    emb = get_embedder()
    if not emb.available:
        return 0
    if material_ids is None:
        pairs = dao.all_material_texts(article_id)
    else:
        pairs = [(mid, dao.get_material_text(mid)) for mid in material_ids]
    model_id = json.dumps(config.get("llm.embedding") or {}, sort_keys=True)
    want_dim = int((config.get("llm.embedding") or {}).get("dimension", 0))
    todo: list[tuple[str, str]] = []
    for mid, content in pairs:
        if not content.strip():
            continue
        row = db.query_one("SELECT dim, model_id, content_hash FROM embeddings WHERE material_id=?", (mid,))
        digest = hashlib.sha256(content.encode()).hexdigest()
        if row and row["model_id"] == model_id and row["content_hash"] == digest and (not want_dim or row["dim"] == want_dim):
            continue
        todo.append((mid, content))   # 截断控制成本
    count = 0
    for i in range(0, len(todo), 32):
        batch = todo[i:i + 32]
        try:
            vecs = emb.embed([c[:2000] for _, c in batch])
        except Exception:
            break
        for (mid, content), vec in zip(batch, vecs):
            with db.transaction():
                # Discard a late embedding if a recrawl changed the evidence meanwhile.
                if dao.get_material_text(mid) != content or (dao.get_material(mid) or {}).get("deleted_at"):
                    continue
                db.execute("INSERT OR REPLACE INTO embeddings(material_id,dim,vector,model_id,content_hash) VALUES(?,?,?,?,?)",
                           (mid, len(vec), pack_vector(vec), model_id, hashlib.sha256(content.encode()).hexdigest()))
                count += 1
    return count


def semantic_search(query: str, article_id: str | None = None,
                    top_k: int = 8) -> list[tuple[str, float]]:
    """向量相似度检索，返回 (material_id, score)。embedding 不可用时返回空。"""
    emb = get_embedder()
    if not emb.available:
        return []
    try:
        qv = emb.embed([query[:1000]])[0]
    except Exception:
        return []
    if article_id:
        rows = db.query(
            "SELECT e.material_id, e.vector FROM embeddings e "
            "JOIN materials m ON m.id=e.material_id "
            "WHERE m.deleted_at IS NULL AND (m.article_id=? OR m.scope='common') AND e.model_id=? AND e.dim=?",
            (article_id, json.dumps(config.get("llm.embedding") or {}, sort_keys=True), len(qv)))
    else:
        rows = db.query("SELECT e.material_id, e.vector FROM embeddings e JOIN materials m ON m.id=e.material_id WHERE m.deleted_at IS NULL AND e.model_id=? AND e.dim=?", (json.dumps(config.get("llm.embedding") or {}, sort_keys=True), len(qv)))
    scored = [(r["material_id"], cosine(qv, unpack_vector(r["vector"]))) for r in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def text_search(query: str, limit: int = 10, article_id: str | None = None) -> list[tuple[str, str]]:
    """全文检索，返回 (material_id, snippet)。"""
    return dao.search_materials_fts(query, limit, article_id)


def evidence_for_claim(claim: str, article_id: str, top_k: int = 5) -> list[dict]:
    """审稿取证：向量优先，FTS 补充，返回 [{material_id, score|snippet}]。"""
    out: list[dict] = []
    seen: set[str] = set()
    snips = dao.search_materials_fts(claim[:20], top_k, article_id)
    for mid, score in semantic_search(claim, article_id, top_k):
        seen.add(mid)
        snip = next((s for i, s in snips if i == mid), "")
        out.append({"material_id": mid, "score": round(score, 4), "snippet": snip})
    if len(out) < top_k:
        for mid, snip in text_search(claim[:30], top_k - len(out), article_id):
            if mid not in seen:
                out.append({"material_id": mid, "score": None, "snippet": snip})
    return out[:top_k]
