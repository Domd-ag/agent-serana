# memory 目录

这里实现 Serana 的记忆系统。当前约定是：长期 memory 只保存可复用要点，例如用户事实、偏好、resident snapshot 和 working memory；原始聊天消息属于会话历史，只能作为上下文证据，不直接作为“记忆结果”返回给用户。

## 目录结构

```text
memory/
+-- __init__.py
+-- artifacts.py      统一 memory artifact：fact、preference、summary、episode
+-- consolidation.py  从对话中提炼可长期保存的用户事实
+-- facts.py          用户 profile facts 的增删改查
+-- history.py        会话历史读取和格式化
+-- injector.py       把 resident、working、facts、会话历史组装进 prompt 上下文
+-- resident.py       常驻记忆和 resident snapshot
+-- retriever.py      记忆检索器，目前显式 memory_search 只面向 facts
+-- service.py        统一 MemoryService 门面
+-- working.py        当前会话/目标的临时工作记忆
```

## 记忆分层

- `ProfileFactsManager`：长期用户事实，例如偏好、身份信息、常用地点。
- `MemoryArtifactManager`：统一存储高密度记忆 artifact，当前支持 `fact`、`preference`、`summary`、`episode`。
- `ResidentMemoryManager`：把稳定事实同步成常驻上下文，避免每轮都做复杂检索。
- `WorkingMemoryManager`：只服务当前会话或目标的临时状态，适合预算、当前任务约束、短期偏好。
- `HistoryManager`：读取聊天历史作为上下文证据，不属于长期 memory artifact。
- `MemoryRetriever`：检索 profile facts 和 memory artifacts；summary 优先，summary 不足时再补 episode。
- `MemoryInjector`：生成可注入 Serana prompt 的上下文片段；会话历史可以进入 prompt，但不能直接作为用户可见的“记忆列表”。
- `MemoryConsolidationService`：先用 LLM 提取候选 artifact，再经过本地 validate / resolve / persist；LLM 输出不会直接写库。
- `MemoryService`：对 API、skill 和 agent 暴露统一入口。

## 行为约定

- 用户明确问“我之前说过什么 / 你记得什么 / 查一下记忆”时，才走 `memory_manager.memory_search`。
- 用户问“继续 / 统计 / 合计 / 估算 / 总共多少钱”等上下文推理问题时，Serana 应使用会话上下文直接回答，而不是把历史问答原样列出来。
- 会话沉淀会生成/刷新 session summary，并保存具体 episode；跨会话检索优先返回 summary，再按需返回 episode。

## 修改导航

- API 读写 facts：看 `facts.py` 和 `service.py`。
- Serana prompt 缺上下文：看 `injector.py`、`resident.py`、`working.py`。
- 自然语言触发记忆工具：看 `backend/skills_store/memory_manager/` 和 `backend/app/agents/serana/nodes.py`。

## 维护约定

新增记忆类型时，要同时考虑数据库模型、`MemoryService` 门面、prompt 注入和 skill/API 暴露；新增或调整模块后同步更新本 README。
