# V1.0+ 文档与验收入口

最终开发分支为`dev/v1-plus`。候选已于2026-11-05合入main；完整团队验收仍未通过：8项范围复核接受、L02失败、9项待实测。源码集成、等价环境测试、真实部署和外地成员验收分别记录。

## 开发与源码检查点

- [开发计划](../dev-plan-v1-plus.md)：功能范围、依赖和当前分支规则。
- [阶段commit清单](commits.md)：实际实现、原阶段末端、集成提交和按commit复验方法。
- [S8分支整理记录](branch-cleanup-2026-11-06.md)：规则同步、清理范围、验证与回退。
- 原始阶段记录：[S0](S0-acceptance.md)、[S1](S1-acceptance.md)、[S2](S2-acceptance.md)、[S3](S3-acceptance.md)、[S4](S4-acceptance.md)、[S5](S5-acceptance.md)、[S6](S6-acceptance.md)、[S7](S7-acceptance.md)。旧分支名称、main状态及验证结果保留为历史事实，当前管理方式以S8记录为准。

## 使用、部署与维护

- [团队手册](user-guide.md)：账号、授权、人工批准及导出。
- [S0设计](S0-design.md)、[API约定](api-contract.md)：角色、自审与共享边界。
- [S1运维](S1-operations.md)、[S6部署维护](S6-operations.md)：持久运行目录、计划任务、备份恢复和维护权限。
- [候选发布说明](../release/V1.1.0-rc.1.md)、[版本规范](../release/VERSIONING.md)、[产物清单](../release/ARTIFACTS.md)：版本、实际构建和安装包；整理分支不会重建安装包。

## NUC实测与两机同步

- [统一验收入口](validation/START-HERE.md)、[逐项标准](validation/CASEBOOK.md)、[当前状态](validation/STATUS.md)：真实测试步骤与门槛。
- [证据模板](validation/EVIDENCE-TEMPLATE.md)、[诊断说明](validation/DIAGNOSTICS.md)：需传回的信息与问题定位。
- [当前run报告](validation/runs/nuc-20261101-01/report.md)、[公司复核](validation/runs/nuc-20261101-01/evidence/company-review-20261101.md)、[最新交接](validation/runs/nuc-20261101-01/evidence/handoff-20261101-02.md)：已实测范围与缺项。固定run源码`91c9009`不因分支整理改变，不覆盖原始证据。
- [家庭开发机复验](home-validation-2026-10-31.md)、[后续补验交接](NUC-validation-followup-2026-10-31.md)、[工具自验](validation/KIT-VALIDATION.md)：历史等价环境范围，不能代替真实手机、外地成员和长期试用。
