# 开发进度交接（PROGRESS.md）

> **给下一次会话**：这份文档 + `docs/design/` 设计文档 + git log 即可恢复全部上下文。
> 读法：先看本文件「当前状态」与「下一轮该做什么」，细节查设计文档对应章节。

## 当前状态（截至 2026-10-28）

**功能完整可用、本地运行中的 M1+ 产品；V1.5 校准 + V1.6 工程化 + V1.7 审稿优化均落地**
（需求方口头编号与文档编号的映射：其「V1.5 打包」=本文档 V1.6；其「V1.6 审稿优化」=本文档 V1.7）。
测试 32 项全绿。git remote：github.com/18582088138/WeChatRewriteX，已推送。

- 启动：`C:\Users\75203\miniforge3\envs\xkd_env_py312\python.exe -m app` → http://127.0.0.1:8000
  （conda 环境在 miniforge3，Git Bash 里 `conda activate` 不生效，直接用绝对路径 python）
- **产品已更名「文枢 - 自媒体 Studio」**（短名 文枢；pip 包名/进程标识 `wenshu`）
- 前端已构建于 `web/dist/`（改前端后需 `cd web && npm run build`，再 `python scripts/build_assets.py`）
- 数据根 `resource/`（gitignore）；日志 `log/wenshu.log`（gitignore，常驻持久化）
- 一键打包：`python tools/pack_release.py`（默认全平台，产物进 release/）

## V1.8 发布页优化（2026-10-28）

1. **exports 平台文件夹跳转**：发布页平台条目生成完毕出现「打开文件夹」按钮 →
   `POST /api/articles/{aid}/exports/reveal {platform}` 系统文件管理器直达 exports/<平台>/。
2. **Playwright 浏览器随包（免 install）**：冻结态启动时若发布包含 `playwright-browsers/`
   则注入 `PLAYWRIGHT_BROWSERS_PATH`（`config.setup_playwright_browsers`）；打包流水线
   `bundle_browsers()` 把本机 `ms-playwright/chromium_headless_shell-*` 拷进包；
   bat/ps1 仅在包内与用户目录都没有浏览器时才跑 `--install-browser` 兜底。
   实证：屏蔽用户目录缓存后冻结 exe 卡片渲染正常产出。
3. **发布页同步创作信息**：总结/关键词/参考链接（读 draft meta，与创作分页同源）。
4. **参考链接**：写入侧去重（creator + apply_ops 走 `blocks.dedupe_ref_links`，URL 归一化
   保序去重）；展示统一「标题 - 链接地址」+ 新窗口打开（rel=noopener）；展示层再去重兜底。
5. **日志补齐**：`AgentBase.progress()` 统一进度事件（stage.progress + 文件日志），
   创作/审稿/导出/批量抓取全部逐步打点（此前只有收集有）。
6. **GIF 调研结论（跳过）**：卡片=HTML→Playwright 静态 PNG 截图，动图嵌入只会定格首帧，
   PNG 卡片原理上不支持动图 → 按需求分支「不支持则跳过」，不改动。若未来要动图，
   方向是单独出 GIF/视频物料（imageio-ffmpeg 已在依赖链可复用），而非嵌入卡片。

## V1.7 审稿优化与 bug 修复（2026-10-28）

1. **冻结态收集崩溃修复**：PyInstaller 漏收 justext 的 stoplists 静态资源（trafilatura
   正文抽取依赖）→ 收集炸 `WinError 3: _MEIxxx/justext/stoplists`。spec 补
   `collect_all(justext/certifi/curl_cffi)`；已在干净目录用真实文章实证收集全通过。
2. **资料收集入口改造**：列表页「录入链接」→「资料收集」；弹窗双模式（网页链接 /
   本地文件·文件夹）。本地模式：`POST /api/articles` url 可空（title 立档为
   `local://` 文章）→ `POST /api/articles/{aid}/materials/upload-batch` 批量上传，
   自动识别分流（md/txt→文章；html/pdf 抽取正文→文章；图片/视频/音频按扩展名；
   其余→其他），local:// 文章上传成功即 NEW→COLLECTED。
3. **版本机制重构（废弃 V1.4 主动保存模式）**：**定稿=版本节点**。定稿生成
   `origin=finalized` 快照并进回滚列表（dao.list_draft_versions 的 saved 标记含
   finalized）；定稿后仍可编辑（编辑端点自动 FINALIZED→EDITING，不再是只读锁）；
   已定稿无改动再定稿幂等（`already_finalized`）；再次定稿生成全新独立版本。
   前端创作页「保存版本」按钮已移除，版本区改列定稿快照。
4. **审稿交互重构**：意见列表改**右侧悬浮窗**（可收起为角标，正文阅读区全宽）；
   条目按**对应段落顺序**排列（¶n 角标定位，无锚排尾、同级严重度优先）；
   点击条目平滑滚动+高亮对应段落（原有能力保留）；审稿阅读区**双击文本块即编辑**
   （与创作分页同一保存链路，改动达标自动触发复审）。

**顺手修的存量 bug**：跨文章 sha256 去重饿死——两篇文章收同一原文时，后收文章的
primary 素材被去重到首篇名下，导致第二篇「素材库为空」无法创作。ingest_bytes/
ingest_text 改为：同归属命中才复用，跨归属命中则同文件克隆新行（不重复占盘），
文本正文随行克隆进 FTS。

## V1.6 工程化发布（2026-10-27）

启动、打包、日志、更名配套：

1. **运行根三态统一**（`app/core/config.py`）：仓库态=仓库根；PyInstaller 冻结态=exe 旁
   （只读资产在 `_MEIPASS/wenshu_assets`）；pip 安装态=启动 cwd（资产在包内 `app/_assets`）。
   首启 `ensure_runtime_assets()` 自动播种 config/、web/dist、.env.example 到运行根（幂等）。
2. **日志标准化**（`app/logging_setup.py`）：常驻持久化（不再由 dev.mode 门控——dev.mode
   只管设置页日志面板）；仅 INFO/ERROR 两档（`log.level` 切换）；`log.path` 自定义路径，
   默认 `log/wenshu.log` 按日期轮转（`log.keep_days` 保留）；格式 时间/级别/[模块]/内容，
   ERROR 带堆栈（含 `sys.excepthook` + `threading.excepthook` 兜底）。
3. **打包产物**：`pyproject.toml`+`MANIFEST.in` → sdist `dist/wenshu-1.6.0.tar.gz`
   （含内置资产，提供 `wenshu` 命令）；`packaging/wenshu.spec` + `packaging/launcher.py`
   → Windows 单文件 `文枢.exe`（~141MB，冒烟通过：健康检查/SPA/播种/日志全过）；
   `packaging/build_linux_binary.sh`（Docker 内出 Linux 二进制）与 `Dockerfile` 已就绪，
   **本版按需求方要求未实际构建 Linux 二进制/镜像**，需要时一条命令出包。
   构建前置：`python scripts/build_assets.py`（归集 config+web/dist+.env.example → app/_assets）。
4. **一键启动**：`scripts/start_windows.bat`（仅 Windows）/ `scripts/start_linux.sh`
   （仅 Linux）：目录自检自建、首启自动装 Chromium（`--install-browser`）、失败写
   `log/start.log` 并给排查提示。
5. **更名**：代码内 APP_NAME/APP_FULL_NAME/APP_ID（app/__init__.py）、FastAPI 标题、
   前端 title 与头部（宽屏显示全称，`hidden md:inline`）、设置注释、README、
   scraper 标题；环境变量 `WRA_DATA_DIR` → `WENSHU_DATA_DIR`（旧名兼容回退）。
6. **交付文档**：`docs/release/ARTIFACTS.md`（产物清单+选型理由）、
   `docs/release/DEPLOY.md`（Windows/Linux/Docker/pip 部署 + 故障排查）、
   `docs/release/VERSIONING.md`（版本管理建议：SemVer+版本号单一来源+CHANGELOG+tag/
   GitHub Release+发布检查清单）。
7. **一键打包**：`tools/pack_release.py`（默认全平台：测试门槛→资产归集→sdist→exe→
   组装 zip→SHA256SUMS，统一进 release/；`--skip-*`/`--reuse-exe` 开关）。
   版本号单一来源 `app/__init__.py::__version__`（pyproject dynamic 读取）。
8. **bat 运行失败实修**：根因=LF 行尾（cmd 括号块解析错乱）+ 非 ASCII 跨编码；
   重写为纯 ASCII + CRLF + `for %%F in (*.exe)` 通配发现主程序 + 端口 8000~8005
   自检顺延。已实测：dev 服务占 8000 时 bat 自动用 8001 起服、浏览器自动打开。
   sh 同步端口顺延逻辑。

发布包组装（不入库，gitignore release/）：`release/文枢-v1.6.0-windows-x64.zip`
= 文枢.exe + 启动文枢.bat + docs/；Linux 包结构同（二进制 + start_linux.sh）。

## V1.5 真实案例校准（2026-10-26）

## V1.5 真实案例校准（2026-10-26）

用 3 篇量子位真实选题（OpenAI 断网训练/云生意格局/Anthropic 奇点演讲）完整走通
「收集→创作→审稿→定稿→四平台导出」，并据审稿报告做了一轮系统性校准：

**发现的问题（全部实锤根因）**
1. attribution 误报洪水：citations 是块级结构化字段（`Block.citations`），但审稿 prompt
   只渲染块文本 → 审稿模型永远看不见引用标注，每篇误报 4~5 条「未标注 citations」。
2. 证据截断假 blocker：证据窗口 3000 字符，长文关键数据在窗口外 → 「未见此数据」误判
   （44 万亿 GDP 在 3243 字符处被截断，冤产生 blocker）。
3. 幻觉引文：审稿模型引用稿中不存在的话（如「为了保证系统的绝对安全」）并据此判违规。
4. 配置不一致：创作分页按 `cards.max_chars_per_page=380` 打包，审稿硬编码 300 字/页 →
   每篇 3~4 条无解 warn；公众号正文词数无检查（两篇超 1800 字上限无人报）。

**修复（代码+prompt 双侧）**
- `reviewer.py`：小红书分页上限改读 `cards.max_chars_per_page`；新增正文词数对
  `variants.wechat_mp.word_range` 检查（超上限 warn/不足 info）；证据窗口
  `review.evidence_chars` 默认 8000；新增 `_ground_llm_items` 引文接地校验——
  审稿条目 message 中成对引号片段归一化（去空白/引号/markdown 强调符/HTML 标签）后
  必须在稿件或证据语料中逐字找到，找不到即降一档 severity 并留痕「已自动降级」。
- `config/prompts/reviewer/review.j2` 重写：渲染块 citations；attribution 只判
  「关键事实块无 citations」；severity 分级明确（blocker=直接矛盾/凭空捏造/严重合规，
  范围放大/口径差异=warn，修饰词省略不改含义不报）；「证据节选未覆盖」只 warn 且仅关键主张；
  引文约定「」=稿件、『』=证据、逐字复制；ai_flavor 豁免风格包规定的开头功能句。
- 同步：`rules.md`/`05-publishing.md`/`06-style-guide.md` 的小红书每页 300→380；
  `rules.md` 数据引用改为「citations 字段结构化标注」描述。

**校准效果（同三篇稿件前后对比）**
- blocker 7→0（原 7 个中 6 个是假阳/严重级错配，1 个真阳「十五个月二十多倍」自相矛盾
  以 info 保留可见）；warn 40→18，留存项均真实可操作。
- 首轮复审曾出现真阳被误降级（证据原文 `**4000亿**` 的 markdown 强调符破坏逐字包含）
  → 归一化加 strip `*_`#` 与 HTML 标签修复，已入测试。
- 三篇均无 force 定稿，四平台导出各 32 文件（小红书卡片 10 页/篇，页脚页码一致）。

`scripts/calib_drive.py` 是可复用的校准驱动（submit/status/jobs/advance），下轮校准换
SEEDS 链接即可。

## 产品是什么

AI 行业要闻「收集 → 创作 → 审稿 → 人工定稿 → 多平台发布包导出」的本地助手。
输入一篇文章链接，三个 Agent（收集/创作/审稿）流水线处理，人工在工作台审阅编辑，
定稿后导出公众号/小红书（分页卡片组图）/微博/X 的发布包（手动发布；自动推送是二阶段）。

## 已验证能跑通的真实链路

- 收集：公众号正文+图片抓取、DuckDuckGo/Bing 零配置扩搜、arXiv 论文、Pexels/Pixabay
  媒体补充、纯规则过滤（文本垃圾/低质图/pHash 去重）、mpvideo.qpic.cn 签名直链视频实体下载
  （Vidu 文章实测 21 图 + 4 视频实体落盘）
- 创作：DeepSeek 成稿（风格包 tech-evangelist 人设），勾选素材集合创作、段落级 AI 重写、
  资料融合插入、必配图兜底、小红书分页
- 审稿：六维 checklist（排版规则/禁用词/SimHash 撞重阈值 blocker/LLM 事实来源合规 AI 味），
  采纳即修复 + 高亮，blocker 禁定稿可强制留痕
- 编辑：Notebook 工作台（双击编辑/点外保存/增删块/拖素材入位/标题副标题置顶/图注编辑），
  块级增量版本 + 主动保存版本（备注）+ 一键回滚
- 发布：四平台导出包（公众号 HTML 可复制进编辑器 / 小红书卡片 PNG / 微博短文 / X 推文串）

## 架构速查（勿推翻）

| 层 | 位置 | 要点 |
|---|---|---|
| 领域模型 | `app/core/models.py` | **DraftDoc 块模型**（稳定 id 块列表）是编辑/审稿/分页/导出的地基 |
| 版本 | `app/services/draft_service.py` + `app/storage/dao.py` | 块级增量：`draft_changes` 差异日志 + `drafts` 稀疏 checkpoint；HEAD=checkpoint+重放；**主动保存版本**（origin=manual+note）才进回滚列表 |
| 状态机 | `app/core/statemachine.py` | NEW→COLLECTING→…→DONE/FAILED；定稿后复审为软审（不动状态） |
| 队列 | `app/pipeline/queue.py` | 双泳道线程（collect/ingest/deepsearch ∥ create/review/publish），`UPDATE...RETURNING` 原子认领，崩溃恢复 |
| LLM | `app/services/llm/router.py` | OpenAI 兼容薄路由（deepseek/ark/openrouter 优先级+fallback+schema 校验重试+成本日志）；key 在 `.env` |
| 检索 | `app/services/rag/index.py` | FTS5 trigram（短语化+LIKE 兜底）+ embedding API 可选（无 key 降级纯 FTS） |
| 爬虫 | `app/services/crawl/` | wechat_mp（自写 #js_content 解析+视频音频提取）/ trafilatura / arxiv / fixture；插件 registry |
| 搜索 | `app/services/search/` | tavily→bing→duckduckgo→arxiv；Bing 需解 /ck/a 跳转 base64 |
| 媒体 | `app/services/media/` | 下载（防盗链 Referer）、filter.py 纯规则过滤、stock.py 图库补充、video_dl.py（yt-dlp） |
| 主题提取 | `app/services/textmine.py` | **纯规则禁 LLM**：标题分句×3+型号 token+引号词+实体词典+高分核心句 |
| 卡片 | `app/services/cards/render.py` + `themes/tech-note/` | HTML 模板→Playwright 截图 1080×1440，浏览器内分页+溢出校验；「编辑部快报」平面风 |
| 配置 | `config/` | prompts/（Jinja2 按 Agent 分目录）、styles/tech-evangelist/（风格包）、settings.yaml；DB settings 覆盖层优先级最高 |
| 前端 | `web/src/` | Vue3+NaiveUI+Tailwind；views: ArticleList/Workbench/Settings；components: MaterialsPanel/BlockEditor/ReviewPanel/PublishPanel/StatusChip |
| 独立工具 | `tools/scraper/` | CLI + GUI 服务（127.0.0.1:8765），复用爬虫与过滤规则，不连库 |

## 数据布局（resource/，唯一数据根，gitignore）

```
resource/
├── app.db(.shm/.wal)     # SQLite：文章/素材索引/版本/审稿/任务/成本
├── style_reference/      # 13 篇范文（风格蒸馏参照）
├── common/               # 公共素材库：图片/视频/音频/其他/ + inbox（无 reference）
└── <标题-YYYYMMDD-HHmm>/  # 项目文件夹（创作定题后自动改名为拟定标题）
    ├── reference/<文章标题>/{page.html,content.md,meta.json,图片/,视频/,音频/,其他/}
    ├── inbox/  drafts/   # drafts: vNNN checkpoint + runs/ Agent 运行记录
    ├── exports/<平台>/   # 发布包（含 xhs_cards/ 卡片）
    └── notes.md          # 收集报告
```

素材统一命名 `NNN-类型-来源标题前5~8字.ext`；`materials.path` 相对 resource/；
`articles.lib_dir` 记录项目文件夹名；`articles.selected_json` 存创作会话勾选。
**文件不能在资源管理器手动移动**（DB 路径会失效），要走应用内操作。

## 关键设计决策（拍板记录）

1. 发布一阶段只做导出包手动发布；API/RPA 自动推送归后续阶段。
2. 风格 = 「轻松诙谐但严谨科学的技术传火人」人设（14 篇范文蒸馏，规则见 `config/styles/tech-evangelist/` 与 `docs/design/06-style-guide.md`）。
3. 审稿撞重双保险：创作侧 prompt 预防 + 审稿 SimHash/Jaccard 双阈值 blocker。
4. 水印图当前可用仅打标（后续再处理）。
5. LLM 与搜索均可降级运行（无 key 走保底稿/仅原文/纯 FTS），测试全程离线可跑。
6. GUI 遵循 taste-skill app-screen 规范（已装 `~/.zcode/skills/taste-skill`）：1px 边线无阴影、近黑主按钮、朱红 #C63B24 accent 克制、无渐变无 emoji。

## 踩过的坑（别再踩）

- **PyInstaller 两坑（V1.6）**：① 入口脚本不能是包内 `__main__.py`（相对导入报
  no known parent package）→ 用包外跳板 `packaging/launcher.py` 绝对导入；② 包内运行期
  数据文件（`schema.sql`、卡片主题 theme.html/yaml）必须显式进 spec datas，否则冻结态
  FileNotFoundError。
- **bat 铁律（V1.6）**：cmd 的 bat 必须**纯 ASCII + CRLF 行尾**。LF 让 if/for 括号块
  解析错乱（报错形如 `'yedExpansion' 不是内部或外部命令`）；非 ASCII 按 OEM 代码页
  解析，UTF-8/GBK 互读必乱甚至 0x5C 尾字节吃换行。中文 exe 名用通配符发现。
- **PyInstaller 静态资源（V1.7）**：trafilatura 依赖 justext 的 stoplists 数据文件——
  只 collect_all(trafilatura) 不够，数据在 justext 包里；同类还有 certifi(cacert.pem)、
  curl_cffi(DLL)。冻结态跑通收集才算验证（单测测不到）。
- **sha 去重饿死（V1.7）**：ingest 的 sha256 去重若直接返回他篇素材 id，后收同源的
  文章会「素材库为空」。去重只省文件不省行：同归属复用、跨归属同文件克隆新行。
- **项目文件夹名粒度到分钟（V1.8 发现，已知边界）**：同名标题同分钟创建的两篇文章会共用
  项目文件夹（lib_dir 无唯一化）。修法方向：article_dir 生成时撞名追加短 id 后缀
  （注意 `_DT_SUFFIX` 校验与改名联动）。测试侧已用 tag 参数隔离。
- **复现实验污染生产库（V1.7）**：绕过 pytest 直接跑 `create_app()` 的调试脚本会写
  生产 resource/！调试脚本开头先 `os.environ["WENSHU_DATA_DIR"] = 临时目录`。
- **PowerShell 5.1 两坑（V1.6）**：不支持 `&&`（报错「不是有效的语句分隔符」，逐行或
  用 `;`）；不搜索当前目录（脚本必须 `.\xxx.bat` 前缀）。PS 用户给原生
  `scripts/start_windows.ps1`（发布包内「启动文枢.ps1」），执行策略拦截用
  `-ExecutionPolicy Bypass -File` 绕过；ps1 同样只写纯 ASCII。
- **Git Bash 调 Docker（V1.6）**：`-v $PWD:/src` 会被 MSYS 路径转换搞坏（`/src` 变
  `C:/Program Files/Git/src`）→ `cygpath -w` 转 Windows 路径 + `MSYS_NO_PATHCONV=1`。
- **Bash `&` 优先级**：`A && B && C & sleep N` 会把整条 && 链后台化——构建+冒烟必须
  拆成独立命令调用。
- **审稿 prompt 三坑（V1.5）**：① LLM 看不见的字段等于不存在——citations 不渲染进 prompt，
  attribution 维度必然误报；② 证据截断窗口外的数据会被判「不存在」→ 冤 blocker，
  窗口默认 8000 且 prompt 声明「节选未覆盖≠不存在」；③ LLM 会幻觉引文，必须程序侧
  逐字接地校验兜底（`_ground_llm_items`）。
- **引文归一化**：爬取的 markdown 带 `**强调**`，LLM 引文时会剥掉 → 接地校验的归一化
  必须同步 strip `*_`#` 与 HTML 标签，否则真阳条目被误降级。
- **同一数字多处定义必漂移**：分页容量曾同时存在 300（审稿硬编码/rules.md/设计文档）与
  380（cards 配置）两套值——规则侧一律读配置，文档同步改。
- **curl 中文 body**：Windows Git Bash 下 curl `-d` 带中文必 400（编码被 mangling），
  API 驱动一律走 python 脚本（scripts/calib_drive.py）。
- **FTS5 MATCH** 遇标点语法错误 → 短语化包裹 + LIKE 兜底（dao.search_materials_fts）。
- **任务重试**：阶段准入必须含自身进行态 + 同态迁移幂等，否则重试被防呆误杀。
- **mpvideo.qpic.cn 直链**：藏在文章 inline JS，`&` 转义为 `\x26amp;` 必须先反转义再匹配，
  否则截断丢签名必 403（`services/crawl/wechat_video.py`）；readtemplate 条目在有直链时跳过防重。
- **草稿不存在 bug**：增量版本后前端持有的 `<aid>-vN` 不是实体行，`resolve_head_row` 回退 HEAD。
- **拖拽 500**：copy 端点 INSERT 列数与占位符必须逐个数齐（18↔18）。
- **sha 去重**：复制会合法产生同 sha 多行，去重必须查全部再按 scope 过滤。
- **grid 自动放置**：fixed 定位的标记元素也是 grid 子项，会挤扁中央列——显式 grid-column。
- **heredoc 转义**：`\\x26`、三引号 docstring、`\n` 在 Bash heredoc 里会被吃——复杂补丁写成临时 .py 文件执行。

## 已知边界 / 待办候选

- 懒加载 wxv_ 视频号无直链 → 链接型素材（iframe 弹窗 + 外跳兜底）；要实体需本机微信凭证方案。
- 免费搜索端点（Bing/DDG）有反爬波动；稳定可配 TAVILY_API_KEY。
- embedding 语义检索/撞重需要 OpenAI 兼容 embedding key（如火山方舟 doubao-embedding），未配则纯 FTS。
- 卡片只有 1 套主题；移动端 PWA 打磨未做；移动端轻编辑是二阶段。
- 创作聚焦受勾选素材影响大（混主题会偏题）——这是特性不是 bug。
- M2 候选：公众号 API/RPA 推送、watchdog 素材监听、成本看板页、多卡片主题、字符级 diff。

## 下一轮怎么接

1. 本目录说「继续」即可——项目记忆 + 本文档 + git log 提供全部上下文。
2. 校准轮已做过一轮（V1.5）。再做就换 `scripts/calib_drive.py` 的 SEEDS 跑新选题，
   重点观察：attribution warn 是否仍偏多（可收紧创作侧 citations 覆盖率）、
   演讲类稿件的 fact warn 密度（当前 13 warn/篇，仍偏吵）。
3. 推 GitHub：remote 已配好，`git push` 即可（`.env`/`resource/`/`log/` 已在 gitignore）。
4. 若要二阶段发布：读 `docs/design/05-publishing.md` 的 Publisher 插件接口与降级链。
