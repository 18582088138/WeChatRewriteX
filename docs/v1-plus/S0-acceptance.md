# V1.0+ S0：基线与验收记录

日期：2026-10-30（Asia/Shanghai）。分支：`dev/v1-plus-s0`。
**状态：基线检查及实施设计完成，设备/网络/团队信息待补充，阶段待用户验收和合并。S1 尚未开始。**

## 1. 四类交付状态

- S0 实施设计：已完成，[S0-design.md](S0-design.md)；成员账号/团队协作代码尚未实施。
- 开发机基线验证：已执行，99 项后端与7项浏览器检查通过，前端构建通过；不是未来团队功能验收。
- 真实小主机部署：未执行，尚未获得设备信息或访问条件。
- 外地成员验收：未执行，尚未确认成员与访问方案。

S0 信息缺项列于下方，不将建议值记为用户确认；阶段完成需补充信息、核对运行路线和用户验收。

## 2. Git 与正式版核对

- 本轮开始时 `HEAD=dev/v1-plus`，`main`、`origin/main`、`origin/dev/v1-plus` 和 `v1.0^{commit}`
  均指向 `af63c6162f33de6a3834a60b168d714ea707b215`，`main...HEAD` 无源码差异。
- 实际执行 `git ls-remote origin refs/heads/main refs/heads/dev/v1-plus refs/tags/v1.0` 和
  `git ls-remote origin 'refs/tags/v1.0^{}'`，远程基线一致。`v1.0` 是 annotated tag，
  标签对象 `c6008329cd215cc1550b6270603bf3cf77d5aa21` 与 peeled commit 不同属正常情况。
- `app/__init__.py` 是产品版本唯一来源，当前 `1.0.0`；旧 V1.18 和 PROGRESS 历史测试数量不作为本轮验收证据。
- 仓库根及上级路径未发现 AGENTS.md；已阅读 README、PROGRESS、ARCHITECTURE、DEPLOY、VERSIONING、V1.0 和开发计划。
- 入口未提交项：`docs/dev-plan-v1-plus.md`、`web/web/package-lock.json`。
  原始计划原文不修改，本轮将其纳入阶段提交以便其他机器复现；`web/web/` 保留、不暂存、不删除。
- 已从 `dev/v1-plus` 创建 `dev/v1-plus-s0`，不执行 merge、标签或 Release 操作。

## 3. 当前开发环境（不能代替部署设备信息）

- 工作区：`C:\Users\kundaxu\Downloads\xkd\Self_Project\WeChatRewriteX`，Windows AMD64，PowerShell。
- 当前机器属于公司或家庭：待用户确认。实际 GitHub 远程读取可用，不推断其他网络服务均可用。
- 默认 `python` 为 `C:\Program Files\Python315\python.exe`（3.15.1），执行 `python -m pytest --version`
  报缺少 pytest。没有向全局 Python 安装依赖。
- 验证改用已有 `C:\Users\kundaxu\AppData\Local\miniforge3\envs\xkd_env_py312\python.exe`，
  Python 3.12.13，SQLite 3.53.1；与 CI 的 Python 3.12 主版本匹配，不宣称所有依赖/系统与小主机等价。
- Node 24.13.0、npm 11.6.2，现有 `web/node_modules` 可用。满足 Node ≥20.19，未执行新的 npm 安装。
- 本轮 `Get-Command docker` 未找到命令；Docker 构建/运行未验证。不据此判断小主机有无 Docker。

## 4. 实际检查与证据

检查针对正式版基线；本轮只有文档变化，无新增业务测试或实现。

1. 工作区根执行：

   ```powershell
   & 'C:/Users/kundaxu/AppData/Local/miniforge3/envs/xkd_env_py312/python.exe' -m pytest -q tests/
   ```

   退出码0，输出 `99 passed in 54.05s`，无 skipped。
   覆盖现有离线 API 流程、文稿版本/CAS、迟到 AI/审稿、任务所有权、旧库迁移与离线备份恢复、
   素材归档/引用、网络与文件登记边界、四平台导出及 Chromium 卡片渲染。
   `tests/conftest.py` 使用临时数据/日志根、屏蔽真实模型及搜索密钥、离线桩；不代表真实模型网络调用通过。

2. `web` 目录执行 `npm run build`：退出码0；`vue-tsc --noEmit` 和 Vite 构建通过，2701 modules，
   Vite 输出 `built in 15.65s`（仅 bundler 阶段，不含 typecheck 总耗时）。更新的是忽略的 `web/dist`。

3. `web` 目录执行：

   ```powershell
   $env:WENSHU_TEST_PYTHON = 'C:/Users/kundaxu/AppData/Local/miniforge3/envs/xkd_env_py312/python.exe'
   npm run test:e2e
   ```

   退出码0，输出 `7 passed (38.3s)`。测试代码见 `web/e2e/workflow.spec.ts`，
   独立服务器由 `scripts/e2e_server.py` 使用临时根、空密钥和 `127.0.0.1:8011` 启动。
   覆盖未保存输入/事件刷新、保存冲突、创作/审稿更新、设置刷新、宽窄屏侧栏和既有媒体显示。
   图文导出/定稿是原有流程，不是新增人工审核账号流转。

4. `git diff --check` 通过；正式标签本地与远程 peeled commit 相同。
   后续阶段分支提交不移动正式标签；阶段 push 与最终状态以 Git 实际记录为准。

浏览器输出有 Node `NO_COLOR`/`FORCE_COLOR` 警告和一次 Windows asyncio Proactor
`ConnectionResetError: [WinError 10054]` 回调日志，测试仍全部通过。
该日志未做修复，作为 S1/S6 长连接断线/重连的运维观察项，不将它记为服务稳定性验收通过。
本轮没有执行 Docker、Linux、冷安装包、Windows exe 重构建、真实 AI 服务或真实主机/跨网络验收。

## 5. 待用户补充（问题卡已发出）

- 当前机器：公司/家庭、实际网络限制。
- 部署小主机：系统/版本、CPU 型号与架构、内存、可用磁盘、Docker 或服务管理能力；
  是否兼用其他服务、能否常开/关闭休眠、是否有管理员权限；已有访问方式与可操作时间。
- 家庭网络：实测或套餐上行、路由器管理权限、公网 IPv4/IPv6、运营商 NAT；未知项可先标待查。
- 成员：首批人数和大致城市、管理员与维护负责人、能否安装私有组网客户端、是否要求手机浏览器。
- 业务规则：是否接受旧项目默认管理员私有、负责人分配创作/审核/只读能力、默认禁止作者自审。
- 备份：另一设备/异地存储候选、可用空间、密钥访问负责人和可接受维护窗口。

未依赖这些信息的基线验证与数据/API 设计已完成。具体部署路线、容量门槛和有效排期待信息齐后更新，
真实设备相关操作不在未知条件下执行。若硬件未就绪，S1 可在明确路线后先做开发机隔离验证。

## 6. 数据变化、遗留项与回退

- S0 无数据库迁移、无新增成员或权限、无真实数据导入/服务启动；只新增开发计划归档、设计/验收文档与 PROGRESS 入口。
- 保留用户 `.env`、配置、真实数据库/素材与未跟踪 `web/web/`；测试仅使用临时数据根。
  前端构建更新忽略的 `web/dist/`，测试报告位于忽略的 `web/test-results/`。
- 本轮识别的实施缺口：SSE 全局广播、文件登记缺项目授权、任务结果含配置/本机路径、共享令牌无成员身份、
  修改接口可省略 revision、旧迁移固定写 schema v3、公共素材默认可见、无独立人工批准。
  这些均是 S2～S5 的待开发范围，未宣称本轮已修复。
- 配置与密钥完整备份、持久配置根、跨网络访问、管理员恢复、性能门槛和试运行需后续实测。
- 回退本轮只需保留未提交工作后切回 `dev/v1-plus`；本轮无 schema 变化，无需恢复业务库。
  若要恢复先前前端构建，在原分支 `web` 中重新构建；不得清理真实数据或删除未跟踪用户文件。
- 下一步：补充信息并确认 S0 文档，用户将阶段合入 `dev/v1-plus` 后，再从该分支创建 `dev/v1-plus-s1`。
  阶段合并及最终 `main` 合并由用户执行。
