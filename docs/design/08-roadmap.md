# 08 · 路线图、风险与开放问题

## 里程碑

| 里程碑 | 范围 | 验收标准 |
|---|---|---|
| **M1 本地 MVP** | 链接录入 → 收集 → 洗稿 → 审稿 → 人工编辑 → 定稿 → 导出（Markdown / 公众号 HTML / 小红书卡片 PNG）；文章列表三态；块编辑器；素材面板；基础设置页 | 用 3 篇真实要闻跑通全流程；成稿经人工轻改即可用；审稿六维 checklist 全部生效（originality 先只提示不阻断） |
| **M2 发布与素材增强** | Publisher 插件落地（公众号 API/RPA + exporter 兜底）；一键推送草稿箱；watchdog 素材监听；版本 diff；多平台变体预览打磨；审稿阈值用 M1 数据校准后开启阻断 | 一篇定稿可从 GUI 推入公众号草稿箱（或完整导出包）；小红书卡片达到可直接发布的观感 |
| **M3 一键化与线上** | install/start 脚本；Docker 镜像；GitHub Pages 文档站；线上部署（收集+创作）与本地发布分工；访问认证与备份 | 新机器上 10 分钟内完成安装启动并跑通一篇 |
| **M4 打磨与扩展** | 移动端 PWA 体验收尾；风格包生态（多风格 + 范文库回归）；成本看板；素材标签/专辑；可选：ForumEngine 式多 Agent 辩论审稿实验 | 移动端可完成审阅与轻编辑；风格包切换效果可感知 |

M1 刻意不含：RPA 发布、多用户、暗色模式、字符级 diff。

## 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 平台接口/登录态失效（公众号、小红书） | 高 | 一切平台依赖走插件 + 降级链；exporter 兜底永远可用；登录态巡检提醒 |
| 撞稿投诉 | 高 | 双阈值查重 blocker + 强制来源标注 + 「重述事实而非逐句改写」的风格约束 |
| 内容失实 | 高 | 证据包 grounding + fact 维度逐 claim 核对 + blocker 不定稿机制 |
| LLM 成本失控 | 中 | 模型分档 + `llm_calls` 成本日志 + 设置页用量看板（M4） |
| 中文 AI 味检测不准 | 中 | 预防式 prompt 反模式清单为主，检测为辅，人工终审兜底 |
| RPA 合规（小红书等） | 中 | 默认关闭、用户显式启用、文档明示风险；优先导出卡片包手动发 |
| Windows 环境坑（Playwright、sqlite-vec） | 低 | M1 第一周做技术验证 spike |
| 素材版权 | 中 | 图片优先官方稿件/论文图并标注来源；提供一键替换；卡片模板不含版权素材 |

## 开放问题汇总（按优先级，供讨论拍板）

**影响 M1 范围的：**

1. 公众号资质：是否有**认证公众号**？决定发布层先做 API 还是 RPA/导出。（来自 `05`）（为确保发布包的一致性，先不考虑公众号API接口，统一导出发布包，手动发布，自动发布作为二阶段开发任务）
2. originality 阈值策略：M1 只提示不阻断，用真实数据校准后 M2 收紧——同意吗？（来自 `02`）（洗稿Agent通过提示词配置约束，审稿Agent进行强约束，并提供修改指导）
3. 前端组件库：Naive UI vs Element Plus（倾向 Naive UI）。（来自 `04`）（Naive UI）
4. 向量索引：sqlite-vec vs numpy 兜底，待 spike 验证。（来自 `01`）（是否需要引入embedding model建立索引？）

**影响体验与成本的：**

5. 是否提供 5~10 篇你认可的范文作为风格 few-shot？（强烈建议）（来自 `06`）
文风轻松，诙谐但不失严谨与科学性，有一定的人设感觉（技术传火人/布道师），
真实文章链接，可以用于文风参考，也可以用于真实文章样例测试：
- https://mp.weixin.qq.com/s/J4hF44T9ReHgnnRq_Y4ucA
- https://mp.weixin.qq.com/s/zy-Q9Br15wBG0hNiUzK1Xw
- https://mp.weixin.qq.com/s/cXhPG3ZKOgz8Br53InfExQ
- https://mp.weixin.qq.com/s/7eJn7SYFdMJ4kA2uxohsiw
- https://mp.weixin.qq.com/s/Hwm0pRcJ2ZANaETHkcU1qg
- https://mp.weixin.qq.com/s/qgoO_6y2BD-pe9QXOq120Q
- https://mp.weixin.qq.com/s/prtvMyXdeKYGpLn5ViVbjg
- https://mp.weixin.qq.com/s/bDQ1wFxu9Y7XmfkOQ70Mug
- https://mp.weixin.qq.com/s/jE_B7ZJOKDpL4_bz3JKeUw
- https://mp.weixin.qq.com/s/2mkO2QKRg_dRfVnxZKswlQ
- https://x.com/laobaishare
- https://mp.weixin.qq.com/s/bKmbFg-G53GG0cXjON2SHA
- https://mp.weixin.qq.com/s/lrtQS84NgE1WXgAuJBIaZQ
- https://mp.weixin.qq.com/s/xBruurHTng53rD7gYsoQVg

6. 多模型交叉审稿、商用 AI 味检测 API：启用意愿与预算。（来自 `02`/`06`）（建议借鉴开源方案或使用skill，但可以调研商用AI 味检测 API的效果）
7. 小红书 RPA 风险接受度；X 是否有付费 API 额度。（来自 `05`）
（暂时没有，可以先用统一导出发布包，手动发布，自动发布作为二阶段开发任务）
**可以晚点定的：**

8. 云端部署目标平台倾向；pnpm vs npm；公共素材库标签体系；移动端是否最终需要原生壳。（来自 `01`/`04`/`07`）
（第一阶段软件功能主体在PC端部署；第二阶段开发移动端主要负责轻量化编辑/修改/操作和素材收集）

## 拍板结论汇总（2026-10-24 确认，开发依据）

1. **发布**：一阶段全平台统一「导出发布包 + 手动发布」；API/RPA 自动推送归二阶段。
2. **查重**：洗稿侧 prompt 硬约束预防 + 审稿侧强约束（blocker）+ 具体修改指导；阈值 0.35/0.75 起步。
3. **组件库**：Naive UI。
4. **向量索引**：需要 embedding 支撑语义检索/查重/选图；M1 走 OpenAI 兼容 embedding API（如火山方舟），不可用时降级纯 FTS；不本地装大模型。
5. **风格**：轻松诙谐 + 严谨科学 + 「技术传火人/布道师」人设；14 篇范文用于蒸馏 few-shot 与测试。
6. **AI 味检测**：开源方案/skill 为主，商用 API 仅调研。
7. **端形态**：一阶段 PC 优先；移动端二阶段做轻编辑 + 素材收集。
8. **配置**：Agent prompt 与参数配置统一放 `config/` 文件夹，可手动调整；语言风格 prompt 独立成包确保风格统一。
9. **图文**：必须分页（手机阅读体验）、美观、必要处配图，不出超长单图。
10. **文档交付**：产品设计文档（已有 `docs/design/`）+ 接口文档 + 使用手册。
11. **部署**：一阶段纯本地；云端部署待功能完善后再议。
12. 开发环境核实：conda `xkd_env_py312` = Python 3.12.14 ✓；Node v22.16.0 + npm 10.9.2 ✓（无 pnpm，用 npm）；git ✓（无 gh CLI，GitHub 推送后续再配）。
13. 前端美观：环境中无 "Taste" skill 可用，以设计规范（设计 token / 排版节奏 / 组件打磨）保证 GUI 品质。

### 补充信息
- 使用Taste skill等前端优化skill（包括但不限于），提升GUI的美观和易用性。
- Agent的prompt以及项目的参数配置文件都应该保存在config文件夹中，方便手动调整和优化。
- Agent需要有语言风格设定相关的prompt配置，用于确保所有生成文案风格统一。
- 不要生成一整个超长图文，图文需要分页，确保手机上的阅读体验，同时图文生成也要考虑界面美观设计，必要的部分需要配图
- 需要完整的产品设计文档，接口文档，使用手册。
- 第一阶段先做本地部署，云端部署待功能完善后再做考虑，毕竟涉及到数据同步，资源管理，后端部署等环节。

## 参考的开源项目（调研致谢）

- 发布：social-auto-upload（Cookie/RPA 架构）、Wechatsync（草稿优先 + driver 抽象）、wechatpy（官方 SDK）、AiToEarn（产品化形态）
- 爬取：MediaCrawler（免逆向登录态思路）、wechatDownload（公众号下载）、XHS-Downloader（CLI/API/MCP 三入口）、yt-dlp
- 卡片与排版：guizang-social-card-skill（HTML→截图管线，AGPL 仅借鉴）、RedInk（生成流程编排，CC BY-NC-SA 仅借鉴）、doocs/md（公众号主题）
- LLM 调度：litellm（直接集成）、one-api / new-api（路由思想）
- 工作流与 HITL：AIWriteX（同构参考）、BettaFish（论坛机制）、gpt-researcher（来源追踪）、Co-STORM（参与式人机协同）
- 查重：text-dedup（SimHash/MinHash）；AI 味检测开源现状见 `06`

许可注意：AIWriteX（禁商用 NOTICE）、BettaFish（GPL-2.0 禁商用）、RedInk（CC BY-NC-SA）、guizang-social-card-skill（AGPL-3.0）**只借鉴设计、不搬代码**。
