# 产物清单（文枢 - 自媒体 Studio 1.16.0）

版本单一来源为 `app/__init__.py`。打包脚本更新与实际执行包生成是两个步骤，
旧 exe 不会自动获得源码更新。升级和回退见 [架构与升级说明](../ARCHITECTURE.md)。

## 当前交付状态

- `release/v1.16.0/wenshu-1.16.0-py3-none-any.whl`：已构建，独立环境与非源码目录安装验收通过（含环境热加载、卡片与三平台导出）。

- `dist/wenshu-1.16.0.tar.gz`：源码包（含内置运行资产），已构建；支持 pip 本地安装。
- Windows 绿色包 `release/v1.16.0/文枢-v1.16.0-windows-x64.zip`：含 exe + `_internal/`、双启动脚本、
  自带 Chromium 与完整 docs/，目录式构建和隔离 exe 四平台验收通过。
- Linux 独立包 `release/v1.16.0/文枢-v1.16.0-linux-x64.tar.gz`：打包工程已同步，尚未实际构建二进制。
- Docker：本版未预构建镜像；Dockerfile 在仓库内维护，需要时 `docker build -t wenshu-studio .`。

## 输出目录约定（V1.16）

- **发布根 `release/v<版本号>/`**：zip / sdist / SHA256SUMS 按版本分目录归档，避免互相覆盖。
- **构建中间产物在 `build/`**：`build/dist-windows/`（原始 exe）、`build/dist-linux/`、
  `build/pyinstaller*/` 均为中间态，不入发布根、不入 git。
- **文章文件导出 exports/<平台>/**：固定最终文件目录；成功替换，失败保留完整旧包。
  不再保留新 runs 批次或文稿 snapshot.json，文稿版本由 drafts 管理。旧 runs 不自动删除。
- **缓存 `resource/_cache/`**：Logo 徽章、视频首帧、UI 截图统一缓存位置，与业务目录分离。

## 构建步骤

建议使用独立 Python 3.12 构建环境，避免把本机额外依赖带入冻结程序：

```bash
python -m venv build/package-env
# Windows PowerShell：.\build\package-env\Scripts\Activate.ps1
# Linux/macOS：source build/package-env/bin/activate
python -m pip install --require-hashes -r requirements-build.lock
python -m playwright install chromium
cd web && npm ci && npm run build && cd ..
  python tools/pack_release.py --skip-linux   # Windows exe + sdist/wheel + 文档 + SHA256
```

PowerShell 5.1 请逐行执行命令，不使用 `&&`。Linux 二进制需要 Linux/Docker，不能用 Windows
PyInstaller 交叉编译：先构建前端，再执行 `bash packaging/build_linux_binary.sh`。
该脚本使用带 hash 的 `requirements-build.lock`，构建后检查二进制版本与构建信息。
本地没有 Docker 时，全平台脚本会明确提示 Linux 包未生成。

单独构建 Python 分发包：

```bash
python scripts/build_assets.py
python -m build --no-isolation
```

## 发布包内容与验证

Windows 包含主程序、两种启动脚本、README、CHANGELOG 和完整 docs/；Linux 包含二进制、
Linux 启动脚本及同一套文档。文档保留仓库层级，`docs/release/DEPLOY.md` 到升级说明的链接有效。
旧入口 `docs/ARTIFACTS.md`、`docs/DEPLOY.md` 保留为导航页。

首次启动会在可写运行根播种 config/、web/dist/ 和空密钥模板 .env，并创建 resource/、log/。
发行包不应包含用户的 .env、数据库、素材或日志。Windows 脚本必须保持纯 ASCII 和 CRLF；
Linux shell 脚本使用 LF。

`--version` 显示应用版本；`--build-info` 显示版本、commit、源码和三类依赖锁摘要、
Python/SQLite/Node/Playwright 信息。`--reuse-exe` 只有在内嵌版本及源码摘要匹配时才允许复用。
`SHA256SUMS.txt` 记录本次实际生成的发行文件，不代表尚未生成的平台。

## 打包工程

- `tools/pack_release.py`：测试门槛、前端新鲜度、资产归集、平台构建、文档组装及校验和。
- `scripts/build_assets.py`：归集运行资产，生成构建溯源信息。
- `requirements.lock`：运行依赖；`requirements-dev.lock`：测试依赖；`requirements-build.lock`：构建和冻结依赖。
- `packaging/wenshu.spec`、`packaging/launcher.py`：PyInstaller 资源与入口。
- `packaging/build_linux_binary.sh`：Linux 容器内冻结构建。
- `Dockerfile`、`.dockerignore`：运行镜像构建与上下文隔离。
- `scripts/start_windows.bat`、`scripts/start_windows.ps1`、`scripts/start_linux.sh`：平台启动入口。

V1.15 验收：87 项后端回归与 2 项真实浏览器流程通过（含四平台导出、定稿后自动开版和历史视图回滚），Vue 类型检查及生产构建通过。Windows exe、sdist、wheel 已生成；exe 与 wheel 隔离验收通过，未使用原项目数据库。exe 输出管道的中文编码问题已修复，内置 Chromium revision 为 1248。业务提交 436e27d 的 GitHub CI 已全部通过（Windows/Linux Python 3.10/3.12、浏览器与安装包、Docker）。

冻结程序复验：`python scripts/frozen_smoke.py release/v1.16.0/文枢-v1.16.0-windows-x64`。该脚本使用临时空数据目录并屏蔽真实模型/搜索密钥。运行后只结束自己启动的 exe 进程树。

## V1.16 验收（2026-10-29）

97 项后端回归、5 项真实浏览器流程、Vue 严格类型检查与生产构建通过。新增验证覆盖环境配置替换/删除/失败保留、实际模型 HTTP 请求读取新 key（MockTransport，无付费调用）、令牌会话轮换、后台扫描不阻塞就绪、LLM 完成后的页面刷新、编辑缓冲与方向键翻页。

Windows exe 与独立安装 wheel 均在临时数据目录通过环境热加载和发布流程验收；浏览器 revision 1248。Linux 独立二进制未实际构建，Docker 未在本机运行。代码按功能提交并 push main，未创建 tag/GitHub Release。

同机 3 次新进程测量：源码就绪中位数 1.911 → 1.462 秒（约 24%）；Windows 旧单文件包 17.333 → 新目录式包 1.478 秒（约 91%），新版样本范围 1.475–3.409 秒。未清操作系统文件缓存；不代表机器重启后磁盘冷缓存耗时，也不包含浏览器绘制。原始样本见 [V1.16-startup.json](V1.16-startup.json)。

新版程序需要整体保留 exe 与 `_internal/`。发布目录的 SHA256SUMS.txt 覆盖 zip、sdist 与 wheel。
