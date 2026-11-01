# B02 程序与源码复核（attempt 02）

- B01权限前置已于attempt 02通过，原B02.md的实测程序证据继续有效：候选ZIP 298,628,465字节，SHA256与清单一致，CRC完整。
- 实际exe仍为`C:\Wenshu\releases\v1.1.0-rc.1\文枢.exe`，版本1.1.0-rc.1，build commit `2be37d65f2e5a579550c74d429aca665d60a6f02`。
- run固定source_commit为`91c90090515405f6235e31f70a47f64c1851631f`；`git diff --name-only <build> <source> -- app web/src config pyproject.toml .env.example`无输出。后续只有验收文档/账本提交，应用、前端和配置未漂移。
- 当前任务动作指向同一exe；D03已认证ready和导出通过，证明实际运行程序与B02核对对象一致。
- 结果：**passed**。没有重构建、移动标签或覆盖旧候选。
