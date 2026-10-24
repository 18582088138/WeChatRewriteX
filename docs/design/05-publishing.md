# 05 · 多平台发布

> **已拍板（2026-10-24）：第一阶段所有平台统一「导出发布包 + 手动发布」**（exporter 插件），不接公众号 API、不做小红书/微博 RPA；自动推送草稿箱作为第二阶段开发任务。下文的能力矩阵与降级链是二阶段的完整设计，一阶段只实现 `exporter` 与接口骨架。

## 现实约束（调研结论，设计前提）

| 平台 | 草稿箱能力 | 可行路径 | 风险与备注 |
|---|---|---|---|
| **微信公众号** | ✅ 官方 `draft/add` 接口，但**仅限认证公众号**；个人订阅号无权限 | 有资质 → wechatpy 封装官方接口；无资质 → Cookie/RPA 或导出降级 | 官方接口带 IP 白名单；`wechat-article-exporter` 因官方断供停更的教训——必须可插拔降级 |
| **小红书** | ❌ 无任何官方发布 API | Cookie + Playwright RPA（social-auto-upload / MediaCrawler 式登录态复用） | 违反平台条款风险、风控掉线；默认仅导出卡片组图包，RPA 由用户显式启用并自担风险 |
| **微博** | △ 官方 API 需应用审核，个人基本拿不到发布权限 | RPA 或导出 | 微博视频 extractor 脆弱，视频类内容优先导出 |
| **X** | ❌ 无草稿概念（只有直发/定时） | 官方 API v2（有 key 时）「确认后发」；或导出推文串 | 与「草稿箱」语义不符：界面文案改为「确认后发送/复制」，绝不静默直发 |

**设计基调**：发布层对所有平台统一「推送到草稿/待确认区」语义；平台不支持草稿的，要么显式用户确认后发送，要么只导出内容包。**任何情况下应用不替用户做最终公开发布**。

## Publisher 插件接口

```python
class Publisher(Protocol):
    platform: str
    def capabilities(self) -> Capabilities:
        # {draft: bool, schedule: bool, media_upload: bool, direct_post: bool, max_images: int, ...}
    def prepare(self, doc: DraftDoc) -> Variant: ...      # 平台变体生成
    def push(self, variant: Variant) -> PushResult: ...   # 入草稿箱/导出
    def check_auth(self) -> AuthStatus: ...               # 凭证/登录态体检
```

内置实现：

| 插件 | 方式 | 说明 |
|---|---|---|
| `wechat_mp_api` | 官方 API | 需 appid/secret（`.env`），封面图上传 → 草稿 → 返回草稿 id |
| `wechat_mp_rpa` | Playwright + Cookie | 无资质号的降级路径，登录态扫码获取、本地缓存 |
| `xhs_rpa` | Playwright + Cookie | 卡片组图 + 标题正文填入创作者中心存草稿；默认关闭 |
| `x_api` | 官方 API | 推文串；界面需二次确认 |
| `exporter` | 纯本地 | 所有平台的兜底：导出「文本 + 素材 + 使用说明」zip/文件夹，附一键复制按钮 |

**降级链**：`api → rpa → exporter`，任一环节失败自动给出下一级选项，失败原因写入 `publish_jobs.result_json`。

## 平台变体生成规则（Rewriter 产出 + Publisher `prepare` 适配）

| 平台 | 标题 | 正文 | 媒体 | 其他 |
|---|---|---|---|---|
| 公众号 | 标题候选其一，≤64 字 | 完整稿，Markdown → 公众号主题 HTML（doocs/md 式） | 正文内嵌图，封面 2.35:1 主图 + 1:1 次图 | 摘要取 `one_liner`；注明「素材来源」段 |
| 小红书 | ≤20 字标题 + emoji 克制使用 | 分页卡组：每页 ≤300 字，3~9 页；正文区放 `one_liner` + 要点 | 卡片 PNG（3:4，1080×1440） | 话题标签 3~5 个 |
| 微博 | 无标题 | ≤140 字精华 + 链接/图；长文走「头条文章」导出 | ≤9 图 | 话题 #AI# 等 |
| X | 无标题 | 推文串：首条 hook（one_liner）+ 分条要点 + 来源链接 | ≤4 图/条 | 默认英文/中文双语候选可配 |

## 卡片组图生成（小红书核心体验）

管线（自写实现，参考 guizang-social-card-skill 的模式，注意其 AGPL 协议不可直接搬运）：

```
DraftDoc.xhs_pages → 选 CardTheme → 渲染单文件 HTML(每页一个 <section>)
→ Playwright 无头浏览器逐页截图 1080×1440 PNG
→ 自动校验: 文字溢出 / 最小字号 / 对比度 / 每页密度
→ 不合格页自动调整(缩字号/换版式/重分页) → 入库为「导出素材」
```

- 主题 = 插件（HTML+CSS+分页规则+字体声明），设置页可预览切换。
- 校验脚本独立可测：溢出检测用 DOM `scrollHeight vs clientHeight`，密度按字符数/面积比。
- 封面页单独模板（大标题 + 主图 + 关键词条）。

## 发布配置（设置页）

- 每平台一张账号卡：方式选择（API/RPA/仅导出）、凭证状态体检、默认开关。
- 公众号 API：`WECHAT_MP_APPID` / `WECHAT_MP_SECRET` 存 `.env`，IP 白名单提示。
- RPA 类：扫码登录向导（Playwright 弹出浏览器 → 用户扫码 → 缓存 storage_state），登录态有效期巡检，掉线提醒重登。

## 开放问题

1. ~~公众号资质~~ **已拍板**：一阶段统一导出包手动发布，不考虑 API；自动发布归二阶段。
2. ~~小红书 RPA / X API 额度~~ **已拍板**：暂时没有，同样走导出包；二阶段再议。
