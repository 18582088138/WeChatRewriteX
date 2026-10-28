# 产物清单（文枢 - 自媒体 Studio 1.11.0）

版本单一来源为 `app/__init__.py`。打包脚本更新与实际执行包生成是两个步骤，
旧 exe 不会自动获得源码更新。升级和回退见 [架构与升级说明](../ARCHITECTURE.md)。

## 当前交付状态

- `dist/wenshu-1.11.0-py3-none-any.whl`：已构建，冷安装、前端、数据库、提示词和卡片渲染验收通过。
- `dist/wenshu-1.11.0.tar.gz`：已构建，包含源码、依赖锁、测试、前端源码及内置运行资产。
- Windows 绿色包 `release/文枢-v1.11.0-windows-x64.zip`：打包工程已同步，独立 exe 尚未重新生成。
- Linux 独立包 `release/文枢-v1.11.0-linux-x64.tar.gz`：打包工程已同步，尚未实际构建二进制。
- Docker：镜像构建、非 root 运行、认证和就绪检查已在 GitHub CI 验证；尚未发布镜像到镜像仓库。

## 构建步骤

建议使用独立 Python 3.12 构建环境，避免把本机额外依赖带入冻结程序：

```bash
python -m venv build/package-env
# Windows PowerShell：.\build\package-env\Scripts\Activate.ps1
# Linux/macOS：source build/package-env/bin/activate
python -m pip install --require-hashes -r requirements-build.lock
python -m playwright install chromium
cd web && npm ci && npm run build && cd ..
python tools/pack_release.py --skip-linux   # Windows exe + 源码包 + 文档 + SHA256
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
