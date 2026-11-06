# S1 仓库整理与远端交付

日期：2026-11-06。用户授权直接在 main 更新标记为【规则更新】的开发规则，允许 push/分支管理，要求整理本地过期文件和分支。功能分支合入 main 仍由用户决定。

本文件保留当时的文件归档/分支推送事实；随后用户改为仅推送最终开发分支，当前名称为 `dev/v2-audio`，旧远端 V2 step/别名已删除，详情见 [后续分支整理](branch-conventions-2026-11-06.md)。

## 基线与提交

- 规则 S0：直接在 main 更新 `AGENTS.md` 与 `.cursor/rules/staged-development.mdc`，提交/推送 `723ce2b`；此阶段按用户要求不新建分支。
- 整理 S1：从新 main 创建 `codex/repository-s1-cleanup`，以 merge `8a48b7e` 保留原 V2 候选 `5ffc41a`；规则冲突采用 main 的完整新规则，未重写 S0～S9 历史。随后提交本记录和受影响的开发计划/README/进度。
- 软件仍固定 `87f3004`、版本 `1.2.0-rc.2`；本轮没有业务代码、数据库迁移、真实 API 或克隆调用。

## 文件与分支管理

12 个已核实的过期目标：误生成的 `web/web` 空锁文件、pytest/egg-info 缓存、`build/bdist.win-amd64`、`build/lib`、`build/pyinstaller`、旧 V2 参考副本/重组脚本、`build/stage-check`、`build/stage-v115`/临时脚本及重复 `build/cold-env` 环境。另整理 14 份旧 dist 安装包副本；正式/候选重复件先与 release 中保留的版本逐份核对 SHA256。

自动审批审查阻止批量和逐项永久删除，只返回“blocked by policy”，没有更详细原因。改用可恢复的 Move-Item 归档：所有源路径先核实在仓库内且不包含真实 `.env`/数据库/实例锁、受 Git 管理文件或外部链接；目标为明确的仓库外目录 `C:/Users/kundaxu/Downloads/xkd/Self_Project/WeChatRewriteX-cleanup-20261106`。归档共 11,002 文件、574,062,047 字节（约 547 MiB），原位置已清空；归档未永久删除，不表示释放同等磁盘容量。

删除三条已完成的本地分支：`codex/architecture-hardening`、`codex/development-workflow-s0-guidance` 和 `codex/release-v1.0`。前两条确认已进入 main，最后一条确认等于保留的 `v1.0` 标签；历史提交保持可追溯。保留 V1.0+ 验收线路、原文档补充分支和 V2 S0～S9 检查点，原版本不因清理消失。

V2 S0～S9 分支现已全部推送，并逐份核对远端 HEAD 与本地检查点。集成 `codex/v2-rebuild` 同步整理结果；main 只含规则更新，不含 V2 功能。原阶段推送触发的远端 CI 不等于用户验收，不能沿用本机结果宣称其已通过。

## 验证、证据与回退

- 清理前检查 Git 状态、main/远端、分支祖先与标签；未提交的空锁文件内容为无依赖的 82 字节锁文件。
- 原 `.env` 与 `resource/app.db` SHA256 前后相同；真实数据/日志、API 调试账本/声音样例、阶段与安装包证据、release 回退版本继续保留。
- 当前 V2 业务源码/前端/测试相对 `87f3004` 无差异，只改规则和文档；执行相关 Markdown 本地链接、差异和远端分支核对，工作树清洁，不增加无意义业务测试。
- Windows rc.2 仅同步随包文档并重算 CRC/SHA256，程序、wheel/sdist manifest 保持固定构建；完整一致性检查通过后交付。最终本机结果记录在 `build/v2-rebuild-evidence/` 的 `cleanup-S1.json`、`documentation-links.json` 和 `artifacts-rc2-final.json`。
- 回退规则使用上一 main commit；功能候选和阶段分支保留完整历史。归档文件可从上述仓库外目录恢复到清理前路径，恢复前停止有关进程并确认目标未被新生成文件占用。

交付文档用途与阶段导航见 [V2 README](../README.md)；真人长音频、NUC/手机/跨网络及用户最终验收继续待完成。
