# data/api 目录说明

这里是 Android 端的后端协议层。

## 文件职责

- `ApiService.kt`
  - Retrofit 接口定义
  - 普通 JSON 请求
  - multipart 上传技能 ZIP
- `RetrofitClient.kt`
  - Retrofit / OkHttp 初始化
  - 流式聊天事件解析
  - artifact URL 拼接

## 当前技能相关接口

- `GET /skills`
- `POST /skills/{skillName}/enable`
- `POST /skills/{skillName}/disable`
- `GET /skills/{skillName}/lifecycle`
- `POST /skills/{skillName}/scope`
- `POST /skills/{skillName}/update`
- `DELETE /skills/{skillName}`
- `POST /skills/marketplace/install`
- `POST /skills/upload`（multipart，本地 ZIP 导入）

## 维护约定

- 后端返回结构变化时，先同步这里的 DTO
- 如果是文件上传或下载，优先在这里明确协议形式，再交给 ViewModel 调用

## 流式聊天

- RetrofitClient.streamChatMessage 使用专用 OkHttp client，SSE 读取不设置 30 秒 readTimeout，用来承载 HTML 演示生成、审批等待等长任务。
- `done` 事件会直接携带后端最终的 `thinking_blocks` 和 `tool_calls`，ViewModel 可以先把工具卡片和演示 artifact 放进当前消息，再用 debug 接口做最终补水。
- Audit insights 使用 `planning_stages` 表示后端 planning flow 阶段。
- Audit insights 也包含 `tool_result_names`、`tool_result_statuses`、`tool_result_schema_versions` 和 `artifact_kinds`，用于按统一工具结果协议展示或调试。
