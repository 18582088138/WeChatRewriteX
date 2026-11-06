"""Project audio use cases: independent drafts, immutable batches, bounded billing."""
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import time
from fastapi import HTTPException
from ..storage import db, dao, audio_store as store
from ..core import config, events
from . import team, draft_service
from .audio_models import SpeechDoc, Paragraph, VoiceSettings, Limits


from .audio_models import Mix
from . import audio_text


def uid():
    return secrets.token_hex(16)


def digest(value):
    return hashlib.sha256(store.dumps(value).encode()).hexdigest()


def project(aid, capability='read'):
    team.require(aid, capability)
    if not dao.get_article(aid):
        raise HTTPException(404, '项目不存在')


def product(aid):
    project(aid)
    row = db.query_one("SELECT * FROM media_products WHERE article_id=? AND kind='speech'", (aid,))
    if not row:
        raise HTTPException(404, '请先从图文派生口播稿')
    return row, SpeechDoc.model_validate_json(row['doc_json'])


def check_revision(row, revision):
    if row['revision'] != revision:
        raise draft_service.VersionConflict('口播稿已更新；保留本地输入，刷新核对后重试')


def source(aid):
    try:
        doc, _ = draft_service.get_doc(aid)
        return doc, draft_service.content_hash(doc)
    except ValueError:
        return None, ''


def source_stale(aid, doc):
    _, current = source(aid)
    return bool(doc.source_hash and current != (doc.source_confirmed_hash or doc.source_hash))


def script_hash(doc):
    citations = {mid for p in doc.paragraphs for mid in p.citations}
    evidence = {mid: {k:v for k,v in (dao.get_material(mid) or {}).items() if k not in ('path','created_at')}
                for mid in citations}
    return digest({'title': doc.title, 'brief': doc.brief.model_dump(),
                   'paragraphs': [p.model_dump() for p in doc.paragraphs],
                   'source_hash': doc.source_hash, 'source_confirmed_hash': doc.source_confirmed_hash, 'evidence': evidence})


def normalize(doc):
    if doc.voice != VoiceSettings():
        raise ValueError('此阶段尚未开放声音设置')
    if doc.mix != Mix() or doc.dictionary or any(p.pause_ms != 300 for p in doc.paragraphs):
        raise ValueError('词典、停顿与混音在 S7 开放')
    ids = [p.id for p in doc.paragraphs]
    if len(ids) != len(set(ids)):
        raise ValueError('段落 ID 不可重复')
    if sum(len(p.text) + len(p.speech_text) for p in doc.paragraphs) > 40000:
        raise ValueError('口播稿总长度超过上限')
    for p in doc.paragraphs:
        if not p.manual_speech:
            p.speech_text = audio_text.pronounce(p.text, {}, doc.brief.language)
        if '<' in p.speech_text or '>' in p.speech_text:
            raise ValueError('当前不支持 SSML/情绪标签；请使用纯文本和段间停顿')
    return doc


def save(aid, revision, doc, deriving=False):
    with db.transaction():
        project(aid, 'write')
        row = db.query_one("SELECT * FROM media_products WHERE article_id=? AND kind='speech'", (aid,))
        if row:
            check_revision(row, revision)
            old = SpeechDoc.model_validate_json(row['doc_json'])
            if not deriving:
                # Source binding and rule version are server-owned.
                for key in ('source_hash', 'source_version', 'source_revision', 'source_confirmed_hash', 'rules_version'):
                    setattr(doc, key, getattr(old, key))
        elif revision != 0:
            raise draft_service.VersionConflict('口播稿尚未创建')
        if not row and not deriving:
            current, fingerprint = source(aid)
            doc.source_hash = fingerprint
            doc.source_version = current.version if current else None
            doc.source_revision = current.edit_revision if current else None
            doc.source_confirmed_hash = ''
            doc.rules_version = 'speech-rules-1'
        doc = normalize(doc)
        if not deriving:
            current_source,_ = source(aid)
            allowed_blocks = {b.id for b in current_source.blocks} if current_source else set()
            if row:
                allowed_blocks.update(bid for p in old.paragraphs for bid in p.source_block_ids)
            if any(bid not in allowed_blocks for p in doc.paragraphs for bid in p.source_block_ids):
                raise ValueError('口播来源位置不属于本项目的图文/已保存来源，请重新派生或保留为空并人工核对')
        validate_references(aid, doc)
        pid, next_rev = (row['id'], row['revision'] + 1) if row else (uid(), 1)
        text = doc.model_dump_json()
        now = time.time()
        db.execute('INSERT INTO media_products VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,doc_json=excluded.doc_json',
                   (pid, aid, 'speech', next_rev, text, now))
        db.execute('INSERT INTO media_versions VALUES(?,?,?,?,?)',
                   (pid, next_rev, text, (team.actor.get() or {}).get('id'), now))
        team.audit('speech.save', pid, aid, {'revision': next_rev})
        db.after_commit(lambda: events.bus.publish('audio.updated', aid, revision=next_rev))
    return get(aid)


def validate_references(aid, doc):
    for p in doc.paragraphs:
        for mid in p.citations:
            material = dao.get_material(mid)
            if not material or (material['scope'] == 'article' and material['article_id'] != aid):
                raise HTTPException(404, '引用素材不属于本项目')
            if team.enabled() and not team.material_allowed(team.actor.get(), material):
                raise HTTPException(404, '引用素材没有授权')


def derive(aid, request):
    project(aid, 'write')
    current, fingerprint = source(aid)
    if not current:
        raise ValueError('需要先保存图文稿再派生口播')
    paragraphs = []
    for block in current.blocks:
        if block.type.value in ('paragraph', 'quote', 'heading') and block.text.strip():
            # Conservative extraction preserves facts; segment at sentence boundaries.
            import re
            sentences = re.split(r'(?<=[。！？.!?])\s*', audio_text.clean(block.text))
            chunk = ''
            for sentence in sentences:
                if len(chunk) + len(sentence) > 350 and chunk:
                    paragraphs.append(Paragraph(id=uid(), text=chunk, speech_text='', source_block_ids=[block.id], citations=block.citations))
                    chunk = ''
                chunk += sentence
            if chunk:
                paragraphs.append(Paragraph(id=uid(), text=chunk, speech_text='', source_block_ids=[block.id], citations=block.citations))
    doc = SpeechDoc(title=dao.get_article(aid)['title'], brief=request.brief, paragraphs=paragraphs,
                    source_hash=fingerprint, source_version=current.version, source_revision=current.edit_revision)
    existing = db.query_one("SELECT doc_json FROM media_products WHERE article_id=? AND kind='speech'", (aid,))
    if existing:
        old = SpeechDoc.model_validate_json(existing['doc_json'])
        doc.voice, doc.mix, doc.dictionary = old.voice, old.mix, old.dictionary
    if request.use_llm:
        from .llm.router import complete
        from pydantic import BaseModel, Field
        class SpokenResult(BaseModel):
            paragraphs: list[Paragraph] = Field(max_length=80)
        result = complete('rewrite', [
            {'role': 'system', 'content': '将图文改为单人口播：开场、事实、解释、结尾。缩短长句，去除引用标记；不得增加无依据事实，不得改变数值。保留输入段落id和source_block_ids/citations，只改text，speech_text填空。输出JSON paragraphs。'},
            {'role': 'user', 'content': store.dumps({'brief': request.brief.model_dump(), 'paragraphs': [p.model_dump() for p in paragraphs]})}
        ], schema=SpokenResult, article_id=aid, stage='speech_derive')
        output = result.parsed.paragraphs
        old_map = {p.id: p for p in paragraphs}
        if {p.id for p in output} != set(old_map) or len(output) != len(paragraphs):
            raise ValueError('AI 改变段落来源结构，结果未保存')
        import re
        for p in output:
            original = old_map[p.id]
            if re.findall(r'\d+(?:\.\d+)?', p.text) != re.findall(r'\d+(?:\.\d+)?', original.text):
                raise ValueError('AI 改变关键数字，结果未保存；请使用保守派生并人工编辑')
            p.source_block_ids, p.citations, p.manual_speech = original.source_block_ids, original.citations, False
        doc.paragraphs = output
    if source(aid)[1] != fingerprint:
        raise draft_service.VersionConflict('图文在派生期间已改变，请重新派生')
    return save(aid, request.revision, doc, deriving=True)


def rewrite(aid, request):
    row, doc = product(aid)
    check_revision(row, request.revision)
    paragraph = next((p for p in doc.paragraphs if p.id == request.paragraph_id), None)
    if not paragraph:
        raise HTTPException(404, '目标段落不存在')
    from .llm.router import complete
    from pydantic import BaseModel
    class Result(BaseModel):
        text: str
    result = complete('rewrite', [
        {'role': 'system', 'content': '只重写目标口播段落，保留全部关键事实和数值，不添加事实。输出JSON text。'},
        {'role': 'user', 'content': store.dumps({'text': paragraph.text, 'instruction': request.instruction})}
    ], schema=Result, article_id=aid, stage='speech_rewrite')
    import re
    if re.findall(r'\d+(?:\.\d+)?', result.parsed.text) != re.findall(r'\d+(?:\.\d+)?', paragraph.text):
        raise ValueError('AI 改变关键数字，结果未保存')
    paragraph.text, paragraph.manual_speech = result.parsed.text, False
    return save(aid, request.revision, doc)


def get(aid):
    project(aid)
    row = db.query_one("SELECT * FROM media_products WHERE article_id=? AND kind='speech'", (aid,))
    state = {'product': None, 'voices': [], 'batches': [], 'reviews': [],
             'features': {'reviews': False, 'mix': False, 'subtitles': False}}
    if row:
        doc = SpeechDoc.model_validate_json(row['doc_json'])
        state['product'] = {'id': row['id'], 'revision': row['revision'], 'doc': doc.model_dump(),
                            'source_stale': source_stale(aid, doc)}
        state['rules_review'] = audio_text.review(doc)
    return state


def history(aid):
    row, _ = product(aid)
    return [{'revision': r['revision'], 'editor_id': r['editor_id'], 'created_at': r['created_at'], 'doc': json.loads(r['doc_json'])}
            for r in db.query('SELECT * FROM media_versions WHERE product_id=? ORDER BY revision DESC', (row['id'],))]


def confirm_source(aid, revision):
    with db.transaction():
        row, doc = product(aid); check_revision(row, revision)
        doc.source_confirmed_hash = source(aid)[1]
        return save(aid, revision, doc, deriving=True)
