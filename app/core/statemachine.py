"""任务状态机，见 docs/design/02。非法迁移直接抛错，杜绝状态漂移。"""
from __future__ import annotations

from .models import ArticleStatus, UI_STATUS


class InvalidTransition(Exception):
    pass


TRANSITIONS: dict[ArticleStatus, set[ArticleStatus]] = {
    ArticleStatus.NEW: {ArticleStatus.COLLECTING},
    ArticleStatus.COLLECTING: {ArticleStatus.COLLECTED, ArticleStatus.FAILED},
    ArticleStatus.COLLECTED: {ArticleStatus.CREATING, ArticleStatus.COLLECTING},   # 允许补收集
    ArticleStatus.CREATING: {ArticleStatus.DRAFTED, ArticleStatus.FAILED},
    ArticleStatus.DRAFTED: {ArticleStatus.REVIEWING, ArticleStatus.CREATING},
    ArticleStatus.REVIEWING: {ArticleStatus.REVIEWED, ArticleStatus.FAILED},
    ArticleStatus.REVIEWED: {ArticleStatus.EDITING, ArticleStatus.FINALIZED},
    ArticleStatus.EDITING: {ArticleStatus.REVIEWING, ArticleStatus.FINALIZED,
                            ArticleStatus.CREATING},   # 编辑后可整篇重写
    ArticleStatus.FINALIZED: {ArticleStatus.PUBLISHING, ArticleStatus.DONE,
                              ArticleStatus.EDITING, ArticleStatus.REVIEWING},
    ArticleStatus.PUBLISHING: {ArticleStatus.DONE, ArticleStatus.FAILED},
    ArticleStatus.DONE: {ArticleStatus.EDITING},          # 允许回炉
    ArticleStatus.FAILED: {ArticleStatus.NEW, ArticleStatus.COLLECTING, ArticleStatus.CREATING, ArticleStatus.REVIEWING},
}


def can_transition(src: ArticleStatus, dst: ArticleStatus) -> bool:
    return dst in TRANSITIONS.get(src, set())


def transition(src: ArticleStatus, dst: ArticleStatus) -> ArticleStatus:
    if not can_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} 不是合法迁移")
    return dst


def ui_status(status: ArticleStatus) -> str:
    return UI_STATUS[status]
