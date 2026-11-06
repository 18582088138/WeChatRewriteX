# S0～S9 分支、源码与验证清单

main 规则基线 `bf24cac` 已推送；旧 V2 主体 `cc59842` 不在新系列祖先中。每阶段检查点均实际提交并重新验证；阶段内修正提交及 S5 修正合入 S6 的 merge 保留。

- S0：`codex/v2-rebuild-s0-baseline`；源码 `0f7c99d`；[本次验证](S0.md)。
- S1：`codex/v2-rebuild-s1-products`；源码 `36264b3`；[本次验证](S1.md)。
- S2：`codex/v2-rebuild-s2-speech`；源码 `831cbd5`；[本次验证](S2.md)。
- S3：`codex/v2-rebuild-s3-tts`；源码 `73c7452`；[本次验证](S3.md)。
- S4：`codex/v2-rebuild-s4-batches`；源码 `8fe9628`；[本次验证](S4.md)。
- S5：`codex/v2-rebuild-s5-workbench`；源码 `d372724`；[本次验证](S5.md)。
- S6：`codex/v2-rebuild-s6-approval`；源码 `cc9cff2`；[本次验证](S6.md)。
- S7：`codex/v2-rebuild-s7-mixing`；源码 `65f325e`；[本次验证](S7.md)。
- S8：`codex/v2-rebuild-s8-captions`；源码 `879cb24`；[本次验证](S8.md)。
- S9：`codex/v2-rebuild-s9-delivery`；源码 `74b49ee`；[本次验证](S9.md)。

S9 完整后端 190 项在 `79bfff8` 上通过；图文 7/团队 3 项保留同一轮通过结果。音频浏览器夹具在 `d071e33` 改为两个独立项目；`74b49ee` 再修正稿件、版本或生成状态变化时的过期费用估算，类型检查/构建与音频 2 项重新通过。`79bfff8..74b49ee` 的 `app/` 与后端 `tests/` 无差异；候选包与旧分支清理完成后追加最终交付记录。

所有阶段新增付费/克隆请求为 0；真实环境与用户终审独立待验收。

S9 最终包固定 `87f3004`，wheel/Windows 安装与包一致性通过；后续交付提交只更新文档。集成候选 `codex/v2-rebuild` 保留完整阶段历史，本地 S0～S9 分支继续用于检查与回退。旧集中实现的 `codex/v2-audio` 与 `codex/v2-audio-s3-api-recheck` 已删除，远端没有这两条分支；main 仍为 `bf24cac`。最终包详情见 [S9](S9.md)。
