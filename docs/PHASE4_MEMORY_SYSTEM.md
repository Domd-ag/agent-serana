# 第四阶段：Memory 系统

## 当前能力

- Profile Facts：保存稳定用户事实和偏好，并同步到 resident snapshot。
- Working Memory：按会话或目标隔离临时状态。
- Memory Artifact：保存 `fact`、`preference`、`summary`、`episode` 四类高密度要点。
- Summary-first Retrieval：优先检索事实、偏好和摘要，摘要不足时再补 episode。
- Memory Injection：把 resident、working、当前会话历史和相关长期记忆分层注入 prompt。
- Background Consolidation：用户回复持久化后，在后台执行 LLM extractor 与本地 validate / resolve / persist。

## 稳定性约定

- LLM 输出只生成候选 artifact，不能直接写入数据库。
- LLM 合法返回空候选时停止沉淀，不使用规则制造无意义记忆。
- LLM 不可用、超时或格式无效时才启用保守规则兜底。
- 同一个事实或偏好 key 的新值会刷新旧 artifact，避免新旧偏好同时参与检索。
- `fact` / `preference` 属于全局长期记忆；`summary` / `episode` 和 conversation working memory 属于具体会话。
- 删除会话时同步删除该会话的 scoped memory。
- 后台任务由统一 tracker 管理；应用退出时等待短时间，超时后安全取消。

## 后续增强

- 为长期 artifact 增加更强的语义向量检索。
- 增加用户可见的长期记忆审阅、纠正与删除入口。
- 对低置信度冲突引入显式待确认状态，而不是直接刷新。
