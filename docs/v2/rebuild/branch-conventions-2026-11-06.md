# S10 V2 分支整理与 commit 复验

日期：2026-11-06。用户以【更新规则】要求只推送最终开发分支，step 保持本地；最终分支命名 `dev/v2-audio`，本地 step 命名 `dev/v2-audio-s<N>-<purpose>`。本轮仅管理 V2 分支，V1.0+ 和更早版本的本地/远端分支及标签不动。

## 规则与开发基线

规则直接在 main 修改、验证并提交/推送 `cc6e844`，只变更 `AGENTS.md` 和 `.cursor/rules/staged-development.mdc`。V2 通过 `57e80a9` 合入新 main 规则，V2 功能没有合入 main。

本次文档/分支整理在本地 `dev/v2-audio-s10-branch-conventions` 开发，验证后以一个 `docs(audio S10): document V2 branch names and commit-based verification` commit 快进集成到 `dev/v2-audio`；只推送最终分支。已交付 S0～S9 的源码、修正和证据多提交历史保留，不通过本次更名改写；后续阶段如有多个本地中间提交，按 step squash 成一个集成 commit。

## 分支范围与结果

- 最终分支：本地 `codex/v2-rebuild` 更名为 `dev/v2-audio`，先推送新最终分支，再核对完整阶段祖先及远端 HEAD 后删除旧远端名称。
- S0～S9：本地 `codex/v2-rebuild-s<N>-<purpose>` 更名为 `dev/v2-audio-s<N>-<purpose>`，每份原完成 commit 保持不变，移除旧 upstream；旧远端 10 个 step 名称删除，不推送新 step 名称。
- 两条 V2 临时别名 `codex/development-docs-s1-handoff`、`codex/repository-s1-cleanup` 已确认包含于最终分支历史，删除其本地/远端分支引用，原 commit 保留。
- 不管理旧版本分支，不创建每个 step 的远端分支或标签替代品；远端 V2 只保留最终 `dev/v2-audio`。

原分支名仍出现在早先执行证据中，表示历史事实；当前入口与本地检查点名称已同步到各阶段文档和 [commit 清单](commits.md)。

## 拉取与复验

先拉取 `dev/v2-audio`，再使用 commit 清单指定阶段的完成 commit（例：S3 `20e5a5d`）：

```powershell
git fetch origin dev/v2-audio
git switch --detach 20e5a5d
```

检出前先保存未提交改动。完成后 `git switch dev/v2-audio` 返回当前开发版本；按各阶段文档执行当时的验证命令。完成 commit 带当时源码和验证文档，实际测试源码另列；二者的 `app/`、`web/src/`、`tests/` 已逐阶段核对无差异。远端 step 分支删除后，这些 commit 仍是最终分支祖先，可正常获取。

## 验证、数据和回退

- 规则/文档差异与本地 Markdown 链接检查通过；本地 10 个完成检查点 SHA 与更名前相同，全部属于最终分支祖先。
- 新最终分支推送后核对远端 HEAD；远端不再有旧 V2 集成/step/临时别名，也没有新 `dev/v2-audio-s*` 分支。较早版本的分支与标签引用前后逐份核对不变。
- 本轮业务源码/前端/测试相对程序构建 `87f3004` 无差异，仅更新规则/文档/分支引用；不重复业务回归，不新增真实 API、声音克隆或用户数据操作。
- Windows rc.2 随包文档同步并重新核验 CRC/SHA256，程序 manifest 仍固定 `87f3004`。本机去敏验证记录位于忽略的 `build/v2-rebuild-evidence/branch-rename-plan.json`、`branch-conventions-final.json`、`documentation-links.json`、`artifacts-rc2-final.json`。
- 回退可按原 commit 从最终分支历史恢复，分支引用可重新创建；不要因回退恢复持续推送 step 分支。V2 仍待用户验收并决定是否合入 main，真人长音频及实际设备验收继续保留。

文档用途与验收目录见 [V2 README](../README.md)。
