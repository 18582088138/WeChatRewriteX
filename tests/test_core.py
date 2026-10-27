"""核心层单测：状态机 / 块操作 / 查重 / 配置分层。"""
from __future__ import annotations

import pytest

from app.core import blocks as bk
from app.core.models import ArticleStatus, Block, BlockType, DraftDoc, DraftMeta
from app.core.statemachine import InvalidTransition, can_transition, transition, ui_status
from app.services.dedup.similarity import literal_similarity


# ---------- 状态机 ----------

def test_legal_transitions():
    assert transition(ArticleStatus.NEW, ArticleStatus.COLLECTING) == ArticleStatus.COLLECTING
    assert can_transition(ArticleStatus.EDITING, ArticleStatus.FINALIZED)
    assert can_transition(ArticleStatus.REVIEWED, ArticleStatus.FINALIZED)
    assert can_transition(ArticleStatus.FAILED, ArticleStatus.COLLECTING)


def test_illegal_transition_raises():
    with pytest.raises(InvalidTransition):
        transition(ArticleStatus.NEW, ArticleStatus.FINALIZED)
    with pytest.raises(InvalidTransition):
        transition(ArticleStatus.DONE, ArticleStatus.COLLECTING)


def test_ui_status_mapping():
    assert ui_status(ArticleStatus.NEW) == "New"
    assert ui_status(ArticleStatus.CREATING) == "Process"
    assert ui_status(ArticleStatus.FINALIZED) == "Done"


# ---------- 块模型 ----------

def _doc() -> DraftDoc:
    return DraftDoc(
        id="d", article_id="a", version=1,
        blocks=[
            Block(id="b1", type=BlockType.HEADING, level=1, text="标题"),
            Block(id="b2", type=BlockType.PARAGRAPH, text="第一段， fifty 50 words 这里。"),
            Block(id="b3", type=BlockType.IMAGE, asset_id="mat_x", caption="图"),
        ],
        meta=DraftMeta(),
    )


def test_word_count_cjk_and_latin():
    # 5 CJK in "第一段这里"（逗号不计）+ "fifty"+"50"+"words" = 3 latin
    assert bk.word_count("第一段，fifty 50 words 这里。") == 5 + 3


def test_block_ops():
    doc = _doc()
    assert bk.replace_block_text(doc, "b2", "改写后的段落")
    assert bk.get_block(doc, "b2").text == "改写后的段落"
    nb = Block(id="", type=BlockType.PARAGRAPH, text="插入")
    bk.insert_block(doc, "b2", nb)
    assert nb.id and doc.blocks[2].text == "插入"
    assert bk.remove_block(doc, nb.id)
    assert not bk.replace_block_text(doc, "b3", "x")  # 图片块不可改文本


def test_to_markdown_and_changed():
    doc = _doc()
    md = bk.to_markdown(doc)
    assert "# 标题" in md and "![图](asset://mat_x)" in md
    new = doc.model_copy(deep=True)
    bk.replace_block_text(new, "b2", "完全不同的新内容，改动了一段。")
    changed, delta = bk.changed_blocks(doc, new)
    assert changed == 1 and delta >= 0


def test_blocks_from_llm_assigns_ids():
    blocks = bk.blocks_from_llm({"blocks": [
        {"type": "heading", "level": 1, "text": "t"},
        {"type": "paragraph", "text": "p", "citations": ["mat_1"]},
        {"type": "unknown_type", "text": "这是一段正常的正文，带句末标点。"},
    ]})
    assert all(b.id for b in blocks)
    assert blocks[1].citations == ["mat_1"]
    assert blocks[2].type == BlockType.PARAGRAPH


# ---------- 查重 ----------

def test_similarity_identical_and_different():
    a = "星河实验室发布72B多模态模型，在MMMU基准上取得68.4分，较上一代提升12%。"
    assert literal_similarity(a, a)["jaccard"] == pytest.approx(1.0)
    b = "今天天气不错，我们去公园散步，顺便讨论一下晚饭吃什么。"
    sim = literal_similarity(a, b)
    assert sim["jaccard"] < 0.05 and sim["simhash"] < 0.9


def test_similarity_partial_rewrite():
    src = "模型在256张H800上训练了74天，碳排放较上代降低18%，支持128K上下文。"
    copied = "模型在256张H800上训练了74天，碳排放较上代降低18%，支持128K上下文。"
    rewritten = "训练耗时74天、动用256张H800；上下文窗口拉到128K，碳排放还少了近两成。"
    assert literal_similarity(src, copied)["jaccard"] > 0.9
    assert 0.05 < literal_similarity(src, rewritten)["jaccard"] < 0.75


# ---------- 配置分层 ----------

def test_config_layers(tmp_path, monkeypatch):
    from app.core import config
    config.reload()
    assert config.get("collect.search_window_days") == 3
    # DB 覆盖优先于 yaml/默认
    config.set_db_overlay(lambda: {"collect": {"search_window_days": 7}})
    try:
        assert config.get("collect.search_window_days") == 7
    finally:
        config.set_db_overlay(lambda: {})
    assert config.get("collect.search_window_days") == 3


def test_logging_persist_and_levels(tmp_path, monkeypatch):
    """日志标准化：常驻写文件（按日期轮转）、格式含 时间/级别/模块/内容、
    ERROR 档下 INFO 被过滤。"""
    import logging
    from app import logging_setup

    monkeypatch.setattr(logging_setup, "log_dir", lambda: tmp_path)
    logging_setup._logger.handlers.clear()          # 解除幂等，重挂到临时目录
    logging_setup.configure()
    logging_setup.log("info", "普通运行信息")
    logging_setup.log("error", "异常报错内容")
    for h in logging_setup._logger.handlers:
        h.flush()
    content = (tmp_path / "wenshu.log").read_text(encoding="utf-8")
    assert "普通运行信息" in content and "异常报错内容" in content
    assert "[wenshu]" in content and "INFO" in content and "ERROR" in content

    # ERROR 档：INFO 不再落盘
    monkeypatch.setattr(logging_setup, "_level", lambda: logging.ERROR)
    logging_setup._logger.handlers.clear()
    logging_setup.configure()
    logging_setup.log("info", "不该出现的信息")
    logging_setup.log("error", "该出现的错误")
    for h in logging_setup._logger.handlers:
        h.flush()
    content2 = (tmp_path / "wenshu.log").read_text(encoding="utf-8")
    assert "该出现的错误" in content2
    assert "不该出现的信息" not in content2.replace("普通运行信息", "")
    logging_setup._logger.handlers.clear()          # 不影响其他测试
