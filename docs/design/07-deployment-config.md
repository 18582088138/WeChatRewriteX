# 07 · 部署与配置

## 第一阶段：本地开发部署（当前轮）

环境：conda 环境 `xkd_env_py312`（Python 3.12）。

```bash
conda activate xkd_env_py312
pip install -r requirements.txt        # fastapi uvicorn litellm pydantic sqlalchemy \
                                       # trafilatura playwright yt-dlp imagehash \
                                       # simhash jinja2 watchdog httpx tenacity ...
playwright install chromium            # 爬虫兜底 + 卡片截图共用
# 前端
cd web && pnpm install && pnpm build   # 产物 dist/ 由 FastAPI 托管
# 启动
python -m app                          # http://127.0.0.1:8000
```

开发期前端热更新：`pnpm dev`（Vite 代理 `/api` 与 `/sse` 到 8000 端口）。

预期依赖清单（草案，M1 收敛）：fastapi、uvicorn、sqlalchemy、aiosqlite、pydantic、litellm、jinja2、httpx、tenacity、trafilatura、playwright、yt-dlp、imagehash、pillow、simhash、pypdf、watchdog、apscheduler（或自研 asyncio 队列）、sse-starlette、python-multipart；可选：sqlite-vec。

## 配置三层模型

| 层 | 位置 | 内容 | 优先级 |
|---|---|---|---|
| 密钥 | `.env`（不进 git） | `DEEPSEEK_API_KEY`、`ARK_API_KEY`、`TAVILY_API_KEY`、`WECHAT_MP_APPID/SECRET`、X/微博凭证、RPA storage_state 路径 | 最高（只读引用） |
| 非密配置 | `settings.yaml` | 搜索窗口、参考篇数、阈值、模型档位映射、风格包绑定、hooks、并发数 | 中 |
| UI 设置 | DB `settings` 表 | 设置页可改的一切 | 覆盖 yaml |

启动时合并：默认值 ← `settings.yaml` ← DB；密钥仅从 `.env` 读取，UI 只显示掩码。`.env.example` 进 git 作为模板。

`settings.yaml` 草案：

```yaml
search_window_days: 3
allow_foundational: true
ref_count: { min: 3, max: 5, scarce_min: 1 }
auto_pipeline: false          # 自动连跑到 REVIEWED
recheck_on_edit: { enabled: true, min_changed_blocks: 3, min_word_delta_pct: 20 }
originality: { simhash_warn: 0.35, embedding_block: 0.75, block_on: true }
word_count: { wechat_mp: [1200, 1800], xhs: 1000, weibo: 140 }
concurrency: { llm: 2, download: 4 }
hooks:
  draft.finalized: ["python scripts/notify.py {article_id}"]
```

## 一键安装 / 一键启动（M3 目标，现在定接口）

- `install.bat` / `install.sh`：检测 conda 环境（不存在则创建）→ 装依赖 → `playwright install chromium` → 初始化 DB 与目录 → 引导复制 `.env.example`。
- `start.bat` / `start.sh`：激活环境 → 起后端（托管前端 dist）→ 自动开浏览器。
- 再往后：PyInstaller 单文件（Playwright 浏览器外置）或 Docker 镜像（`mcr.microsoft.com/playwright/python` 基底），二选一，倾向 Docker（Playwright 依赖在 Windows 原生打包里容易踩坑）。

## 线上部署的定位澄清（重要）

GitHub Pages **只能托管静态文件，跑不了 Python 后端**。因此它的正确用途是：

1. 项目主页 / 文档站（本设计文档可渲染发布）；
2. 前端构建产物的**演示壳**（无后端、纯 UI 演示）。

真正的线上版本需要跑后端，候选（都支持 Python、有一键部署路径）：

| 平台 | 适配度 | 备注 |
|---|---|---|
| Hugging Face Spaces | 好 | Docker SDK，免费档可用；Playwright 可装进镜像 |
| Render / Railway | 好 | 常驻进程 + 磁盘，适合带 SQLite 的本应用 |
| 自有 VPS | 最灵活 | 后续多账号/RPA 场景的唯一稳妥解 |

线上化时的额外工作（列入 M3）：访问认证（单用户密码/令牌即可）、HTTPS、密钥改为平台 secret 管理、SQLite 定期备份。RPA 类发布在云端 IP 上风控更敏感，**建议发布功能长期留在本地执行**，云端只做收集与创作——这是推荐的双端分工。

## 数据备份

- `data/` 整体是唯一状态所在；提供「导出备份」按钮（打包 `data/` 为 zip）与 hooks 触发的 git 自动提交（`draft.finalized` 事件 → commit）。
- Git 仓库本身管理代码与 `docs/`、`settings.yaml`、`.env.example`；`data/`、`.env` 在 `.gitignore`。

## 开放问题

1. 前端包管理器用 pnpm 还是 npm？（机器上有 pnpm 则 pnpm）
2. 云端部署的目标平台有没有倾向？（影响 M3 的一键部署脚本形态）
