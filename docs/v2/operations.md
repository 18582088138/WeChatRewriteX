# 音频候选安装、维护与回退

## 配置与启动

延续 Vue/FastAPI/SQLite、单数据根和一个 ASGI worker。音频任务进入既有创作泳道，TTS 同时最多一个请求；本地处理用一个有界子进程通道，不新增独立 worker 或 GPU。

密钥仅通过服务端 `MINIMAX_TTS_API_KEY` 读取，默认已有音色用 `MINIMAX_DEFAULT_VOICE_ID`；声音档案存储非密钥标识和授权项目范围。当前开发机默认音色已设置，但没有复制密钥到 Git 或新前端。环境启动时进程变量优先于 `.env`；显式刷新环境变量沿用既有文件权威规则。

联网时可在启动进程设置用户提供的 HTTP_PROXY/HTTPS_PROXY/FTP_PROXY，NO_PROXY 保留 localhost/127.0.0.1 等本地范围。应用 HTTP 层沿用现有环境代理/Windows PAC 支持。区域配置仅允许 `https://api.minimaxi.com` 与 `https://api.minimax.io`，只能发送合成与只读音色清单请求。

音频工具优先级：`WENSHU_FFMPEG`/`WENSHU_FFPROBE` 显式绝对路径 → 持久运行根 `audio-tools/ffmpeg.exe` 和 `ffprobe.exe` → PATH。Windows 可自行从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html) 安装可信构建，保留对应分发许可；本候选不把开发机 GPL 构建擅自复制进绿色包。Docker 安装发行版 FFmpeg 包。工具配置、FakeTTS 与存储上限变更需重启。

绿色包仍采用 exe + `_internal/`，前端和数据库扩展 schema 随候选包。不要只替换 exe。Linux 未在本开发机构建，不冒充通过。

`WENSHU_FAKE_TTS=1` 仅供离线测试；它输出确定性 WAV 测试音，不能作为人声交付。真实使用保持 `0`。

## 费用与资源

默认共享持久额度为 2 个请求、累计 120 个发送字符；发出即计入，失败/未知不返还。额度存储在数据库，跨页面、批次和重启共享；事务内预留防止并发超限。管理员在设置页调整上限与带来源/生效时间/模型的费率。真实长样例前先明确增加本批次的文本、请求与金额额度，不能无限重试。

2026-11-05 官方中国区文档列出：speech-2.6-hd / speech-02-hd 为 3.50 元/万计费字符，Turbo 为 2.00 元/万计费字符。1 汉字计 2，其余字符计 1。记录返回 usage_characters 与估算，实际账户资源包/账单仍需核对；本轮余额不足，不报告准确实际费用。

最少保留 256MB 空闲空间，音频目录默认上限 2048MB（`WENSHU_AUDIO_MAX_MB`）。输入段落/总稿、请求/响应大小、源音频 64MB 和 10 分钟、输出 10 分钟、工具超时均有界。生成前稿件超过 2400 发送字符拒绝付费发送。历史文件不自动删除；达到空间上限先完整备份和人工归档。

## 数据与恢复

新增 `audio_schema` 独立扩展版本 **1**，基础 personal/team `PRAGMA user_version` 保持原来的 3/6；旧程序可忽略新增表。迁移原子化且重复启动不重复实施，已有图文项目首次增加扩展前保存 `backups/before-audio-v1.sqlite3`。该自动副本只含数据库，不代替完整实例备份。

所有声音档案、口播与版本、音频任务、费用、片段、文件及审批在原 SQLite 中；音频文件位于 `<data-root>/audio/`，不通过 `/files/` 暴露内部路径。项目专属音频端点验证当前 ACL 和校验摘要。跨项目不共享片段缓存。

升级/回退：停止唯一实例，按 [完整实例备份](../v1-plus/S6-operations.md) 备份 DB、音频、原素材、配置和 `.env`，再部署候选到独立程序目录。新旧服务不能并行写同数据根。恢复只到全新隔离目录，校验 SHA256 后以显式 runtime/data/log 参数启动；不得覆盖唯一原件或运行中的 NUC。

完整成品与字幕不可变，正式导出采用一个 SQLite 事务更新完成包指针，保持稳定下载 URL。恢复已发送/已收到但未完成校验的片段为响应未知，不自动付费重发；未发出的预留和已完成缓存可安全续用。取消或撤权释放未发送预留，但不抹去已发送账本。

## 验证命令

源码验证：`python -m pytest tests/ -q`；前端：`npm run build`、`npm run test:e2e`、`npm run test:team`、`npm run test:audio`。CI 使用 FakeTTS/固定音频，并安装 FFmpeg；更新工作流不代表已执行远端 CI。

独立候选 wheel 在空目录运行 `scripts/v2_package_smoke.py`（使用安装包解释器），检查 schema、音频/字幕/导出与完整备份恢复。实际记录见 [阶段证据](acceptance.md)。调试脚本 `v2_tts_smoke.py` 有持久额度，累计已用 2 次，原调试额度已用完；不要换目录绕过额度或自动重试 `1008`。只读清单脚本每执行一次都会查询一次，本轮已完成，勿为浏览界面重复运行。
