# 文枢 - 自媒体 Studio

输入一篇 AI 行业要闻（大模型 / 具身智能 / 芯片 / AI 软硬件）的链接，三个 Agent 依次完成
**资料收集 → 创作 → 审稿**，人工审阅定稿后一键导出**公众号 / 小红书 / 微博 / X** 的发布包。

短名「文枢」，全称「文枢 - 自媒体 Studio」；pip 包名与进程标识为 `wenshu`。

架构优化及升级注意事项见 [架构与升级说明](docs/ARCHITECTURE.md)。

## 快速开始

**方式一：绿色执行包（无需 Python 环境，推荐）**

- Windows：解压发布包，双击 `启动文枢.bat`；PowerShell 用户：`.\启动文枢.ps1`
  （注意：PowerShell 运行当前目录脚本必须带 `.\` 前缀）→ 浏览器自动打开 http://127.0.0.1:8000
- Linux：解压后执行 `./start_linux.sh`

**方式二：源码运行**

Windows PowerShell（注意 PS 5.1 不支持 `&&`，请逐行执行或用 `;` 分隔）：

```powershell
pip install --require-hashes -r requirements.lock
python -m playwright install chromium
cd web; npm ci; npm run build; cd ..
Copy-Item .env.example .env   # 填入 DEEPSEEK_API_KEY 等
python -m app                 # → http://127.0.0.1:8000
```

Linux / macOS（bash）：

```bash
pip install --require-hashes -r requirements.lock
python -m playwright install chromium
cd web && npm ci && npm run build && cd ..
cp .env.example .env          # 填入 DEEPSEEK_API_KEY 等
python -m app                 # → http://127.0.0.1:8000
```

**方式三：pip 本地安装 / Docker**

```powershell
pip install dist/wenshu-1.16.0.tar.gz; wenshu            # 源码包安装（交付 sdist）
docker build -t wenshu-studio:1.16.0 .                   # 容器化（服务器批量部署，本版未预构建）
docker run -d --env-file .env -p 8000:8000 wenshu-studio:1.16.0
```

发布包产物与部署细节见 [docs/release/ARTIFACTS.md](docs/release/ARTIFACTS.md) 与
[docs/release/DEPLOY.md](docs/release/DEPLOY.md)；版本管理约定见
[docs/release/VERSIONING.md](docs/release/VERSIONING.md)；应用使用见
[docs/user-manual.md](docs/user-manual.md)。一键打包全平台发布包：`python tools/pack_release.py`
（产物统一进 `release/`）。独立爬取小工具：`python tools/scraper/server.py`（→ 127.0.0.1:8765）。

## 架构速览

- **后端**：FastAPI + SQLite + 文件素材库（本地优先）；三 Agent（collector / rewriter / reviewer）
  由编排器经 SQLite 持久化任务队列驱动，SSE 实时推送进度
- **文案块模型**：带稳定 id 的有序块列表，支撑段落级重生成、审稿锚定、小红书分页
- **LLM 调度**：OpenAI 兼容薄路由（DeepSeek / 火山方舟 / OpenRouter），渠道优先级 +
  fallback + 成本日志；密钥在 `.env`，prompt 与参数全部外置 `config/` 可手调
- **审稿六维**：排版（规则）· 事实/来源/合规/AI味（LLM，引文逐字接地校验）· 撞稿
  （SimHash 双阈值，blocker 禁止定稿）
- **日志**：常驻持久化 `log/wenshu.log`（INFO/ERROR 两档可配，按日期轮转，错误带堆栈）
- **发布**：一阶段统一导出发布包（公众号排版 HTML、小红书分页卡片 PNG、微博短文、X 推文串），
  手动发布；API/RPA 自动推送为二阶段扩展点（Publisher 插件接口已就位）
- **前端**：Vue 3 + Naive UI + Tailwind，文章三态列表 / 素材面板 / 块编辑器（预览默认、双击编辑）
  / 审稿 checklist 联动 / 发布包导出 / 设置页

## 文档

| 文档 | 内容 |
|---|---|
| **[docs/PROGRESS.md](docs/PROGRESS.md)** | **开发进度交接：当前状态 / 架构速查 / 坑清单 / 待办（新会话先读它）** |
| [docs/release/ARTIFACTS.md](docs/release/ARTIFACTS.md) | 发布产物清单（exe / Linux 二进制 / sdist / Docker） |
| [docs/release/DEPLOY.md](docs/release/DEPLOY.md) | 部署步骤（Windows / Linux / Docker）与故障排查 |
| [docs/design/](docs/design/README.md) | 产品设计文档（00 总览 ~ 08 路线图，含拍板结论） |
| [docs/api.md](docs/api.md) | 接口文档 |
| [docs/user-manual.md](docs/user-manual.md) | 使用手册 |

## 测试

```bash
pip install --require-hashes -r requirements-dev.lock
python -m playwright install chromium
python -m pytest tests/        # 版本并发、故障注入、离线端到端、权限与网络边界
cd web && npm ci && npm run build && npx playwright install chromium && npm run test:e2e
```

## 合规说明

本工具用于基于公开资讯的**再创作**：关键事实以块级 citations 标注素材来源，审稿内置撞稿查重
与合规检查；发布环节只产出草稿包，最终发布行为由使用者完成。请尊重原创与平台规则。

## V1.15 工作版本与导出

定稿前的人工编辑、AI 重写和连续采纳审稿意见保存在同一工作版本；定稿封存当前版本，之后首次修改才自动进入下一个版本。未定稿改动保存在数据库，刷新或重启后仍可继续。回滚会替换未定稿内容，已定稿快照保持可读。

发布包固定存放在 `resource/<项目目录>/exports/<平台>/`，重新生成成功后替换同平台文件，失败保留上一份完整包。旧 `runs/` 不自动删除；文稿版本由文稿系统管理。小红书品牌签名和 Logo 放在最后正文页底部。

X 提供逐条 `post-NN.txt`、合并预览 `thread.txt` 和媒体/回复顺序 `thread.json`；微博提供完整摘要 `weibo.txt` 与 `media.json`。平台规范与人工发布步骤见 [V1.15 说明](docs/release/V1.15.md)。旧 exe 需替换为新构建。
# V1.16 更新

设置页支持保存 `.env` 后点击“刷新环境变量”；创作/审稿内容在任务完成后自动更新，小红书卡片大图支持 ←/→ 翻页。绿色包改为 exe + `_internal/`，升级时请整体替换程序目录并保留自己的配置与数据。详见 [V1.16 说明](docs/release/V1.16.md)。
