# Memory Manager

Serana 的内置记忆适配层。所有读写都通过统一 `MemoryService` 完成。

- 用户明确要求“记住”稳定事实或偏好时，使用 `memory_save`。
- 用户明确询问“之前说过什么 / 你记得什么”时，使用 `memory_search`。
- 当前会话的预算、约束和临时状态使用 `working_memory_save`。
- 用户要求清空当前临时状态时，使用 `working_memory_clear`。

普通上下文续答、统计、合计和推理不调用记忆搜索工具，直接使用已注入的当前会话上下文回答。
