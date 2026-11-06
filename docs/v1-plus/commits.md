# V1.0+ 阶段源码与集成commit清单

2026-11-06核对：11条原远端阶段分支末端全部属于`dev/v1-plus`和main历史。多提交/merge历史保留，不事后squash或伪造阶段。下列为Git事实；历史验证的命令、环境与范围以阶段记录为准，不保证每次旧测试都有精确源码SHA记录。

## 原阶段与后续补验

- **S0**：本地`dev/v1-plus-s0`末端`e47ff09`，前置设计`430d184`，集成`1a54ae8`。[记录](S0-acceptance.md)。主要为基线、设备与设计文档，没有成员功能实现。
- **S1**：本地`dev/v1-plus-s1`实现/末端`58d5d01`，集成`437d45b`。[记录](S1-acceptance.md)。
- **S2**：原主体实现`d811584`，原集成`bf2028a`；后来补充独立验收，本地`dev/v1-plus-s2`末端变为`dcc7e8b`，通过`7b02575`合入S7历史。后补末端不是原实现提交。[记录](S2-acceptance.md)。S2复验可检出`dcc7e8b`，主体差异查看`d811584`。
- **S3**：本地`dev/v1-plus-s3`实现/末端`86ae545`，集成`d740d3b`。[记录](S3-acceptance.md)。
- **S4**：本地`dev/v1-plus-s4`实现/末端`cca5b2c`，集成`696bcc8`。[记录](S4-acceptance.md)。
- **S5**：本地`dev/v1-plus-s5`实现/末端`60d1459`，集成`4e8b7ee`。[记录](S5-acceptance.md)。
- **S6**：本地`dev/v1-plus-s6`实现/末端`c6d44c0`，集成`706ca30`。[记录](S6-acceptance.md)。
- **S7**：主体`052c46c`，后续修复/打包验证保留多个提交；本地`dev/v1-plus-s7`末端`e593860`，集成`2be37d6`。原候选运行源码`cf40afa`，家庭机重建程序源码`2be37d6`；文档末端不等于exe重建来源。[记录](S7-acceptance.md)、[家庭复验](home-validation-2026-10-31.md)。
- **部署补验**：本地`dev/v1-plus-s7-deployment-validation`，维护修复`97ad216`，末端`646cb12`，集成`21cb648`。[交接](NUC-validation-followup-2026-10-31.md)。
- **验收工具**：本地`dev/v1-plus-s7-nuc-acceptance-kit`，实现`5143b6d`及后续修复，末端`bbadf87`，集成`91c9009`。[工具自验](validation/KIT-VALIDATION.md)。
- **NUC反馈**：直接提交`c54006a`、`0099696`；run源码`91c9009`，NUC exe源码`2be37d6`。[报告](validation/runs/nuc-20261101-01/report.md)。
- **公司复核**：本地`dev/v1-plus-s7-nuc-review`末端`8e0fbd5`，集成`52e0ae9`。[复核](validation/runs/nuc-20261101-01/evidence/company-review-20261101.md)。
- **合入main**：约定更新`c6d6ee9`，合并`215f262`；正式标签/安装包不变。
- **S8整理**：基线`cc6e844`，本地`dev/v1-plus-s8-branch-cleanup`；本文件和整理记录在同一个S8提交中，快进集成到`dev/v1-plus`，step末端与集成SHA相同。用`git log --all --grep='docs(v1-plus S8):'`定位唯一集成commit，不用后补空提交把SHA写入自身。[整理记录](branch-cleanup-2026-11-06.md)。

## 另一台机器按commit复验

先保存未提交改动，再执行：

```powershell
git fetch origin dev/v1-plus
git switch --detach dcc7e8b
# 按S2记录在独立测试数据目录验证
git switch dev/v1-plus
git merge --ff-only origin/dev/v1-plus
```

其他阶段替换为上列末端或集成commit。每次新测试记录实际HEAD、环境、命令与结果；历史源码不得连接已升级的唯一真实数据库。NUC固定run继续按[验收入口](validation/START-HERE.md)执行，源码/标准改变则新建run。

后续使用本地`dev/v1-plus-s<N>-<purpose>`，每step一个集成commit，只推送`dev/v1-plus`。S0～S7旧多提交历史保留，删除远端名称不会丢失其中源码。
