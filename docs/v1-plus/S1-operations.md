# S1：独立运行目录与单机维护

适用于S1源码/新构建包；正式v1.0下载的旧exe没有新参数，拉取源码不会更新旧exe。
当前公司主机只做隔离验证；家庭系统/硬件/网络待查，不安装服务、不重装系统、不开放公网。
S1尚未实现成员账号，只允许维护者验证，共享令牌不能替代成员身份。

## 1. 目录与配置

以下路径均为示例，实施时替换为实际主机路径：

- 程序目录：Windows `D:\Wenshu\releases\s1`，Linux `/opt/wenshu/releases/s1`，随版本替换。
- 持久运行目录：Windows `D:\Wenshu\runtime`，Linux `/srv/wenshu`，不随程序升级替换。
- 运行目录中保存 `config/`（设置/风格/prompts）、`.env`（密钥/维护令牌）、`resource/`（DB/素材/历史/导出）、`log/`。
- 本地备份：`D:\Wenshu\backups\日期-批次` 或 `/srv/wenshu-backups/日期-批次`，位于数据根及配置目录外。

`--runtime-dir` / 进程环境 `WENSHU_RUNTIME_DIR` 在配置导入前确定运行根，不在`.env`中切换。
`--data-dir`、`--log-dir`优先于`.env`/YAML；生产及恢复演练显式传三条路径。
相对`WENSHU_DATA_DIR`以运行根为基准；不带新参数的便携启动保留原行为，不自动移动旧文件。
首启从程序默认资产补缺失配置，不覆盖已有settings、prompt、风格或`.env`。
独立运行模式的前端来自当前程序资产，持久目录中的旧`web/dist`不会遮住新界面。
`WENSHU_MIN_FREE_MB`默认64，配置/数据/日志各目录可用空间低于阈值或无法写临时文件时ready返回503。
阈值是最低保护，不是大文件任务所需空间承诺；路径/阈值变更需重启，既有模型密钥热加载保留。

## 2. Windows安装与使用

先确认实际Windows、CPU、磁盘和Python；可选已有绿色包或Python路线，不要求重装。
源码使用Python3.10+（本阶段测试3.12）、构建前端使用Node≥20.19；依赖和前端可在开发机准备：

```powershell
python -m pip install -r requirements.txt
cd web
npm ci
npm run build
cd ..
python -m playwright install chromium
```

在程序目录启动源码，或使用未来新构建exe（exe与`_internal/`必须成套）：

```powershell
python -m app --runtime-dir 'D:\Wenshu\runtime' --data-dir 'D:\Wenshu\runtime\resource' --log-dir 'D:\Wenshu\runtime\log' --host 127.0.0.1 --no-browser
# 新exe的等价命令：
.\文枢.exe --runtime-dir 'D:\Wenshu\runtime' --data-dir 'D:\Wenshu\runtime\resource' --log-dir 'D:\Wenshu\runtime\log' --host 127.0.0.1 --no-browser
```

首次启动生成config及空密钥示例`.env`。修改运行目录中的配置；无真实密钥只验证规则审稿/降级创作。
源码卡片需安装Chromium；新exe用`--install-browser`，包内已有浏览器优先。
浏览器访问`http://127.0.0.1:8000`；`/api/health`看存活，`/api/ready`看DB/任务线程/存储。
维护令牌非空时ready需Authorization或合法Cookie。S1默认loopback，不能邀请成员用令牌共用。

确认目标设备后才在该主机管理员PowerShell注册开机任务：

```powershell
.\packaging\deployment\register_windows_task.ps1 -PythonPath 'D:\Wenshu\python\python.exe' -AppDirectory 'D:\Wenshu\releases\s1' -RuntimeDirectory 'D:\Wenshu\runtime'
Start-ScheduledTask -TaskName 'Wenshu-SingleInstance'
Get-ScheduledTaskInfo -TaskName 'Wenshu-SingleInstance'
```

新exe改用`-ExecutablePath 'D:\Wenshu\releases\s1\文枢.exe'`，不用`-PythonPath`。
模板使用已有用户、S4U、有限权限、开机触发、失败每分钟重启、忽略重复启动、不限运行时长，同名任务拒绝覆盖。
用户须可读程序、写运行目录；S4U不依赖需要用户凭据的网络盘，令牌/密码不放任务参数。
停机维护用`Stop-ScheduledTask -TaskName 'Wenshu-SingleInstance'`并确认进程退出。
升级任务先停止，核对确为本应用，再`Unregister-ScheduledTask -TaskName 'Wenshu-SingleInstance' -Confirm:$false`并注册新路径。
家庭主机的Windows版本、权限、开机/异常重启尚未实测，失败应按实际账户/系统调整。

## 3. Docker候选路线

当前无Docker命令，以下材料未进行镜像/容器实测。已有Docker的小主机可采用；不强制安装。
开发机构建/保存镜像，主机加载，不要求主机编译前端：

```bash
docker build -t wenshu:s1-local .
docker save -o wenshu-s1-image.tar wenshu:s1-local
# 转移后在主机执行：
docker load -i wenshu-s1-image.tar
```

独立部署目录例如`/srv/wenshu-deployment`，内建`runtime/`、`backups/`，把`.env.example`复制为`runtime/.env`，
设置随机维护令牌和模型密钥。运行UID10001须可写这两个明确目录，Linux由维护者限制所有者/访问权限。
不在容器`.env`填主机路径，模板已设容器内部运行/数据/日志路径。

```bash
docker compose --project-directory /srv/wenshu-deployment -f /opt/wenshu/s1/packaging/deployment/compose.yaml up -d
docker compose --project-directory /srv/wenshu-deployment -f /opt/wenshu/s1/packaging/deployment/compose.yaml ps
docker compose --project-directory /srv/wenshu-deployment -f /opt/wenshu/s1/packaging/deployment/compose.yaml logs --tail 100
```

默认端口只发布到主机127.0.0.1，容器内绑定0.0.0.0，因此APP_ACCESS_TOKEN仍须非空。
`restart: unless-stopped`处理进程退出，healthcheck失败不会自动重启；存储故障应先修复。
维护备份先使用相同project-directory和模板参数执行`stop`，确认退出后执行
`run --rm --no-deps wenshu python -m app --backup /backups/<全新批次>`，再`up -d`。
直接docker run方式新增`/app/state`持久卷保存配置，保留旧`/app/resource`和`/app/log`卷兼容。
Compose统一挂载runtime并显式设置数据/日志；更换镜像不替换这些目录。跨城市入口留待S6。

## 4. Linux/systemd候选路线

模板`packaging/deployment/wenshu.service`适用于已有systemd和专用用户的主机，当前Windows未实测。
开发机构建前端/归集资产/生成wheel，主机在新版本venv安装匹配系统/架构的依赖：

```bash
python -m pip install build 'setuptools>=77' wheel
python -X utf8 scripts/build_assets.py
python -X utf8 -m build --wheel --no-isolation
# 主机运行：
/opt/wenshu/releases/s1/venv/bin/python -m pip install /path/to/new-wheel.whl
/opt/wenshu/releases/s1/venv/bin/python -m playwright install --with-deps chromium
```

Chromium按服务用户安装并确认系统依赖，不能把Windows浏览器当Linux浏览器。
创建专用用户及可写`/srv/wenshu`，核对模板中的Python/运行路径（示例`/opt/wenshu/current/venv/bin/python`），
安装模板为`/etc/systemd/system/wenshu.service`：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wenshu
systemctl status wenshu
journalctl -u wenshu -n 100
```

仅监听127.0.0.1，失败10秒重启，5分钟失败5次停止重试。维护用`sudo systemctl stop wenshu`/`start wenshu`。
此阶段不新增公网代理/端口；后续内网监听也需明确维护令牌与防火墙范围。

## 5. 完整离线备份和隔离恢复

`--backup`保存数据根、config和持久`.env`；日志可另存。仅外部进程注入的密钥不在文件备份中，需另行安全保存注入方式。
备份含密钥，禁止公开下载或提交Git；Linux目录权限受限，Windows维护者限制ACL。
先暂停操作、等待任务结束或确认可恢复，停止服务及自动重启管理器。worker持锁时拒绝备份。

```powershell
python -m app --runtime-dir 'D:\Wenshu\runtime' --data-dir 'D:\Wenshu\runtime\resource' --backup 'D:\Wenshu\backups\s1-before-upgrade'
python -m app --runtime-dir 'D:\Wenshu\restore-check' --restore 'D:\Wenshu\backups\s1-before-upgrade'
python -m app --runtime-dir 'D:\Wenshu\restore-check' --data-dir 'D:\Wenshu\restore-check\resource' --log-dir 'D:\Wenshu\restore-check\log' --port 8012 --no-browser
```

Linux换实际绝对路径，exe将`python -m app`换为新exe。备份/恢复目标必须不存在，恢复不覆盖已有根。
备份保存`resource/`、`config/`、可选`.env`及完成后的`backup-manifest.json`，用SQLite backup API，不只复制WAL主文件。
manifest包含应用/schema版本、文件SHA256，恢复先校验路径、清单/摘要和DB完整性，再创建目标。
缺文件、多文件、篡改、缺完成manifest、符号链接均不能作为有效备份；复制失败留下隔离目录，另选新目录重试。
恢复保留配置原文，旧绝对路径可能指回原实例，**隔离启动必须显式指定上述运行/数据/日志三条路径**。
核对项目、素材预览、正文/历史、定稿、规则审稿、任务及四平台导出，记录数据量与演练时间。
同机备份不能应对主机/磁盘整体损坏；另一设备副本列为S6缺项。本地演练不代替小主机RPO/RTO验收。

迁移旧源码先停应用，在原运行目录使用新源码`python -m app --backup <全新目录>`（不改原数据根）保存旧状态，
再恢复新目录、显式路径启动；旧下载exe无此命令，先按原流程离线保存完整resource/config/.env。
不自动移动原文件，不让新旧进程同时写同一根。

## 6. 升级、故障与回退

- 升级：停服务及自启动管理器 → 完整备份 → 新程序目录安装 → 沿用独立运行根 → ready和历史/素材/导出核验。
  固定版本服务模板需更新启动路径，不能混用新exe与旧_internal，不替换持久目录。
- S1无新schema迁移，保留v3。回退先停新进程，使用对应程序和完整备份隔离恢复，核对旧路径后切换。
  备份后的编辑先另存；切Git不会恢复数据。
- 第二进程拒绝启动：检查已有实例/后台任务，不删锁文件强抢；进程退出/崩溃由OS释放锁。
- health200/ready503：核查DB、线程、数据/配置/日志权限及空间；外部AI网络不影响health，health不代替ready。
- 空间不足：先停新任务、核查占用，不直接删归档素材/历史引用；物理回收须先审计历史引用。
- 备份失败：检查停机/空间/ACL/符号链接，保留错误记录，另选全新批次，缺manifest不得标成功。
- 异常退出后running在下次取得锁后重排；已发出的模型/下载不保证强制取消，重试可能有额外费用或副作用。
  不承诺恰好一次执行。自启动失败看计划任务/systemd/容器日志及`log/wenshu.log`。
- 家庭主机重启、手机、跨城市、管理员恢复、另一设备备份和长期容量验证仍需后续实测。
