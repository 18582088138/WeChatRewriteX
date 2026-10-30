# 版本管理与发布指南（文枢 - 自媒体 Studio）

## 正式版本起点：v1.0

2026-10-30，将开发迭代 V1.18 的最新 main 确立为首个正式版。
对外名称和 Git 标签使用 `v1.0`，程序、文件名和 Python 包使用 `1.0.0`。
旧 V1.1～V1.18 文档保留为开发历史；本次从源码重新构建正式包。
正式发布页：[v1.0](https://github.com/18582088138/WeChatRewriteX/releases/tag/v1.0)，发布范围见 [V1.0.md](V1.0.md)。

## 四个概念

- **Commit（提交）**：一次保存的源码快照，有唯一编号，可以追溯改动。
- **Branch（分支）**：开发线路，随着新提交推进；`main` 集成已验证的代码。
- **Tag（标签）**：给特定提交起固定名字，如 `v1.0`；发布后不移动、不覆盖、不删除。
- **Release（发行版）**：GitHub 上绑定标签的下载页面，包含说明、安装包和校验文件。

本次 `v1.0` 标签固定发布源码，`codex/release-v1.0` 保留发布分支；以后 `main` 继续开发也不会改变该标签。
分支可以推进，精确锁定交付代码依靠标签。安装包放 Release 附件，`release/`、`build/`、`dist/` 不进入 Git。

## 以后如何编号

V1.0+采用1.1.0-rc.1候选编号；SemVer标签/界面保留该字符串，Python分发元数据按PEP440规范化为1.1.0rc1。
用户已授权阶段dev/v1-plus-s0～s7逐阶段合入dev/v1-plus，分支保留用于事后验收；main与正式v1.0保持不变，完整验收后再确定正式1.1.0发布。
阶段代码/本地回归通过不等于真实家庭部署/远程成员验收。候选产物不得替换v1.0附件，也不能提前声称正式团队验收。

- `1.0.1`：修复 v1.0 的问题，保持已有使用方式。
- `1.1.0`：增加兼容的新功能，例如新增卡片主题。
- `2.0.0`：不兼容变化，例如旧数据格式或 API 无法直接使用。
- `1.1.0-rc.1`：候选测试版，在 GitHub 标记 Pre-release；验收后再发正式版。

正式版本从 1.0.0 起递增，之后不再沿用开发期 1.18 的编号。
产品版本唯一来源是 `app/__init__.py` 的 `__version__`；前端私有构建工程的 package.json 不作为产品版本来源。
本次使用短标签 `v1.0`，以后统一三段标签，如 `v1.0.1`、`v1.1.0`。

## 个人项目的日常操作

从最新 main 开短功能分支，提交并推送，在 GitHub 创建 Pull Request（合并请求），测试通过且检查改动后合回 main。
不必额外维护长期 develop 分支。下面 PowerShell 命令逐行执行，分支名仅为例子：

```powershell
git switch main
git pull --ff-only
git switch -c codex/add-card-theme
# 开发、验证后，只暂存本次改动文件
git add app/services/cards/render.py
git commit -m "feat: add card theme"
git push -u origin codex/add-card-theme
```

## 完成验证后发布（以未来 v1.0.1 为例）

先升级版本号，写 CHANGELOG 和发布说明，提交并推送。使用独立构建环境打包；核对真正生成的 exe/wheel、版本、构建提交及 SHA256。
浏览器 E2E 和 GitHub Actions 也通过后，对待发布提交打带说明的标签：

```powershell
git tag -a v1.0.1 -m "文枢 v1.0.1"
git push origin v1.0.1
```

GitHub 网页：仓库 → Releases → Draft a new release → 选标签 → 填说明 → 上传
`release/v1.0.1/` 中的 zip、wheel、tar.gz、SHA256SUMS.txt → 保存草稿 → 核对 → Publish release。
只上传实际通过验收的附件，不上传解压目录；测试版勾选 Pre-release，正式版设为 Latest。
GitHub 自带的 Source code 是 Git 源码快照，前端需自行构建，不能代替 Windows 执行包。

已有 GitHub CLI 时可使用等价命令（先 `gh auth login` 登录）：

```powershell
gh release create v1.0.1 --verify-tag --draft --title "文枢 v1.0.1" --notes-file docs/release/V1.0.1.md
gh release upload v1.0.1 'release/v1.0.1/文枢-v1.0.1-windows-x64.zip' 'release/v1.0.1/wenshu-1.0.1-py3-none-any.whl' 'release/v1.0.1/wenshu-1.0.1.tar.gz' 'release/v1.0.1/SHA256SUMS.txt'
gh release edit v1.0.1 --draft=false --latest
```

仓库已有 `.github/workflows/ci.yml`，push/PR 会验证后端、浏览器/安装包与 Docker；CI 成功不会自动打标签、生成 Windows 附件或发布 Release。

## 发布后修复与查看旧版

紧急修复从正式标签开 `codex/hotfix-v1.0.1`，修复后升为 1.0.1，再按完整流程发布。
如果 main 已开发后续功能，修复还要通过 PR 或 cherry-pick 同步到 main。
不要覆盖旧标签或用不同内容替换同名正式附件；有新内容就发新修订号。

```powershell
git tag --list
git show v1.0 --stat
git switch --detach v1.0
# 查看完回到日常开发
git switch main
```

切换前先提交或暂存当前改动。要在旧版上继续修改，应从标签新建分支。
Git 恢复源码，Release 恢复程序，用户数据单独备份；切分支不会恢复数据库。

---

## 构建与数据管理约定

> 目的：让「改代码 → 发版本 → 用户拿到包」成为一条不依赖记忆的流水线。
> 本文件是建议与约定，已落地的部分会标注 ✅。

## 1. 版本号：语义化 + 单一来源

- 采用 [SemVer](https://semver.org/lang/zh-CN/)：`主.次.修订`（首个正式源码版本 1.0.0）。
  新增功能升次版本；纯修复升修订；不兼容变更升主版本。
- **单一来源** ✅：版本号只写在 `app/__init__.py` 的 `__version__`；
  `pyproject.toml` 用 `dynamic = ["version"]` 从它读取，`tools/pack_release.py` 也读它。
  改版本号只动这一个文件。
- 界面/接口展示版本：FastAPI `/docs` 标题已自动携带（读 `APP_VERSION`）。

## 2. CHANGELOG：每次发布三句话

已新增 [CHANGELOG.md](../../CHANGELOG.md)，每轮更新记录用户可感知的变化、验证结果和已知问题。
未打包的改动标记“未发布”；正式发布时移除该标记，实际版本号以 `app/__init__.py` 为准。
按 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 精简约定：

```
## [1.7.0] - 2026-11-xx
### 新增 / 变更 / 修复   ← 三类标题固定
- 一句话说清用户感知到的变化（不说实现细节）
```

规则：**打包前 changelog 必须有对应版本的小节**，否则不发。它是用户升级意愿的唯一依据。

## 3. 发布流水线（已工具化 ✅）

```bash
python tools/pack_release.py          # 测试门槛→资产归集→sdist→exe→组装→zip→SHA256
```

- 测试是打包的第 0 步，红灯不出包（可 `--skip-tests` 仅本地调试时绕过）；
- 产物统一进 `release/v<版本号>/`（已 gitignore），文件名带版本号；
- `SHA256SUMS.txt` 随包发布，用户可校验下载完整性 ✅。
- 构建环境使用独立 Python 环境，按 [ARTIFACTS.md](ARTIFACTS.md) 安装运行与构建依赖；
  `--version`、`--build-info` 验证产物，`--reuse-exe` 拒绝未核验或源码不匹配的旧程序。
- 打包脚本就绪不等于所有平台已出包；实际状态记录在 [ARTIFACTS.md](ARTIFACTS.md)。

## 4. Git 标签与 GitHub Release

- 正式发布经确认后打 tag，例如 `git tag v1.11.0 && git push origin v1.11.0`；日常功能分支 push 不自动发布 tag；
- 在 GitHub 网页 Releases → Draft new release：选 tag、贴 CHANGELOG 本节、上传
  本次实际生成的文件与 `SHA256SUMS.txt`（仓库只存源码，二进制附件走 Releases，不进 git 历史）；
- 二进制生成并验收后，才将对应附件发布到 GitHub Release；不把旧包标成新版本。

## 5. 分支与节奏（个人项目够用即可）

- `main` 保持可发布；功能开发开短分支 `codex/xxx`，测绿再合；
- 发布节奏建议：功能攒到「用户能感知」再发版，避免为仪式感发空包；
- hotfix：从 tag 拉 `hotfix/v1.6.1` 分支，修完合回 main 并立即发修订版。

## 6. 数据兼容与回滚

- 用户状态包含 `resource/`、`config/` 和 `.env`；升级前停止服务并备份，不能只复制运行中的 WAL 主文件。
- 数据库迁移已登记 `schema_migrations` 和 `PRAGMA user_version`，旧库迁移前自动保存数据库副本；
  自动数据库副本不能替代完整数据根、配置及密钥备份。
- 回滚需要停止服务，恢复对应版本的完整备份并使用旧程序；升级后新增编辑应先导出保存。
  具体步骤见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 7. 发布前检查清单（贴墙用）

1. `__version__` 已升；2. CHANGELOG 已写；3. `python -m pytest tests/` 全绿；
4. 前端有改动则 `cd web && npm run build`；5. `python tools/pack_release.py`；
6. 冒烟：解压 zip 到干净目录跑启动脚本；7. `git tag` + push + GitHub Release 上传产物。
