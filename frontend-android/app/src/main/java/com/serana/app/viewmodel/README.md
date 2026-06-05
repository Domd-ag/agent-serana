# viewmodel 目录说明

这里放页面状态和与后端交互的编排逻辑。

## 当前重点

- `ChatViewModel.kt`
  - 负责聊天流式消息、审批事件、会话刷新。
  - 实时合并 `thinking`、`thinking_block`、`tool_call`、`error` 和最终 `done` 事件。
  - 浏览器工具步骤会先流式追加到当前助手消息，再由落库后的调试数据校准。
- `SkillsViewModel.kt`
  - 负责技能列表刷新、远程安装审批、远程更新审批、生命周期状态加载、范围切换、本地卸载审批和 ZIP 导入。
- `SettingsViewModel.kt`
  - 负责服务器连接与 LLM 配置切换。
  - 服务器地址写入 Android 本地配置；LLM Base URL、API Key、模型写入当前服务器。

## 维护约定

- 页面展示需要的短期 UI 状态优先放在这里。
- 审批两步流在这里闭环：先提交审批，再继续原动作。
- 如果后端新增技能动作状态，优先先补这里的状态机，再改页面展示。
- 流式聊天的 `tool_call` 和 `done.tool_calls` 必须按 `id` 去重，避免同一个步骤在 UI 里重复出现。
- 新增后端 SSE 事件时，同步检查 `RetrofitClient`、`ChatViewModel` 和聊天页执行摘要展示。
