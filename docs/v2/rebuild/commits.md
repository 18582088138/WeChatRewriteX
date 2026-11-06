# S0～S9 完成 commit 与验证清单

最终开发分支为 `dev/v2-audio`，只推送该分支；下列 step 分支仅保留本地。原开发起点 `bf24cac`、S0～S9 实际源码/验证历史保持不变。指定阶段可先拉取最终分支，再检出阶段完成 commit；不需要远端 step 分支。

阶段完成 commit 包含该阶段当时的源码与验证文档；实际测试的源码 commit 另列，两者在业务源码/前端/测试上无差异。本次只更名分支并整理引用，已有多提交历史未改写；后续每 step 按新规则以一个 commit 集成。

- S0：完成 commit `0e370d5`；实际验证源码 `0f7c99d`；本地 `dev/v2-audio-s0-baseline`；[记录](S0.md)。
- S1：完成 commit `b48ee9e`；实际验证源码 `36264b3`；本地 `dev/v2-audio-s1-products`；[记录](S1.md)。
- S2：完成 commit `3082b8c`；实际验证源码 `831cbd5`；本地 `dev/v2-audio-s2-speech`；[记录](S2.md)。
- S3：完成 commit `20e5a5d`；实际验证源码 `73c7452`；本地 `dev/v2-audio-s3-tts`；[记录](S3.md)。
- S4：完成 commit `dfbb691`；实际验证源码 `8fe9628`；本地 `dev/v2-audio-s4-batches`；[记录](S4.md)。
- S5：完成 commit `ffe7621`；实际验证源码 `d372724`；本地 `dev/v2-audio-s5-workbench`；[记录](S5.md)。
- S6：完成 commit `a21a920`；实际验证源码 `cc9cff2`；本地 `dev/v2-audio-s6-approval`；[记录](S6.md)。
- S7：完成 commit `08f548d`；实际验证源码 `65f325e`；本地 `dev/v2-audio-s7-mixing`；[记录](S7.md)。
- S8：完成 commit `ef19ebb`；实际验证源码 `879cb24`；本地 `dev/v2-audio-s8-captions`；[记录](S8.md)。
- S9：完成 commit `96be673`；实际验证源码 `74b49ee`；本地 `dev/v2-audio-s9-delivery`；[记录](S9.md)。

例如复验 S3（工作树先保存好未提交改动）：

```powershell
git fetch origin dev/v2-audio
git switch --detach 20e5a5d
```

回到当前开发版本：`git switch dev/v2-audio`。阶段测试命令与当时环境、遗留项见各 S 文档；检出旧 commit 不等于真人/设备或用户最终验收通过。

S9 最终程序固定 `87f3004`，完整后端 190 项、图文/团队/音频浏览器 7/3/2 项与安装包检查已有记录。最新 main 仅更新规则 `cc6e844`，V2 功能没有合入 main；原集中实现 `cc59842` 不在当前最终分支祖先中。

本次 S10 文档/分支整理见 [分支规范与复验](branch-conventions-2026-11-06.md)，主目录与各阶段文档用途见 [V2 README](../README.md)。
