# B01 权限补齐（attempt 02）

- 时间：2026-11-01 19:08（Asia/Shanghai）；run/source保持`nuc-20261101-01` / `91c90090515405f6235e31f70a47f64c1851631f`。
- 用户提供提升管理员PowerShell条件后，当前工具会话仍为非提升，故通过Windows UAC启动受控子进程。
- 第一次提升启动返回0xFFFD0000且未进入脚本；第二次进入脚本但临时PS1中文exe名被PowerShell5.1误读。保留两次失败，第三次改为纯ASCII并按目录发现实际exe后成功。
- `Wenshu-SingleInstance`实际创建并Running，S4U/Limited，任务动作、runtime和端口正确，证明当前阶段服务注册执行条件已满足。
- 原B01机器、路径、磁盘和真实数据保护事实不变；原库仍未迁移。现有任务/端口已查明，没有覆盖未知任务。
- 结果：**passed**。B01原blocked及失败历史保留在events.jsonl。
- 后续：D03继续验证ready/导出/单实例；D04注销和D05重启仍需维护者另行操作。
- 敏感检查：无Windows用户名、密码、凭据或正文。
