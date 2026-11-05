# 两台机器的交付／验收唯一入口

验证中途结束或性能异常时，按[诊断与交接要求](DIAGNOSTICS.md)采集事实，分别判断机器资源、网络/模型、权限/工具和执行范围。

更新2026-11-01。目标部署机器已经确定为家庭NUC8i5BEH，不再等待另一台主机。公司机提供代码/工具并复核证据，NUC负责实际安装、操作和采集。当前业务候选1.1.0-rc.1、schema6，main仍为正式v1.0。

先读本文件，再读[逐项标准](CASEBOOK.md)、[当前状态](STATUS.md)和[证据模板](EVIDENCE-TEMPLATE.md)。`cases.json`固定编号及依赖，`runs/<run-id>/run.json`固定本次源码/程序/标准，`results.json`是结果账本，`events.jsonl`保留变更历史，`report.md`/STATUS.md是派生摘要。历史复验记录不是本轮正式验收的通过项。

## NUC Agent 的任务要求

请执行以下任务，而不是仅做一次代表性复验后交接结束：

1. 确认自己就在NUC；核对Git改动、实际exe、持久目录、已有服务/账号/真实数据和管理员执行条件。先保护原件，不重装系统、不租云服务器，不强制Docker。
2. 建立唯一run，固定基线；逐项执行CASEBOOK中所有当前可执行的B/L/D/P检查。每项写入真实命令、开始/结束时间、观察结果、证据、数据影响及回退，完成后再判状态。
3. 某项需要主机维护者注销/重启、网络/证书、真实成员、另一设备或试运行自然日时，把具体缺项写为blocked并提出可执行下一步，继续独立检查。不得把“缺另一台小主机”作为理由。
4. 失败先定位并重试，保留第一次失败与修复后的证据。越权、静默覆盖、错误审批绑定、定稿变更、历史引用损坏或无法恢复时停止扩大试用，保留数据并同步问题。
5. 不自动注销/重启用户工作会话，不强行停止未知实例；安排维护者操作窗口。获得既有授权且具备权限的服务注册、隔离测试和维护步骤应继续执行，不把可执行项无故留到下一轮。
6. 不用模拟视口代替真手机、不用本机多账号代替外地成员、不用模型降级路线代替真实模型质量、不用本机小样本秒级恢复代替真实RPO/RTO。阶段分支不连接已升级的真实唯一数据库。

开始工作时请明确回复并记录：**当前机器、repo HEAD、exe内嵌build commit、run-id、计划实际执行的编号、缺失条件、服务是否已有、真实数据如何保护**。模型/Agent版本知道就填，不知道填unknown；不要猜。

## 初始化与安全运行自动检查

从已核对的仓库根逐行执行；路径、实际Conda解释器和账号由NUC实查填写，不照搬公司机绝对路径。

```powershell
git status --short
git fetch origin dev/v1-plus
git switch dev/v1-plus
git pull --ff-only origin dev/v1-plus
conda activate xkd_env_py312
$wenshuRun='nuc-20261101-01'
$wenshuExe='C:\Wenshu\releases\v1.1.0-rc.1\文枢.exe'
python scripts/nuc_acceptance.py init --run-id $wenshuRun --machine-role nuc --agent-label unknown --binary $wenshuExe
$wenshuCommit=(Get-Content "docs/v1-plus/validation/runs/$wenshuRun/run.json" -Raw | ConvertFrom-Json).source_commit
```

exe路径尚未确定时，可先省略`--binary`初始化，再在B02证据中补齐实际build-info和SHA；没有B02证据不能判后续通过。已有本机改动先保留/整理，不reset或强制覆盖。init会拒绝覆盖同名run及未提交的跟踪改动。

自动化优先通过隔离运行器执行，避免NUC shell里已有的生产`WENSHU_RUNTIME_DIR`/团队模式/密钥影响个人模式测试或改动真实配置：

```powershell
python scripts/nuc_acceptance.py run-local --run-id $wenshuRun --suite build --attempt 01
python scripts/nuc_acceptance.py run-local --run-id $wenshuRun --suite backend --attempt 01
python scripts/nuc_acceptance.py run-local --run-id $wenshuRun --suite browser --attempt 01
python scripts/nuc_acceptance.py run-local --run-id $wenshuRun --suite team-browser --attempt 01
```

运行器只执行现有fixture检查；新进程使用全新临时runtime/data/log、父进程个人模式、空外部密钥，生产实例可以继续使用其原目录。build/browser会更新仓库的忽略生成物。原始日志、XML和运行元数据在`build/nuc-acceptance/<run-id>/`。它**不会自动将验收项判通过**；必须读取实际通过/失败/跳过和对应范围。
Node/npm/Playwright依赖未就绪时先核实已有环境，记录安装版本/失败原因；只在所需步骤补安装。不要为此更换用户已指定的Conda环境。绿色产品运行不依赖Python，Python仅用于NUC现有验证环境。

run-local执行期间使用异步终端会话，定期查看日志并汇报，不让Agent长时间阻塞等待。重复测试使用新attempt，保留旧失败。源码/依赖/标准改变后新建run，禁止用旧结果通过新基线。

隔离runtime内复制仓库tests/fixtures合成素材，供旧fixture爬虫按PROJECT_ROOT读取；不复制生产resource或.env。运行期间禁止修改测试代码/标准；运行器结束时再次检查基线，变化会记录baseline_valid=false并返回非零，即使测试进程自身退出0也不能算通过。

浏览器trace/截图仍写入web/test-results或web/team-test-results；首次失败后先复制这些原始材料到本机忽略的build/nuc-acceptance/<run-id>/<suite>-<attempt>-artifacts，再重跑，避免Playwright清理旧输出。它们可能含页面内容，不直接提交Git；共享材料使用已核对的去敏步骤/摘要。

## 记录、证据共享与复核

原始日志、数据库、密钥、会话Cookie、备份、真实文章和模型响应留在NUC本地忽略目录。按EVIDENCE-TEMPLATE整理不含这些内容的事实证据到`runs/<run-id>/evidence/`；可分享已核对的主机probe、去标识的HTTP统计、资源CSV、测试摘要和故障时间线。共享报告只用`.md/.json/.csv/.txt`且≤5MiB。
不得只写“已通过”：说明实际观察、测试范围和未覆盖项。人工实验需要操作人员确认的时间/事实；Agent不可代写未获得的确认。

例如B01实际完成后（先生成并核对该证据文件；示例不是通过预置）：

```powershell
python scripts/nuc_acceptance.py record --run-id $wenshuRun --case B01 --status passed --tested-commit $wenshuCommit --summary '已核对目标NUC、基线、路径和实际执行权限，见证据' --evidence "docs/v1-plus/validation/runs/$wenshuRun/evidence/B01.md"
python scripts/nuc_acceptance.py record --run-id $wenshuRun --case R03 --status blocked --summary '外地成员尚未实际参加' --needed-input '一名外地成员及其设备/网络、测试时段' --next-action '安排30分钟完成R03流程，其他本机项继续'
python scripts/nuc_acceptance.py check --run-id $wenshuRun
python scripts/nuc_acceptance.py report --run-id $wenshuRun
```

状态含义：not_run未执行；running执行中；passed实际范围通过；failed实际执行失败；blocked缺明确条件；not_applicable仅限可选X01且须说明未采用该路线。必做项不能标N/A。通过/失败必须有非空证据，passed必须是本次固定source_commit且前置通过；基线、标准或证据摘要变更使旧结论不能沿用。

本地证据可用`--evidence <本机路径>`记录SHA，但公司机无法读取它：显示local_only，不能直接通过跨机器复核。至少提供一份可读、去敏的shared事实报告；工具只检查结构和SHA，不能证明操作者真的做过手工实验。

shared文本摘要使用`hash_kind=utf8_lf`：去除UTF-8 BOM并统一CRLF/LF，避免Git换行转换误报修改；正文变化仍会失效。本地原件使用`hash_kind=file_bytes`逐字节SHA，原始大小保留作参考，包/备份的校验仍使用其原始逐字节SHA。

公司Agent拉取后阅读共享材料，再逐项复核，不依据status字段或SHA字符串直接接受：

```powershell
python scripts/nuc_acceptance.py check --run-id $wenshuRun
python scripts/nuc_acceptance.py review --run-id $wenshuRun --case B01 --verdict accepted --reviewer company-agent --summary '已阅读实际机器/路径/权限观察及证据，范围满足B01'
python scripts/nuc_acceptance.py report --run-id $wenshuRun
```

证据不足时用`--verdict needs_info`并说明具体补项；NUC补测/补证重新record会将复核重置pending，旧记录仍保留在events.jsonl。不要手改results.json冒充脚本校验通过。

## Git同步规则

每轮先fetch/pull，再核对本机改动与固定run；仅提交验收目录、PROGRESS的简短指向和必要代码修复，绝不`git add .`。

```powershell
git diff --check
git add docs/v1-plus/validation/runs/nuc-20261101-01 docs/v1-plus/validation/STATUS.md
git commit -m 'docs(validation): record NUC actual acceptance observations'
git push origin dev/v1-plus
```

run-id按真实日期/序号取名，每次代码/程序目标或标准变化用新run。两台机器轮流写同一run：NUC写执行事实，公司写复核。不要同时改同一结果文件；push被拒绝时fetch并逐项合并事实，禁止force-push或整文件选ours/theirs抹掉另一台证据。
若有代码修复，保留独立修复分支、提交号和复验，合入dev/v1-plus后对新基线新建run。历史run、S0～S7分支、正式main与既有标签保持可追溯。文档/账本提交推进HEAD但未改变测试代码时，继续使用run.json固定source_commit，运行器会检查代码差异。

## Gate与任务结束

阶段功能对照：S0对应B01/B02；S1对应D01/D03/D04/D05/D06/D07；S2对应L01/D02身份与会话；S3对应L01/L02/D02项目与素材；S4对应L01/L02/D02人工批准和快照；S5对应L01/L02/D07/P02冲突、责任与任务；S6对应D项及R01～R04；S7对应P项、R05和完整复核。同一证据可以覆盖多个阶段，但不要重复相加为独立测试次数。

本账本验收的是固定的集成候选，不能据此声称逐一切换历史阶段分支通过。以后确需逐分支验收时，从各[S0](../S0-acceptance.md)～[S7](../S7-acceptance.md)记录读取对应commit/标准，在独立checkout/runtime运行各阶段自身测试，单独记录分支/commit/证据；不得用旧阶段程序读取NUC已升级schema6的唯一数据。历史阶段复验与本账本集成验收分开报告。

- local_reported：NUC报告全部本机必做项通过，仍待共享材料复核。
- local_reviewed：本机必做项均有共享材料且已复核，可用于判断受控试用准入，不能代替外地/手机/长期验收。
- remote_reported / remote_reviewed：外部与试运行项的对应状态。
- final_reviewed：本机和外部项都已复核；X01明确未采用或实际选用后通过复核；仍需用户最终验收和正式发布决定，脚本不授权合入main/发布。

`check`退出0表示结构/证据摘要有效，**不表示全部验收完成**；`check --gate local_reviewed`等指定门槛时，未达到返回2，数据错误返回1。
PowerShell中查看Python的`$LASTEXITCODE`；若Agent的终端包装器把非零统一显示为失败，仍需保留原生退出码和JSON的errors/gates，区分“门槛未达到”与“证据数据错误”。
NUC本轮结束条件：所有当前可执行项已执行并记录；其余每项有确切缺项、负责人/下一步；共享材料已commit/push，公司机能读取。没有真实执行的项保持待验收，不能因本机回归通过直接宣称M4或最终版本验收完成。
