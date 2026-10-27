# 产物清单（文枢 - 自媒体 Studio v1.6.0）

> 本清单随发布包交付。所有产物统一使用新名称：短名 **文枢**，全称 **文枢 - 自媒体 Studio**，
> 技术标识（pip 包名 / 进程标识 / 日志名）为 `wenshu`。

## 一、三类发布产物

| 产物 | 文件 | 用途 | 构建方式 |
|---|---|---|---|
| Windows 绿色执行包 | `release/文枢-v1.6.0-windows-x64.zip` | 解压即用，无需 Python 环境 | `pyinstaller packaging/wenshu.spec`（本版已出包，冒烟通过） |
| 标准源码包（sdist） | `dist/wenshu-1.6.0.tar.gz` | pip 本地安装：`pip install wenshu-1.6.0.tar.gz` | `python scripts/build_assets.py && python -m build --sdist`（本版已出包） |
| Linux 可执行二进制包 | `release/文枢-v1.6.0-linux-x64.tar.gz` | 解压即用，无需 Python 环境 | `bash packaging/build_linux_binary.sh`（Docker 内构建） |

> **本版说明**：Linux 二进制与 Docker 镜像本版未实际出包（按需构建）；构建脚本与
> Dockerfile 已就绪并在仓库内维护，需要时在装有 Docker 的机器上执行
> `bash packaging/build_linux_binary.sh` / `docker build -t wenshu-studio:1.6.0 .` 即可。

`Dockerfile`（可选容器化方案）：服务器批量部署用，镜像内含全部依赖与 Chromium。

## 二、工具选型理由

- **PyInstaller**：适合 Python 桌面/本地服务型程序，可打包为无 Python 环境依赖的独立程序；
  本项目是本地 Web 工作台（FastAPI + 内置前端），单文件 exe/二进制最贴合「双击即用」。
  限制：不支持跨平台交叉编译，Linux 二进制须在 Linux 环境构建（本仓库用 Docker 容器完成）。
- **Docker（可选）**：容器化方案，用于服务器环境批量部署；镜像自带 Playwright Chromium，
  卡片渲染开箱可用；数据与日志经 volume 持久化。
- **sdist**：标准 Python 源码分发，便于二次开发与审计；内置资产（`app/_assets/`）由
  `scripts/build_assets.py` 预归集，首启自动播种到工作目录。

## 三、Windows 发布包目录结构

```
文枢-v1.6.0-windows-x64/
├── 文枢.exe              # 主程序（单文件绿色执行，进程名「文枢」）
├── 启动文枢.bat          # 一键启动脚本（双击拉起，仅适配 Windows）
├── docs/                 # 交付文档（产物清单 + 部署步骤）
├── config/               # 首启自动生成：settings.yaml / prompts / styles（可手调）
├── .env                  # 首启自动生成自 .env.example，填入 LLM 密钥后生效
├── resource/             # 首启自动生成：数据根（SQLite + 素材库 + 导出包）
├── log/                  # 首启自动生成：wenshu.log 按日期轮转 + start.log 启动记录
└── web/dist/             # 首启自动播种：内置前端（有外部构建则优先用外部）
```

Linux 包结构同上（`文枢` 二进制 + `start_linux.sh`）；Chromium 缓存目录：
Windows `%LOCALAPPDATA%\ms-playwright`，Linux `~/.cache/ms-playwright`。

## 四、源码包含内容

`wenshu-1.6.0.tar.gz`：`app/` 全量源码（含 `_assets/` 内置资产：config + web/dist +
.env.example）、`pyproject.toml`、`MANIFEST.in`、`README.md`。安装后提供 `wenshu` 命令
（等价 `python -m app`），支持 `--host/--port/--no-browser/--install-browser`。

## 五、仓库内打包工程文件（源码侧）

| 文件 | 用途 |
|---|---|
| **`tools/pack_release.py`** | **一键打包：默认全平台，产物统一进 `release/` 并附 SHA256SUMS** |
| `pyproject.toml` + `MANIFEST.in` | sdist/wheel 与 `wenshu` 命令入口定义（版本号动态读 `app/__init__.py`） |
| `scripts/build_assets.py` | 内置资产归集（config + web/dist + .env.example → app/_assets） |
| `packaging/wenshu.spec` | PyInstaller 构建脚本（Windows/Linux 通用） |
| `packaging/launcher.py` | 冻结态入口跳板（相对导入经绝对导入进入） |
| `packaging/build_linux_binary.sh` | 借 Docker 在 Linux 容器内构建 Linux 二进制 |
| `Dockerfile` + `.dockerignore` | 容器化运行时镜像 |
| `scripts/start_windows.bat` / `scripts/start_linux.sh` | 一键启动脚本（严格分系统，禁止混用） |

启动脚本工程约束（踩坑记录）：bat 必须**纯 ASCII + CRLF 行尾**——cmd 按 OEM 代码页解析，
LF 行尾会让括号块错乱、非 ASCII 字节跨编码必坏；主程序名靠 `for %%F in (*.exe)` 通配
发现，不硬编码中文。bat 内置端口自检：8000 被占自动顺延 8001~8005。
