# V1.0+ S1：实现与验收记录

日期：2026-10-30（Asia/Shanghai）。阶段分支`dev/v1-plus-s1`，起点为用户合并S0后的`1a54ae8`。
**状态：代码及开发机隔离验证完成，部署材料完成；真实小主机待验证，阶段待用户验收/合并。S2未开始。**

## 1. 交付范围与四类状态

- 代码实现完成：独立持久运行目录、缺失配置播种/升级保留、当前程序前端、完整实例备份/隔离恢复、
  ready存储检查、Windows后台UTF-8输出；复用已有单实例锁和任务恢复，不新建worker体系。
- 开发机等价验证完成：Windows AMD64、Python3.12.13、SQLite3.53.1；真实CLI子进程、隔离数据根、
  规则/降级图文流程、四平台导出、重启/强制终止恢复、备份/恢复及安装版wheel均已执行。
- 真实小主机部署未执行：家庭硬件/系统/网络/访问仍待查。Docker/systemd/Windows任务是部署材料，不能记为实际安装通过。
- 外地成员验收未执行：成员账号、权限和人工批准还需S2～S5，本阶段仅维护者验证，不用共享令牌邀请团队。

没有TTS、视频制作、自动发布、PostgreSQL或独立worker开发。既有媒体显示保留。
操作与安装步骤见[S1维护手册](S1-operations.md)。

## 2. 代码与运行行为

- `app/core/config.py`：通过`WENSHU_RUNTIME_DIR`/CLI选择独立运行根；配置只补缺失文件，
  个人settings/prompts/风格/.env不会被新版默认配置覆盖；相对数据路径以运行根解析。
- `app/__main__.py`：新增`--runtime-dir`、`--data-dir`、`--log-dir`、`--backup`、`--restore`。
  CLI路径在导入配置前确定；恢复目标必须全新，不自动移动原数据；后台输出统一UTF-8。
- `app/main.py`：独立模式的静态前端从当前程序资产提供，不读取持久旧web副本。
- `app/core/environment.py`：运行根/最低磁盘阈值加入需重启项，禁止.env在启动后切换路径及部分更新。
- `app/services/readiness.py`及`api/ops.py`：DB/worker检查外，探测配置/数据/日志写入和最低空间，
  默认64MB，故障ready503而health仍200。外部模型网络不参与liveness判定。
- `app/services/instance_backup.py`：完整离线数据+config+持久.env，复用OS锁/SQLite backup API，
  SHA256完成清单和DB完整性校验，全新目录恢复，拒绝路径逃逸/符号链接/篡改/额外文件。
  仅外部注入的密钥不在文件备份里；日志可另存。
- Docker新增持久配置卷；Compose默认仅主机loopback端口并有退出重启策略。
  Windows任务支持Python或新exe开机/失败重启；systemd模板保持专用用户和loopback。
  部署模板进入sdist和未来绿色包的资料目录，wheel用户另取源码/发布资料中的模板。

## 3. 实际验证与证据

本机使用已有环境，不向全局Python安装依赖。以下最终结果均为实际执行，不引用S0历史数量：

1. 后端完整回归：

   ```powershell
   & 'C:/Users/kundaxu/AppData/Local/miniforge3/envs/xkd_env_py312/python.exe' -m pytest -q tests/
   ```

   最终退出码0，`110 passed in 91.38s (0:01:31)`，无跳过。
   `tests/test_deployment.py`与env新增检查覆盖独立配置/旧前端、ASCII后台输出、不可写/磁盘不足、
   真实CLI双进程拒绝、运行时备份拒绝、本地素材收集→降级创作→规则审稿→CAS编辑→定稿→四平台导出、
   重启文稿/素材/历史/任务记录、完整恢复、篡改/路径拒绝、强制终止后同一job重新认领并完成（attempts=2）。
   强制终止验证使用受控延迟ingest任务，不代表真实模型/下载可以恰好执行一次。

2. 浏览器回归：`web`目录设置`WENSHU_TEST_PYTHON`为上述Python并执行`npm run test:e2e`。
   最终退出码0，`7 passed (54.3s)`，覆盖事件/输入保护、CAS冲突、规则审稿/定稿/四平台导出、历史回滚及界面回归。
   首轮1失败/6通过：原测试先API审稿再点击“去审稿”又排队一次，定稿与刷新发生竞争；trace中没有发出finalize请求。
   已修改为只等待UI发起的审稿任务完成，并断言定稿响应，再验证状态；没有放宽定稿准入。
   首轮Windows连接重置回调与Node色彩警告保留，末轮只有色彩警告，真实长连接故障仍留S6实测。

3. 安装包：已有`build/package-env`（Python3.12.13、setuptools84.2.1、build1.6.1）
   执行`python -X utf8 scripts/build_assets.py`和`python -X utf8 -m build --wheel --sdist --no-isolation --outdir build/s1-validation/dist`。
   wheel/sdist均成功，检查sdist包含requirements及3种部署模板，wheel包含运行代码与前端资产。
   临时验证包沿用产品版本1.0.0，存于忽略的build目录，不上传/替换正式v1.0附件，不创建标签/Release。

4. 全新wheel安装环境：在`build/s1-validation/wheel-env`新建venv并安装本次wheel，
   从`wheel-check`独立目录确认`app.__file__`指向新venv的site-packages，再执行`scripts/package_smoke.py`。
   输出`Installed wheel smoke passed: schema, prompts, frontend, cards and file boundary`。
   验证包内config/prompts、当前前端、schema、卡片及三平台导出/文件边界；源码CLI隔离测试另外覆盖四平台。
   venv继承已有运行依赖，不宣称完成无缓存/联网安装全量依赖或Linux冷安装。
   随后另用安装版CLI成功备份/恢复到新目录。

5. Windows任务模板：PowerShell Parser无语法错误，没有注册/启动任务。
   Compose YAML可解析，没有执行docker build/run或systemd。
   `git diff --check`通过；本轮没有前端产品代码改动，浏览器使用已构建的同源前端，仅修改E2E时序。

第一次用日常Python构建失败：用户site-packages的旧setuptools不能解析新license元数据，且CP1252输出失败。
改用既有独立构建环境和UTF-8后成功，未更改pyproject依赖下限或全局环境。
最终CLI额外补UTF-8输出并有回归，安装版在最终构建中同步更新。

本地证据（忽略、不push）：`build/s1-validation/pytest.txt`、`browser.txt`、`build.txt`、
`wheel-smoke.txt`、`browser-first-failure.zip/.md`、`backup-timing.json`、`backup-dataset.json`。
自动化代码随阶段提交，跨机器可按上述命令重跑；临时报告保留量按本机清理策略管理。

## 4. 备份演练数据与时间

安装版小样本备份：38文件、4,011,464字节，1项目、1定稿、3条发布记录、0素材行/0队列任务。
CLI备份约0.702秒、清单/DB校验与文件恢复约0.400秒（Windows本地磁盘，包含Python命令启动）。
该安装版样本不覆盖大素材和真实团队规模；素材/任务/四平台的恢复由源码独立流程另行验证。
上述时间不含维护窗口、停服务、重启、登录和人工核验，不据此宣布RTO60分钟或RPO24小时验收通过。
真实主机的10～20主题/并行人数/上行/资源峰值待设备就绪后采样，不能从此样本承诺容量。

## 5. 数据变化、边界与回退

- 无新DB迁移，保留schema v3、产品版本基线1.0.0。真实用户数据/配置/.env未迁移，未开启真实数据根应用。
- 新布局只在显式选择的运行目录播种；默认便携布局保留。测试根、构建/安装/备份副本均独立且Git忽略。
  `web/web/`原未跟踪文件保留、不提交、不删除。
- 维护窗口必须停应用及自启动管理器后备份。外部调用重试可能重复收费；不承诺强制取消/恰好一次执行。
- 恢复保留旧配置原文，隔离启动必须显式给运行/数据/日志路径，避免绝对路径指回唯一原件。
- 回退：停S1进程/自启动 → 另存备份后的新编辑 → 使用对应旧程序与完整备份在新隔离根核验 → 切换服务。
  旧exe不识别新参数；回到旧便携模式须按旧布局放置resource/config/.env，不能单切Git或仅换exe。
- 家庭设备接入、真实开机/异常自动重启、手机/内网/跨城市、真实AI服务、Docker/Linux运行、
  另一设备备份及长期容量仍未验收。当前本地备份不能覆盖主机/磁盘整体损坏。
- 下一步由用户验收合并S1到`dev/v1-plus`；之后再从该集成分支创建`dev/v1-plus-s2`开展成员身份与权限代码。
  开发者只提交/push，不执行merge。
