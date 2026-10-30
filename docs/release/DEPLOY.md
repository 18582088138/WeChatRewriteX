# 部署步骤（文枢 - 自媒体 Studio 1.18.0）

升级前请停止服务并备份，步骤见 [架构与升级说明](../ARCHITECTURE.md)。旧 exe 不会自动获得源码更新；
以下二进制部署流程适用于重新构建的执行包。每个数据根仅运行一个 ASGI worker；远程绑定必须配置令牌。

> 分 Windows、Linux 两套流程；启动脚本严格区分操作系统（bat 仅 Windows，sh 仅 Linux，禁止混用）。

## 一、Windows 部署

1. **解压**：将 `文枢-v1.18.0-windows-x64.zip` 解压到任意目录（路径避免中文空格更稳妥，
   如 `D:\Apps\wenshu\`）。
2. **启动**（三种方式任选）：
   - 资源管理器双击 `启动文枢.bat`；
   - PowerShell 运行 bat：`.\启动文枢.bat`（**必须带 `.\` 前缀**——PowerShell 不搜索
     当前目录，直接敲名字会报「无法识别为 cmdlet」）；
   - PowerShell 原生脚本：`.\启动文枢.ps1`；若报执行策略拦截，用
     `powershell -ExecutionPolicy Bypass -File .\启动文枢.ps1`。
   脚本自动：创建 `resource/`、`log/`、`config/` 目录 → 端口自检（8000 被占用自动顺延
   8001~8005，避免与已运行实例冲突）→ 首启安装卡片渲染组件 Chromium（仅一次，需联网）
   → 拉起主程序并自动打开浏览器。关闭窗口即停止程序。
   - 脚本提示信息为英文（工程约束：bat/ps1 只写纯 ASCII，否则跨编码解析必乱）；
     `[ERROR] Start failed` 等含义见文末故障表。
   - 注意：Windows PowerShell 5.1 **不支持 `&&`** 连接命令——手动执行命令请逐行或用 `;`。
3. **配置密钥**：首次启动后编辑发布包根目录 `.env`，填入 `DEEPSEEK_API_KEY`（必填其一的
   LLM 渠道）等；保存后重启程序生效。不配置密钥也可运行（降级模式：仅原文成稿）。
4. **目录权限**：程序需在自身目录读写 `resource/`、`log/`、`config/`——不要放到
   `C:\Program Files\` 等需要管理员权限的目录。
5. **日志查看**：`log/wenshu.log`（运行日志，按日期自动拆分为 `wenshu.log.YYYY-MM-DD`）；
   `log/start.log`（启动脚本记录）。级别在 `config/settings.yaml` 的 `log.level`
   （INFO/ERROR）切换，路径在 `log.path` 自定义。

## 二、Linux 部署

> 本版未预出 Linux 二进制包；先执行 `bash packaging/build_linux_binary.sh`（需 Docker）
> 得到 `release/linux/文枢`，按下述结构组装后按本节流程部署。也可直接走第四节 pip 安装。

1. **解压**：`tar -xzf 文枢-v1.18.0-linux-x64.tar.gz && cd 文枢-v1.18.0-linux-x64`
2. **启动**：`./start_linux.sh`。脚本自动：创建目录 → 补可执行权限 → 首启安装 Chromium
   （仅一次）→ 拉起主程序（默认监听 127.0.0.1:8000）。
   - 服务器对外提供访问：`./文枢 --host 0.0.0.0 --port 8000`（必须在 `.env` 配置
     `APP_ACCESS_TOKEN`）。
3. **目录权限**：确保运行用户对程序目录有读写权限（`resource/`、`log/`）；如遇权限问题
   `chmod -R u+rwX .`。
4. **日志查看**：同 Windows，`log/wenshu.log` 按日期轮转；`tail -f log/wenshu.log` 实时跟踪。
5. **保活**：生产环境建议 `nohup ./start_linux.sh &` 或写入 systemd unit（`ExecStart`
   指向 `文枢` 二进制，`WorkingDirectory` 为解压目录）。

## 三、Docker（可选容器化方案，本版未预构建镜像）

```bash
docker build -t wenshu-studio:1.18.0 .
docker run -d --name wenshu --env-file .env -p 8000:8000 \
  -v wenshu-resource:/app/resource -v wenshu-log:/app/log wenshu-studio:1.18.0
```

镜像内置全部依赖与 Chromium；`resource`（数据）与 `log`（日志）用 volume 持久化。

## 四、pip 本地安装（源码包）

```bash
pip install wenshu-1.18.0.tar.gz
wenshu                 # 启动；首启在当前目录自动铺 config/、web/dist、.env
```

从仓库源码直接安装时，先执行 `python scripts/build_assets.py` 归集内置资产。

## 五、常见启动故障排查

| 现象 | 排查 |
|---|---|
| PowerShell 里敲 `启动文枢.bat` 报「无法识别为 cmdlet」 | PowerShell 不搜索当前目录：必须写 `.\启动文枢.bat` 或 `.\启动文枢.ps1` |
| ps1 报「禁止运行脚本 / 执行策略」 | `powershell -ExecutionPolicy Bypass -File .\启动文枢.ps1` |
| README 命令报 `&& 不是有效的语句分隔符` | Windows PowerShell 5.1 不支持 `&&`：逐行执行或改用 `;` |
| 双击 bat 闪退 | 看 `log/start.log`；bat 会自动顺延端口（8000~8005），全占用才失败；首次运行可能被 SmartScreen 拦（点「更多信息 → 仍要运行」），杀毒软件同理加白名单 |
| 浏览器未自动打开 | 手动访问 http://127.0.0.1:8000；exe 默认启动后自动开浏览器，`--no-browser` 关闭 |
| 小红书卡片导出失败 | 发布包已自带 Chromium（`playwright-browsers/`），正常无需安装；若该文件夹被删，执行 `.\文枢.exe --install-browser`（Linux: `./文枢 --install-browser`）一次 |
| LLM 全部降级 | `.env` 密钥未配或填错；看 `log/wenshu.log` 的渠道 fallback 记录 |
| 页面 404/空白 | 前端未播种：删除程序目录 `web/` 后重启（自动重新播种），或联系交付方 |
| 数据迁移 | 整个发布包目录原样拷贝即可（`resource/` + `config/` + `.env` 即全部状态） |

## V1.16 程序目录升级

请保留自己的 `.env`、config/、resource/、log/，停止旧程序后整体替换新程序的 exe、`_internal/`、前端与启动脚本。不可只拷贝 exe。不要混用旧 `_internal` 与新 exe。保存 `.env` 后可在设置页点击刷新环境变量，启动绑定目录等变更仍需重启。
