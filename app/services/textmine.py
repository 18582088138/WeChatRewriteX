"""纯规则的主题/报道主体/关键词抽取（不调 LLM，零成本）。

策略：
- 候选词四类：标题分句、英文/型号 token（GLM-5.5、H800、Roadster）、「」引号词、实体词典命中；
- 打分：标题出现 ×3 + 正文词频 + 实体词典加成 + 长度惩罚（太短/太长扣分）；
- topic 用原文章标题（最稳的主题载体），keywords 取 Top 5~8；
- core_points 用「含数字 + 含关键词」的高分句；entities = 英文 token + 词典命中 + 引号词。
"""
from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

# AI 产业常见实体词典（可持续补充；命中即在标题/正文加权）
_ENTITY_DICT = {
    "特斯拉", "比亚迪", "华为", "小米", "苹果", "谷歌", "微软", "亚马逊", "英伟达", "台积电",
    "三星", "高通", "英特尔", "中芯国际", "宁德时代", "京东", "美团", "阿里", "腾讯", "字节",
    "百度", "网易", "快手", "智谱", "月之暗面", "MiniMax", "零一万物", "百川", "商汤", "旷视",
    "OpenAI", "DeepSeek", "Anthropic", "Meta", "Google", "Microsoft", "Amazon", "NVIDIA",
    "Apple", "Tesla", "AMD", "Intel", "Qualcomm", "TSMC", "Samsung", "xAI", "Mistral",
    "Kimi", "Qwen", "Llama", "Claude", "Gemini", "GPT", "Sora", "Copilot", "Grok",
    "GLM", "Vidu", "可灵", "即梦", "文心", "通义", "混元", "豆包", "讯飞", "Manus",
    "Roadster", "Cybertruck", "FSD", "Optimus", "B200", "H100", "H200", "B300",
}

_PUNCT = re.compile(r"[，。！？；：、（）()【】\[\]—…·,.!?;:\"\s]+")
_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9.+\-_/]{1,24}")
_QUOTED = re.compile(r"「([^」]{2,20})」")
_SENTENCE = re.compile(r"[^。！？!?\n]{12,160}[。！？!?]?")
_URL = re.compile(r"https?://[^\s)\]]+")

_TOKEN_STOP = {"https", "http", "www", "com", "cn", "net", "org", "from", "appmsg",
               "wx_fmt", "jpeg", "jpg", "png", "gif", "webp", "bmp", "mp4", "svg",
               "mmbiz", "qpic", "the", "and", "for", "with", "this", "that", "you",
               "are", "not", "but", "all", "can", "has", "was", "his", "her", "its",
               "our", "out", "use", "new", "who", "how", "what", "when", "where",
               "which", "will", "would", "could", "should"}


def _is_noise_token(tok: str) -> bool:
    t = tok.lower()
    if t in _TOKEN_STOP:
        return True
    if tok.isdigit():
        return True
    # CDN 哈希型长乱码（大小写数字混杂 ≥16）
    if len(tok) >= 16 and re.search(r"\d", tok) and re.search(r"[a-z]", tok) \
            and re.search(r"[A-Z]", tok):
        return True
    return False


class TopicGuess(BaseModel):
    topic: str = ""
    keywords: list[str] = Field(default_factory=list)
    core_points: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    foundational_queries: list[str] = Field(default_factory=list)


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def extract_topic_rules(title: str, markdown: str, max_keywords: int = 8) -> TopicGuess:
    text = _URL.sub(" ", markdown or "")   # 去图片/链接 URL，防 CDN token 污染
    title = (title or "").strip()

    # ---- 候选词收集 ----
    scores: Counter = Counter()

    # 1) 标题分句（最强信号：标题就是作者提炼的主题）
    for seg in _PUNCT.split(title):
        seg = seg.strip()
        if 2 <= len(_norm(seg)) <= 16 and not _is_noise_token(seg):
            scores[seg] += 3.0

    # 2) 英文/型号 token（参数、型号、专有名词高发区）
    en_counts: Counter = Counter(t for t in _EN_TOKEN.findall(text)
                                 if not _is_noise_token(t))
    for tok, c in en_counts.items():
        if len(tok) < 2:
            continue
        # 型号感：含数字或大写连写
        bonus = 1.0 if (re.search(r"\d", tok) or tok.isupper()) else 0.4
        scores[tok] += min(c, 8) * 0.6 * bonus
        if tok in title:
            scores[tok] += 2.0

    # 3) 「」引号词（作者强调的概念）
    for q, c in Counter(_QUOTED.findall(text)).items():
        if 2 <= len(q) <= 20:
            scores[q] += min(c, 5) * 0.8 + (2.0 if q in title else 0)

    # 4) 实体词典命中（标题命中重加权）
    for ent in _ENTITY_DICT:
        ent_n = _norm(ent)
        if not ent_n:
            continue
        in_title = ent.lower() in title.lower() or ent_n in title
        c_text = text.count(ent) + text.count(ent_n)
        if in_title or c_text:
            scores[ent] += (4.0 if in_title else 0) + min(c_text, 10) * 0.7

    # 长度惩罚与停用过滤
    def _keep(term: str) -> bool:
        n = _norm(term)
        if len(n) < 2 or len(n) > 18:
            return False
        if _is_noise_token(term):
            return False
        if re.match(r"^\d", n) and len(n) < 6:   # 「5最新曝光」类标题碎片的短数字头
            return False
        if n in {"我们", "他们", "你们", "这个", "那个", "什么", "怎么", "因为", "所以",
                 "但是", "而且", "如果", "已经", "现在", "今天", "昨天", "明天"}:
            return False
        return True

    ranked = [t for t, _ in sorted(scores.items(), key=lambda x: -x[1]) if _keep(t)]
    # 去重（包含关系：保留长词）
    keywords: list[str] = []
    for t in ranked:
        if any(t != k and t in k for k in keywords):
            continue
        keywords.append(t)
        if len(keywords) >= max_keywords:
            break

    # ---- 报道主体（entities）：英文 token + 词典 + 引号词中的实体性强的 ----
    entities: list[str] = []
    for ent in _ENTITY_DICT:
        if (ent.lower() in title.lower()) or (ent in text) or (_norm(ent) in text):
            entities.append(ent)
    for tok, c in en_counts.most_common(12):
        if len(tok) >= 2 and (re.search(r"\d", tok) or tok[0].isupper()) \
                and tok not in entities and not _is_noise_token(tok):
            entities.append(tok)
    entities = list(dict.fromkeys(entities))[:10]

    # ---- 核心句：含数字 + 含关键词的高分句 ----
    key_set = {k.lower() for k in keywords[:4]}
    sent_scores = []
    for m in _SENTENCE.finditer(text):
        s = m.group(0).strip()
        if len(s) < 12 or len(s) > 160:
            continue
        sc = 0.0
        if re.search(r"\d", s):
            sc += 1.5
        sc += sum(1.0 for k in key_set if k in s.lower())
        if any(w in s for w in ("称", "表示", "宣布", "发布", "披露", "透露")):
            sc += 0.5
        sent_scores.append((sc, s))
    core_points = [s for sc, s in sorted(sent_scores, key=lambda x: -x[0]) if sc >= 2.0][:4]

    # ---- 基础资料查询（论文类线索）----
    foundational: list[str] = []
    if re.search(r"论文|arXiv|arxiv|Transformer|架构|benchmark|基准", text, re.I):
        base = " ".join(keywords[:2]) if keywords else title[:20]
        if base:
            foundational.append(f"{base} 论文")

    return TopicGuess(
        topic=title or " ".join(keywords[:3]),
        keywords=keywords,
        core_points=core_points,
        entities=entities,
        foundational_queries=foundational[:1],
    )
