"""素材检索：FTS5 全文（always）+ 向量语义（embedding 可用时）。

用途：洗稿选图/取证、审稿 claims 找证据、撞稿语义比对。
向量存 embeddings 表（float32 blob），维度与配置不一致的存量自动重建。
"""
from __future__ import annotations

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
    want_dim = int((config.get("llm.embedding") or {}).get("dimension", 0))
    todo: list[tuple[str, str]] = []
    for mid, content in pairs:
        if not content.strip():
            continue
        row = db.query_one("SELECT dim FROM embeddings WHERE material_id=?", (mid,))
        if row and (not want_dim or row["dim"] == want_dim):
            continue
        todo.append((mid, content[:2000]))   # 截断控制成本
    count = 0
    for i in range(0, len(todo), 32):
        batch = todo[i:i + 32]
        try:
            vecs = emb.embed([c for _, c in batch])
        except Exception:
            break
        for (mid, _), vec in zip(batch, vecs):
            db.execute(
                "INSERT OR REPLACE INTO embeddings(material_id,dim,vector) VALUES(?,?,?)",
                (mid, len(vec), pack_vector(vec)))
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
            "WHERE m.article_id=? OR m.scope='common'", (article_id,))
    else:
        rows = db.query("SELECT material_id, vector FROM embeddings")
    scored = [(r["material_id"], cosine(qv, unpack_vector(r["vector"]))) for r in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def text_search(query: str, limit: int = 10) -> list[tuple[str, str]]:
    """全文检索，返回 (material_id, snippet)。"""
    return dao.search_materials_fts(query, limit)


def evidence_for_claim(claim: str, article_id: str, top_k: int = 5) -> list[dict]:
    """审稿取证：向量优先，FTS 补充，返回 [{material_id, score|snippet}]。"""
    out: list[dict] = []
    seen: set[str] = set()
    for mid, score in semantic_search(claim, article_id, top_k):
        seen.add(mid)
        snips = dao.search_materials_fts(claim[:20], 3)
        snip = next((s for i, s in snips if i == mid), "")
        out.append({"material_id": mid, "score": round(score, 4), "snippet": snip})
    if len(out) < top_k:
        for mid, snip in text_search(claim[:30], top_k - len(out)):
            if mid not in seen:
                out.append({"material_id": mid, "score": None, "snippet": snip})
    return out[:top_k]
