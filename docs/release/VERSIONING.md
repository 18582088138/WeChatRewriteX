# 发布与版本管理建议（文枢 - 自媒体 Studio）

> 目的：让「改代码 → 发版本 → 用户拿到包」成为一条不依赖记忆的流水线。
> 本文件是建议与约定，已落地的部分会标注 ✅。

## 1. 版本号：语义化 + 单一来源

- 采用 [SemVer](https://semver.org/lang/zh-CN/)：`主.次.修订`（如 1.6.0）。
  新增功能升次版本；纯修复升修订；不兼容变更升主版本。口头编号「V1.6」对应包版本 `1.6.0`。
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
- 产物统一进 `release/`（已 gitignore），文件名带版本号；
- `SHA256SUMS.txt` 随包发布，用户可校验下载完整性 ✅。

## 4. Git 标签与 GitHub Release

- 发布即打 tag：`git tag v1.6.0 && git push origin v1.6.0`——tag 是「这个包对应哪份代码」的唯一锚点；
- 在 GitHub 网页 Releases → Draft new release：选 tag、贴 CHANGELOG 本节、上传
  `release/*.zip` 与 `SHA256SUMS.txt`（仓库只存源码，二进制附件走 Releases，不进 git 历史）；
- 后续如装 `gh` CLI，可一行完成：`gh release create v1.6.0 release/*.zip --notes-file CHANGELOG 片段`。

## 5. 分支与节奏（个人项目够用即可）

- `main` 永远可发布；功能开发开短分支 `feature/xxx`，测绿再合；
- 发布节奏建议：功能攒到「用户能感知」再发版，避免为仪式感发空包；
- hotfix：从 tag 拉 `hotfix/v1.6.1` 分支，修完合回 main 并立即发修订版。

## 6. 数据兼容与回滚

- 用户状态 = `resource/` + `config/` + `.env`。升级只需换 exe，数据目录不动 ✅
  （运行根三态设计保证了这一点）；
- DB schema 变更时必须有迁移路径（当前 `schema.sql` 全量初始化；后续变更建议加
  `PRAGMA user_version` 版本标记 + 迁移脚本，变更一次累加一次）；
- 回滚 = 换回旧版本 exe（数据向后兼容是设计红线：新版本产生的数据不保证旧版可读）。

## 7. 发布前检查清单（贴墙用）

1. `__version__` 已升；2. CHANGELOG 已写；3. `python -m pytest tests/` 全绿；
4. 前端有改动则 `cd web && npm run build`；5. `python tools/pack_release.py`；
6. 冒烟：解压 zip 到干净目录跑启动脚本；7. `git tag` + push + GitHub Release 上传产物。
