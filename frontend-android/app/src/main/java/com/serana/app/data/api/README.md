# data/api 目录说明

这里是 Android 端的后端协议层。

## 文件职责

- `ApiService.kt`
  - 定义 Retrofit 接口。
  - 包含普通 JSON 请求和技能 ZIP 的 multipart 上传。
- `RetrofitClient.kt`
  - 负责 Retrofit / OkHttp 初始化。
  - 从本地配置读取 Serana 后端服务器地址；未配置时不会发起聊天、技能或设置请求。
  - 负责流式聊天 SSE 事件解析。
  - 负责 artifact URL 拼接和下载地址组装。

## 当前技能相关接口

- `GET /skills`
- `POST /skills/{skillName}/enable`
- `POST /skills/{skillName}/disable`
- `GET /skills/{skillName}/lifecycle`
- `POST /skills/{skillName}/scope`
- `POST /skills/{skillName}/update`
- `DELETE /skills/{skillName}`
- `POST /skills/marketplace/install`
- `POST /skills/upload`

## 流式聊天

- `RetrofitClient.streamChatMessage` 使用专用 OkHttp client，SSE 读取不设置 30 秒 `readTimeout`，用来承载 HTML 演示生成、浏览器观察、审批等待等长任务。
- 当前支持的事件包括 `thinking`、`thinking_block`、`content`、`approval_requested`、`approval_resolved`、`tool_call`、`error`、`done`。
- `thinking_block` 必须保留后端返回的 `timestamp`，聊天页会用它和工具步骤时间计算 `Thought for Ns`。
- `tool_call` 会在后端工具完成时即时到达，ViewModel 可以先把浏览器打开、观察、点击等步骤显示到当前消息里。
- `done` 事件仍会携带最终 `thinking_blocks` 和 `tool_calls`，ViewModel 需要按 id 去重合并，再用 debug 接口校准落库后的最终消息。
- audit insights 包含 `planning_stages`、`tool_result_names`、`tool_result_statuses`、`tool_result_schema_versions` 和 `artifact_kinds`，用于调试统一工具结果协议。

## 维护约定

- 后端返回结构变化时，先同步这里的 DTO。
- 新增流式事件时，同步检查 `RetrofitClient`、`ChatViewModel` 和聊天页展示逻辑。
- 文件上传、下载或 artifact 访问优先先在这里明确协议形式，再交给 ViewModel 调用。
