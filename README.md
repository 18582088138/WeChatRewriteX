# WeChatRewritingAssistant · AI 要闻洗稿助手

输入一篇 AI 行业要闻（大模型 / 具身智能 / 芯片 / AI 软硬件）的链接，三个 Agent 依次完成
**资料收集 → 再创作 → 审稿**，人工审阅定稿后一键导出**公众号 / 小红书 / 微博 / X** 的发布包。

## 快速开始

```bash
conda activate xkd_env_py312 && pip install -r requirements.txt
python -m playwright install chromium
cd web && npm install && npm run build && cd ..
copy .env.example .env   # 填入 DEEPSEEK_API_KEY 等
python -m app            # → http://127.0.0.1:8000
```

详见 [docs/user-manual.md](docs/user-manual.md)。

## 架构速览

- **后端**：FastAPI + SQLite + 文件素材库（本地优先）；三 Agent（collector / rewriter / reviewer）
  由编排器经 SQLite 持久化任务队列驱动，SSE 实时推送进度
- **文案块模型**：带稳定 id 的有序块列表，支撑段落级重生成、审稿锚定、小红书分页
- **LLM 调度**：OpenAI 兼容薄路由（DeepSeek / 火山方舟 / OpenRouter / OpenAI），渠道优先级 +
  fallback + 成本日志；密钥在 `.env`，prompt 与参数全部外置 `config/` 可手调
- **审稿六维**：排版（规则）· 事实/来源/合规/AI味（LLM）· 撞稿（SimHash + 向量双阈值，
  blocker 禁止定稿）
- **发布**：一阶段统一导出发布包（公众号排版 HTML、小红书分页卡片 PNG、微博短文、X 推文串），
  手动发布；API/RPA 自动推送为二阶段扩展点（Publisher 插件接口已就位）
- **前端**：Vue 3 + Naive UI + Tailwind，文章三态列表 / 素材面板 / 块编辑器（预览默认、双击编辑）
  / 审稿 checklist 联动 / 发布包导出 / 设置页

## 文档

| 文档 | 内容 |
|---|---|
| [docs/design/](docs/design/README.md) | 产品设计文档（00 总览 ~ 08 路线图，含拍板结论） |
| [docs/dev-plan.md](docs/dev-plan.md) | M1 开发计划与切片验收 |
| [docs/api.md](docs/api.md) | 接口文档 |
| [docs/user-manual.md](docs/user-manual.md) | 使用手册 |

## 测试

```bash
python -m pytest tests/        # 24 项（含 fixture 离线端到端 + Playwright 卡片渲染）
```

## 合规说明

本工具用于基于公开资讯的**再创作**：关键事实强制标注素材来源，审稿内置撞稿查重与合规检查；
发布环节只产出草稿包，最终发布行为由使用者完成。请尊重原创与平台规则。
