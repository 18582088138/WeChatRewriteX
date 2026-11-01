# D03 Windows任务和权限（attempt 02）

- 提升权限注册：`Wenshu-SingleInstance`已创建并启动；任务状态Running、S4U/Limited、LastTaskResult=267009（0x41301，正在运行），动作指向实际候选exe和`C:\Wenshu\runtime`，8000 loopback。
- 只读`after-start.json`确认任务和health；实际管理员登录后`/api/ready`=200。
- 任务中实际导出：将管理员例外验收项目临时解除归档，weibo发布job=done，4个导出文件及manifest可读，随后重新归档。
- 单实例：可见文枢进程仅1个（PID 19096；非提升查询路径为空属Windows权限边界）。运行中直接执行同数据根`--backup`返回1并明确`数据目录已有运行实例`，未生成备份。
- 驱动失败保留：UAC子进程首次0xFFFD0000未进入脚本；第二次临时PS1中文路径乱码；第三次纯ASCII后成功。原非提升0x80070005仍保留。
- 结果：**passed**。任务注册、目录权限、ready、导出和单实例均实际验证。
- 当前状态：任务继续Running供D06；项目已恢复归档，没有公开监听。回退时可停止并核对本实例任务，保留runtime和程序。
- 附件：任务JSON、启动后probe、认证/导出JSON和运行锁日志；无私有Windows凭据或正文。
