# 音频 API 契约

项目端点以 `/api/articles/{id}/audio` 开头，复用成员会话、CSRF、项目 revision 与当前 ACL。写入还需要口播自身 revision；409 保留本地输入。普通成员有项目创作/审核权限时可相应操作，`export` 需要 release；声音档案/预算管理只允许管理员。

GET 根端点返回口播产物、声音选项、片段、批次、审核和项目费用。`PUT speech` 保存独立口播，`POST derive` 从图文派生，`POST rewrite` 仅局部改写，`POST review-ai` 持久化 AI 意见；均不自动人工批准。

`GET history` 与 `POST confirm-source` 查看版本/显式确认来源复核。`GET estimate` 不发 TTS 请求。`POST generate` 事务预留后排队，接受可选 paragraph_ids 与显式 confirm_unknown_retry；返回持久 batch ID。重复已完成/在途同输入不增加调用。

`GET batches/{batch}` 与 `POST batches/{batch}/cancel` 查询/取消；reserved/sent/received/unknown/completed/validation_failed/cancelled_unissued 分别存储尝试事实。响应未知不自动重发；未知与永久错误关闭队列自动重试。

`POST reviews` 分 script/audio；`PUT reviews/{submission}` 仅指定审核者决定；comments 与 review-comments 保存/处理意见。批准绑定稿件/来源、片段/文件和声音/混音摘要，过期内容不能批准/正式导出。

`POST export` 发布已批准完整音频包，使用不可变文件清单与原子正式指针；`GET exports/audio.mp3` 为稳定下载入口。`GET files/{file}`、`GET segments/{segment}` 根据数据库项目归属和当前 ACL 服务，内部路径不公开，校验失败/撤权返回 404。

`PUT batches/{batch}/subtitles` 校验段落顺序、有序时间和音频边界，返回新候选 ID，不修改声音/旧文件。新字幕需重新成品确认。

管理员 `/api/audio/settings` 只返回密钥是否配置；`PUT /api/audio/limits` 保存累计额度/模型费率，`POST /api/audio/voices` 与 `PUT voices/{id}` 登记/修改已有声音和项目范围；`POST /api/audio/inventory` 单次只读查询并缓存成功/失败。没有样本上传、克隆创建、声音转换或远端删除端点。
