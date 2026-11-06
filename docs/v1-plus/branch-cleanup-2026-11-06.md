# S8 GitHub V1.0+分支整理

日期：2026-11-06。用户授权按V2方式整理。范围为规则同步、commit复验文档及已集成远端阶段引用清理，不修改功能或验收结果。

## 基线、步骤与提交

开始时工作区干净，当前`dev/v2-audio`。V1.0+远端`215f262`、main`cc6e844`、V2`62ca3b9`。main多4个规则相关提交；先将`dev/v1-plus`快进到`cc6e844`，同步AGENTS.md与规则，不合入V2功能。切换后出现的未跟踪V2浏览器测试输出保留，不暂存/清理。

本地step`dev/v1-plus-s8-branch-cleanup`基于`cc6e844`。必要检查在此基线加本次文档工作区执行；一个`docs(v1-plus S8): ...`提交快进合入最终分支，只推送`dev/v1-plus`。step末端就是集成commit，按[清单](commits.md)命令定位。

先推送最终分支并核对远端HEAD，再按原SHA删除11条阶段引用；删除使用逐引用lease与原子push，远端若有新反馈则拒绝覆盖。本地S0～S7及3条补验检查点保留，取消失效upstream，不推送S8 step。

## 范围与验证

- 删除远端`dev/v1-plus-s0`～`dev/v1-plus-s7`、`dev/v1-plus-s7-deployment-validation`、`dev/v1-plus-s7-nuc-acceptance-kit`、`dev/v1-plus-s7-nuc-review`。名称与原SHA见[commit清单](commits.md)，11个末端全部是最终分支及main祖先。
- 保留最终分支、main、V2、更早版本分支、全部标签/Release、本地待验收检查点和NUC固定run证据。不清理缓存、真实数据、配置、密钥或备份。
- 验证所有列出commit可解析并属于最终历史、文档链接、`git diff --check`及改动范围；业务源码/测试/配置和固定NUC run相对`cc6e844`无差异。只做文档/Git检查，不重新运行业务回归；外部API次数/费用为0。
- 公司Windows开发机使用Python3.12运行本地链接/祖先检查：49个新增文档链接、34个历史commit、11个原阶段末端通过，errors为空；`git diff --check`通过。跟踪改动仅5份交付文档，未跟踪V2测试输出不纳入提交。
- 推送/删除后核对最终HEAD、11条远端引用消失、其他分支/标签SHA不变、本地11个检查点SHA不变。实际输出保存于忽略目录`build/v1-plus-branch-cleanup/`，可用`git ls-remote --heads --tags origin`重新核对。
- 安装包未重建，仍按原manifest/校验清单验收。8项范围接受、L02失败、9项待实测及整体未通过状态不变，不操作NUC数据。

## 回退与交接

文档回退用S8集成commit的revert，在独立step实施；远端名称若需要恢复，可按清单从保留commit创建分支并显式push。不要reset或force-push改写交付历史；Git回退不恢复数据库。

统一入口为[README](README.md)，NUC Agent按[验收入口](validation/START-HERE.md)固定run实测，删远端step分支无需重新安装程序。
