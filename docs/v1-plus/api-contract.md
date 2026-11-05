# 团队API与并发契约

团队模式开启后整个受保护API/文件入口采用成员Cookie，不接受APP_ACCESS_TOKEN绕过。HTTP修改要求 `X-Wenshu-CSRF`，来源须为同站或明确CORS允许站点；HTTPS会话为Secure/HttpOnly/SameSite。
返回401表示登录/会话失效，403表示成员等级不足，404统一隐藏未授权项目/文件，409表示状态或并发冲突，428表示缺并发token，429表示登录限流。

## 成员与系统

`GET /api/auth/status` 公开返回团队模式/是否初始化；`POST /api/auth/bootstrap` 仅首次临时凭据；`POST /api/auth/login` 返回CSRF和成员公开字段并设置会话Cookie。
`GET /api/auth/me`、`POST /api/auth/logout`、`POST /api/auth/password` 使用当前会话。新账号/重置密码首次更改前不允许业务请求。
管理员 `GET/POST /api/auth/members`，`PUT /api/auth/members/{id}` 更改等级/启用/重置；最后管理员与项目负责人禁用受保护。
`GET/PUT /api/team/settings` 当前自审开关；PUT管理员专用。模型/密钥/配置/日志/导入/公共库管理仅管理员；`/api/capabilities` 只返回成员可用能力。
管理员恢复仅本机停服务CLI，没有远程恢复API。

## 项目与素材

原 `/api/articles`、列表/搜索/历史/费用/任务/导出均保留并按ACL过滤。`GET /api/articles/{aid}/access` 返回负责人、ACLrevision、协作者及当前能力；管理者附可授权成员公开信息。
`PUT .../access` 请求 `expected_revision/owner_id/archived/members`，成员结构 `member_id/can_create/can_review`；冲突409，不改成员等级。
`POST .../access/adopt-jobs` 管理员显式接管旧任务；`PUT /api/materials/{mid}/sharing` 管理员设置 `shared`，仅公共素材。
原素材复制/归档入口继续保留，项目副本有独立实体文件；`/files` 既需已登记文件约束又需当前项目授权，不公开resource/。

## 人工快照

`GET /api/articles/{aid}/human-review` 返回只读提交/意见/候选审核者/批准有效性。
`POST .../human-review` 请求审核者和 `expected_version/expected_revision`；相同待审快照重复提交返回同一ID。
`PUT .../human-review/{sid}` 请求 `status/reason/submission_revision/expected_version/expected_revision/reviewer_id`；状态动作 approved/returned/withdrawn/reassigned。批准和退回必须由指派审核者针对当前同一快照执行。
`POST .../{sid}/comments` 请求anchor（block ID或meta）与message；`PUT .../{sid}/comments/{cid}` 请求status（pending/resolved/declined）、reason及意见expected_revision。
定稿 `/finalize` 保留原force（AI政策），新增exception_reason（管理员人工例外），要求当前version/revision及项目token。不把force视为人工批准。
导出 `/publish`、`/publish/retry`、`/cards` 仅发布授权成员，使用人工关联的定稿和冻结资产。已有文件下载不需要发布权限。

## 写事务与站内记录

项目读响应头 `X-Wenshu-Project-ID` 和 `X-Wenshu-Project-Revision`；业务修改发送 `X-Wenshu-Project-Revision`。服务端短写事务锁内重新检查成员、ACL与token。ACL/人工提交/意见有自身CAS，不使用通用项目写token。
文稿编辑/AI改写/插入/意见采纳/回滚/定稿仍需要正文edit_revision；不传token不允许采用最新值覆盖。
`GET/POST /api/articles/{aid}/lease` 获取/续约占用，POST client_id；DELETE `/lease/{client_id}`释放自身提示，60秒过期。
`GET /api/articles/{aid}/audit` 项目审计；`GET /api/team/audit` 管理员团队审计；`GET /api/team/work` 站内待审/退回/失败。
原 `/api/jobs` 输出发起人和执行耗时，成员响应去除原payload/result（配置/资产快照仅内部使用）。SSE每次交付检查活会话与当前ACL，重连通过API重建状态。

数据库schema6，v4身份/ACL、v5人工快照、v6租约/计时。升级前完整离线备份，迁移DB副本不代替完整素材和密钥备份。
