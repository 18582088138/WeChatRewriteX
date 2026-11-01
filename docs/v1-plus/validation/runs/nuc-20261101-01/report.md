# NUC验收状态：nuc-20261101-01

固定源码：`91c90090515405f6235e31f70a47f64c1851631f`；报告机器：`nuc`；生成时间UTC：2026-11-01T09:24:47.454095+00:00。

reported表示NUC记录；reviewed表示对共享材料的复核记录。工具校验结构和摘要，不会判断手工实验真实发生，也不会授权正式发布。

- local_reported: false
- local_reviewed: false
- remote_reported: false
- remote_reviewed: false
- final_reviewed: false

- **B01 机器、权限、程序与Git基线**：blocked；复核：pending。NUC/磁盘/路径/原数据保护已核对；当前用户S4U任务注册实测0x80070005，服务注册权限缺条件
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/B01.md`，SHA256 `ad5af57ec5fe318ce2a0b3a9a8f42c5ab7e1aa6d4e1592ceee2613a51b803dc7`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/B01-probe.json`，SHA256 `e69b6302e6e72f7883287c2440eba4abb0575b6333fd00a27689d03193c40e58`。
  缺项：主机维护者提供提升的管理员PowerShell操作窗口（约10分钟）；下一步：提升后重跑S4U/Limited权限探针并继续D03；保留本次0x80070005证据。
- **B02 候选SHA256、版本及源码对应关系**：blocked；复核：pending。ZIP SHA/CRC、版本和build commit均实测通过；因B01前置未满足暂不判正式通过
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/B02.md`，SHA256 `635e782c5cb213656285be9ac8d81088d104ad6f6f4205fc864b35c9f3450ec7`。
  缺项：先完成B01所需提升PowerShell权限确认；下一步：B01通过后以本证据重新record B02，无需重构建程序。
- **L01 隔离后端、权限及部署工具回归**：blocked；复核：pending。实际build/155后端/7+3浏览器均通过且无跳过；B02前置未满足
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01.md`，SHA256 `fab2e346de170d3955e8a1ec32ede03e63400ba7e18421444c99d1a67d7ebbb2`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01-build.json`，SHA256 `2c3874088684611391d501b307b65323f7991a0655bbd9be2ec71a53a0ddd769`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01-backend.json`，SHA256 `1125c9acc22c5d3c6a3292c6d6146bd32297b22b3007659cb149bed114e5038f`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01-browser.json`，SHA256 `a94f5abb7109b68d449c3d3e2e9b451c8def0cc5d35ea1e9e1261d9f048af526`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01-team-browser.json`，SHA256 `694992b55b3ebdaaf5cf6a914f91e5dacb9a52b0fc0a0265e7739abbe8f23215`。
  缺项：主机维护者完成B01提升权限确认；下一步：B01/B02补齐后复用本次runner JSON/XML重新record；基线变化则新run重跑。
- **L02 团队真实浏览器闭环及冲突恢复**：failed；复核：pending。额外UI实测发现归档checkbox刷新后与服务端状态不一致，且自审开关无管理员UI
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L02.md`，SHA256 `3d07692f93676cee3c233a461923566f006cf7df6ce897762e185965d52e97bc`。
  缺项：前端Agent修复ProjectAccess归档布尔绑定并补管理员自审开关及回归；下一步：独立分支修复并验证，合入后对新基线新建run；当前run保留failed。
- **D01 真实旧数据完整备份与隔离迁移回退**：blocked；复核：pending。真实schema3原件完整备份、隔离schema6迁移和实际v1.0回退均通过；B02前置未满足
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D01.md`，SHA256 `b14bea1b929d3253e2075269fc54860e12a6a6aec3a88a2681fefb762128dc14`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D01-original-inventory.json`，SHA256 `4f98353f4cd3a46851b9d1213629fbc5730ca7b896ae1d34e30b039bc976472e`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D01-upgraded-inventory.json`，SHA256 `fa2b46522a66e57e1ac7b59834da80a316b2d041b752ec7d694afec58147eeac`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D01-migration.json`，SHA256 `6b780154e7e20d7ad598b035f785c0193fd4b7311678c061cdd0cd3db2720705`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D01-old-read.json`，SHA256 `59c01c69ce8eaddde34eca27a3cefe7b9d919da4c9341e0e36e1b453b4cc72b4`。
  缺项：主机维护者完成B01/B02权限前置；下一步：补齐后以去敏inventory和回退证据重新record；正式数据切换仍需独立维护窗口。
- **D02 独立runtime、三档实际成员和本机业务**：blocked；复核：pending。独立runtime三档账号和完整业务实测通过，项目已归档/额外账号已停用；D01前置未满足
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D02.md`，SHA256 `c52c20d38af2b2e663e6b6f6847c20baea76b095fc3ae93b63ae6b4f74389b3f`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D02-report.json`，SHA256 `08696b34b343eecebf7484aea6934e46285bcbf36d978f682087e1766ac1944f`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D02-database-summary.json`，SHA256 `950d555be4c23dd92cb680fb7dacdad1091a80883f7c3b34f021641168d16934`。
  缺项：先完成B01/B02/D01账本前置；下一步：前置补齐后继续D03；P01密码输入完成后清理剩余验收账号。
- **D03 Windows计划任务和目录权限**：blocked；复核：pending。实际注册脚本返回0x80070005，任务未创建
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D03.md`，SHA256 `6b76381da133ba19ebc97b4f5d643636bb00f7dca1ab0556256ddf3e3f44349e`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D03-register.txt`，SHA256 `63757bf1257b34dcb4eab840272b54e51315f0ae3bec99df05563ebe89c0715f`。
  缺项：主机维护者提供提升的管理员PowerShell窗口（约10分钟）；下一步：提升后注册/启动任务并采集身份、路径、ready和导出证据。
- **D04 退出Windows登录会话后的服务可用性**：blocked；复核：pending。未实际注销，D03也未注册
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D04.md`，SHA256 `8b62358d31ea2c68cc128f8a8c005f4adc90d45f239c2c48782bfeacf4417ab3`。
  缺项：主机维护者完成D03并提供真实注销/再登录窗口（约10分钟）；下一步：按CASEBOOK运行注销后S4U probe并记录人工时间确认。
- **D05 实际主机重启后的自启动和数据一致性**：blocked；复核：pending。未执行主机重启，D03/D06未完成
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D05.md`，SHA256 `bfdf88d8b7719c98904d17f899c8478f622efff8cc878a1a9fd8e638206da29c`。
  缺项：主机维护者提供受控重启窗口（约20分钟），先完成D03/D06；下一步：备份通过后记录running并同步，再由维护者重启并采集启动/数据一致性。
- **D06 实际计划任务离线备份与隔离恢复**：blocked；复核：pending。实际备份脚本因Wenshu-SingleInstance不存在而停止，未开始备份
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D06.md`，SHA256 `a29f9204959b5473a6d3bbbeb8d6eaf0f855652f255c35dec43660fefa0c387a`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D06-backup.txt`，SHA256 `d80cb0a828fe7f496eb7ed14a76aa5c20ea6d9cd288c8502164de626ba3ed85a`。
  缺项：主机维护者完成D03并提供15分钟离线维护窗口；下一步：任务Running后重跑备份脚本并做隔离恢复及故意失败检查。
- **D07 合成任务异常退出、单实例与队列恢复**：blocked；复核：pending。L01同一后端实际执行两个D07子进程恢复测试并通过；B02前置未满足
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/D07.md`，SHA256 `d9b2ee93aa19fba17987fcbd533c7c4bee18d2361be1cc4db764c933afdcddae`。
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/L01-backend.json`，SHA256 `1125c9acc22c5d3c6a3292c6d6146bd32297b22b3007659cb149bed114e5038f`。
  缺项：主机维护者完成B01/B02前置；下一步：前置补齐后复用JUnit XML和runner JSON重新record，不重复计数。
- **P01 三身份真实HTTP基线及资源采样**：blocked；复核：pending。未执行三身份交互密码HTTP探针和资源trace
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/P01.md`，SHA256 `9e9dfff69d44daecf9d3f06dd295d89244430702256a3b4e654d6e029de2898a`。
  缺项：主机维护者在本机交互终端输入三档账号密码并运行60秒probe/trace（约5分钟）；下一步：启动独立实例后按CASEBOOK采集≥100成功读、P95和内存/CPU/磁盘。
- **P02 30～60分钟持续工作负载与队列分段耗时**：blocked；复核：pending。未执行三人30～60分钟持续工作负载
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/P02.md`，SHA256 `1e151c39ad2d06e87e083922eaaa8d8536255d1de22f159515dcb0b763f4ff58`。
  缺项：主机维护者及三档成员提供30～60分钟、10～20主题协作窗口，先完成P01；下一步：并行执行工作负载、HTTP和资源trace，记录队列/模型/渲染分段耗时。
- **R01 私有组网/HTTPS及会话、CSRF、SSE**：blocked；复核：pending。未配置真实跨网络HTTPS/私有组网入口
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/R01.md`，SHA256 `e0c3f41c032470f7b8dc7209f83c77acd418ed9c9db92c7cd0406b72200a26b3`。
  缺项：网络/主机维护者提供上行/NAT/IP、组网/证书选择和另一独立网络，先完成D03；下一步：配置受保护HTTPS并从独立网络验证Cookie/CSRF/SSE/下载/撤权。
- **R02 真实手机及蜂窝网络**：blocked；复核：pending。没有实际手机与蜂窝操作
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/R02.md`，SHA256 `c3ec318d5f2d3c1aaa1e059b5341b893e63ebafa10e2ccea67b189e3f2de7470`。
  缺项：手机持有人提供真实设备、蜂窝和约20分钟窗口，先完成R01；下一步：Wi-Fi/蜂窝分别完成登录、素材、审批、下载和重连并记录操作者确认。
- **R03 外地实际成员完整协作与撤权**：blocked；复核：pending。没有外地真实成员参与
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/R03.md`，SHA256 `551768405de141e589dd6b6933391324a67a5e806ba5cb00e92833bb3399e8c6`。
  缺项：至少一名外地成员及管理员提供另一城市网络和30分钟窗口，先完成R01；下一步：完成跨城协作、冲突和撤权闭环并记录双方确认。
- **R04 另一设备副本及实际RPO/RTO演练**：blocked；复核：pending。仅本机同盘备份恢复，无另一物理设备副本或真实RTO/RPO
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/R04.md`，SHA256 `a2969d3de28bf1a8697dde85f77f57268bba8f812b6c3d99870c495e65229216`。
  缺项：备份维护者提供另一物理设备/异地位置，先完成D06并安排60分钟恢复窗口；下一步：复制并校验真实备份，在独立目录恢复并记录数据量和业务可用时间线。
- **R05 10～20真实主题及3～7自然日试运行**：blocked；复核：pending。未执行10～20真实主题、真实模型质量及3～7自然日试运行
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/R05.md`，SHA256 `fa1b589a8fd04fdb2125b9733db429b36609995ecced21f2b5a022d97934e954`。
  缺项：团队管理员和成员提供真实主题/模型及3～7自然日，先完成P02/R02/R03；下一步：逐日记录用量、失败、质量、资源与备份并由真实成员确认。
- **X01 Docker/Nginx运行（仅选用时）**：not_applicable；复核：pending。选择Windows绿色包+独立runtime+计划任务，未采用Docker/Nginx可选路线
  证据：shared，`docs/v1-plus/validation/runs/nuc-20261101-01/evidence/X01.md`，SHA256 `bfa651fabadb78f19998919c0a04b579e5605a75f920cdf7a777bb1481108b94`。
