# MiniMax 去敏请求与官方依据

核对日期：2026-11-05；通过用户提供的代理访问，不记录密钥、授权头或音色样本。

2026-11-06 追加：用户更新 `.env` 后，第二次短文本 TTS 成功，32 发送字符/60 计费字符，4.899417 秒 MP3 完整解码通过，估算 0.021 元。累计 TTS 2 次/64 发送字符、克隆 0 次；本次没有查询声音，详见 [S3 补验](S3-api-recheck-2026-11-06.md)。以下为首次验证的原始记录。

本轮请求账本：

- 已有声音清单：`POST https://api.minimaxi.com/v1/get_voice` **1 次**，HTTP 200，provider code 0，返回 4 个已有 ID。用户选择 `bambi_check_20261101_155031`。请求中的 `voice_type=voice_cloning` 是已有声音的查询类别，此入口没有创建声音。
- 同步合成：`POST https://api.minimaxi.com/v1/t2a_v2` **1 次**，模型 `speech-2.6-hd`，用户指定声音，**32 个发送字符**，服务商返回 **1008（余额不足）**。未得到音频、没有重试；实收费用未核对，不把估算当作已扣款。
- 声音克隆、样本上传、远端声音删除 **各 0 次**；本轮真实 LLM 请求 **0 次**。本地固定测试音调用不计入真实 API 请求，不证明真人读音/自然度。

已读取国内与国际官方同步合成、声音查询、计费和错误文档，部分旧入口发生跳转。保存的官方 Markdown 摘录核对 Bearer、hex、模型参数、usage_characters 和错误码；中国区汉字计 2 个计费字符，speech HD 3.50 元/万计费字符、Turbo 2.00 元/万计费字符。程序保留发送字符与 provider usage，估算费率按模型绑定；实际账户计费仍以服务商为准。

官方入口：[同步语音合成](https://platform.minimaxi.com/docs/api-reference/speech-t2a-http)、[已有声音查询](https://platform.minimaxi.com/docs/api-reference/voice-management-get)、[按量计费](https://platform.minimaxi.com/docs/guides/pricing-pay-as-you-go)。完整原始正文和去敏响应保留在本机忽略的 `build/v2-evidence/`，没有重复请求查询或追加付费验证。

短文本同步合成和完整解码已由上述 2026-11-06 补验确认；2～5 分钟主题人声、重点读音/自然度/音色、手机与跨网络试听下载仍待实际验收。
