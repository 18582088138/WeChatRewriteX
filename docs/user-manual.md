# 使用手册（M1 本地版）

## 1. 安装与启动

前置：已安装 [miniforge/miniconda] 与 Node.js ≥ 18。

```bash
# 后端（首次）
conda activate xkd_env_py312          # 或任意 Python 3.12 环境
pip install -r requirements.txt
python -m playwright install chromium

# 前端（首次）
cd web && npm install && npm run build && cd ..

# 配置密钥
copy .env.example .env                # 填入 DEEPSEEK_API_KEY 等

# 启动
python -m app                          # 打开 http://127.0.0.1:8000
python -m app --host 0.0.0.0           # 局域网/手机访问（请同时在 .env 设 APP_ACCESS_TOKEN）
```

开发模式（前端热更新）：终端 A `python -m app`，终端 B `cd web && npm run dev`，访问 `http://127.0.0.1:5173`。

## 2. 三分钟上手

1. **录入链接**：首页右上角「+ 录入链接」，粘贴公众号/新闻/arXiv 链接。录入即自动开始收集。
2. **看素材**：卡片进入工作台 → 「素材库」tab。可粘贴网址/上传文件补充素材；也可以直接把文件拷进
   `data/library/articles/<文章标题>/inbox/`（公共库拷 `data/library/common/inbox/`），再点「扫描 inbox」。
   每篇文章的素材（原文/参考/图片/视频）都在 `data/library/articles/<文章标题_短id>/` 这一个文件夹里，
   按「原文/参考/图片/视频/文档」分项存放。
3. **洗稿**：顶部点「开始洗稿」，生成 v1 草稿。
4. **编辑**：「创作」tab。默认阅览模式；**双击段落**进入编辑（失焦自动存为新版本）；**单击选中**后右侧可
   AI 重写/缩写/扩写/自定义指令；**双击图片**可从素材库换图。素材库勾选文本段落 →「融合插入到文案」
   （插入到当前选中段落之后）。
5. **审稿**：「审稿」tab 查看六维 checklist（排版/事实/来源/合规/撞稿/AI味）。逐条「AI 修复 / 采纳标记 /
   忽略」；点击条目会在右侧文档高亮对应段落。处理完点「定稿」。**存在阻断项（blocker）时默认禁止定稿**，
   确认无误后可强制定稿（会留痕）。
6. **发布**：「发布」tab 勾选平台 →「生成发布包」。发布包就在文章素材文件夹里的 `exports/<平台>/`，
   按其中 README.txt 手动发布。公众号直接浏览器打开 `article.html` 全选复制进编辑器；
   小红书按序上传 `cards/` 下 PNG。

## 3. 常用配置（设置页 / `config/settings.yaml`）

| 场景 | 位置 |
|---|---|
| 搜索窗口天数（默认前后 3 天） | 设置页 → 收集，或 `collect.search_window_days` |
| 参考篇数 3~5 可调 | `collect.ref_count.min/max` |
| 目标词数 | 设置页 → 洗稿，或 `rewrite.target_word_count` |
| 收集→洗稿→审稿自动连跑 | `pipeline.auto: true`（人工审阅关卡始终保留） |
| 查重阈值 | `review.originality.simhash_warn/block` |
| 语言风格（人设/禁用词/范文） | `config/styles/tech-evangelist/`，调优见 `docs/design/06-style-guide.md` |
| LLM 渠道与模型档位 | `config/settings.yaml` 的 `llm:` 段；密钥在 `.env` |
| Prompt 模板 | `config/prompts/<agent>/`，可手改，改完即生效 |

## 4. 没有密钥时能用吗？

能跑通流程但内容质量降级：无 LLM key → 洗稿产出「要点罗列保底稿」；无搜索 key → 收集只抓原文
（标记素材稀缺）；无 embedding → 语义检索降级为全文检索。配置任意一个 OpenAI 兼容渠道即恢复正常。

## 5. 常见问题

- **公众号链接抓取失败**：检查链接是否失效；个别文章需微信环境，暂不支持的可复制正文，用「上传文件 /
  粘贴文本」手动入库（`.txt/.md`）。
- **图片粘贴进公众号后不显示**：防盗链所致，发布包 `media/` 目录有原图，手动上传替换。
- **卡片文字溢出**：发布 tab「重新生成卡片」；仍溢出说明该页文字过多，回「创作」压缩对应段落。
- **数据在哪备份**：整个 `data/` 目录即全部状态，定期复制即可；`.env` 不在其中，需另行保管。

## 6. 目录导览

```
config/            提示词与参数（可手改，热生效）
data/library/common/                      公共素材库
data/library/articles/<文章标题_短id>/     文章文件夹: 原文/参考/图片/视频/文档 + inbox + exports(发布包)
data/drafts/       文案版本落盘（vNNN.md / .json + runs/ Agent 运行记录）
docs/design/       设计文档 · docs/api.md 接口 · docs/user-manual.md 本手册
```
