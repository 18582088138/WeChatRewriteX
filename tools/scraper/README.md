# media-scraper · 独立素材爬取小工具

单篇抓取文章的文本、图片、视频、音频素材，输出到本地文件夹。**独立于主应用**：
不连数据库、不写素材库，复用项目的爬虫与过滤规则（trafilatura/公众号解析/yt-dlp/纯规则过滤）。

## 用法

```bash
conda activate xkd_env_py312

# CLI：抓取到 tools/scraper/output/<标题-时间>/
python tools/scraper/scraper.py "https://mp.weixin.qq.com/s/xxxx"
python tools/scraper/scraper.py "https://example.com/post" -o D:\tmp\out

# GUI：启动独立界面
python tools/scraper/server.py            # → http://127.0.0.1:8765
python tools/scraper/server.py --port 9000
```

过滤规则（纯规则，不调用 LLM）：剔除广告/求关注类文本行、「相关阅读/往期回顾」尾巴、
图标/二维码/追踪图（URL 特征 + 尺寸/比例/文件大小），图片 pHash 近似去重。
输出目录结构：`content.md page.html 图片/ 视频/ 音频/ _summary.json`。
