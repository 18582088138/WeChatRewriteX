# WeChatRewritingAssistant 设计文档

AI 行业要闻「洗稿→再创作→多平台分发」助手的设计文档集。当前阶段只做设计与讨论，**不含开发任务**。

## 文档索引

| 文档 | 内容 |
|---|---|
| [00-overview.md](00-overview.md) | 产品定位、核心流程、第一阶段已确认决策、设计原则 |
| [01-architecture.md](01-architecture.md) | 总体架构、技术选型、模块划分、扩展机制（插件/MCP/Hooks/风格包） |
| [02-agents-and-pipeline.md](02-agents-and-pipeline.md) | 三个 Agent 的详细设计、流水线状态机、人机协同流程、审稿实现手段 |
| [03-data-and-materials.md](03-data-and-materials.md) | 数据模型（SQLite）、素材库文件布局、文档块模型、素材摄取流水线 |
| [04-frontend.md](04-frontend.md) | GUI 设计：页面结构、块编辑器交互、PC/移动端适配 |
| [05-publishing.md](05-publishing.md) | 多平台发布能力矩阵、Publisher 插件接口、降级策略 |
| [06-style-guide.md](06-style-guide.md) | 语言风格调优指南：如何通过 Prompt 控制输出风格（需长期迭代） |
| [07-deployment-config.md](07-deployment-config.md) | 本地开发部署（conda xkd_env_py312）、一键安装/启动、配置分层、线上部署定位 |
| [08-roadmap.md](08-roadmap.md) | 里程碑规划、风险清单、待用户拍板的开放问题 |

## 阅读建议

- 想快速了解全貌：读 `00` 和 `01`。
- 想讨论 Agent 工作流细节：读 `02`。
- 想讨论 UI/交互：读 `04`。
- 每篇末尾的「开放问题」汇总在 `08-roadmap.md`，是下一阶段讨论的重点。
