# memory 目录

这里实现 Serana 的记忆系统，包括长期事实、resident snapshot、working memory、历史检索、上下文注入和 consolidation。

## 目录结构

```text
memory/
+-- __init__.py
+-- consolidation.py  从对话中提炼可长期保存的信息
+-- facts.py          用户 profile facts 的增删改查
+-- history.py        会话历史读取和格式化
+-- injector.py       把记忆组装进 prompt 上下文
+-- resident.py       常驻记忆和 resident snapshot
+-- retriever.py      多来源记忆检索
+-- service.py        统一 MemoryService 门面
+-- working.py        当前会话/目标的临时工作记忆
```

## 记忆分层

- `ProfileFactsManager`：长期用户事实，例如偏好、身份信息、常用地点。
- `ResidentMemoryManager`：把稳定事实同步成常驻上下文，并维护 resident snapshot。
- `WorkingMemoryManager`：只服务当前会话或目标的临时状态。
- `HistoryManager`：读取聊天历史作为上下文。
- `MemoryRetriever`：从 facts、history、resident memory 中检索相关信息。
- `MemoryInjector`：生成可注入 Serana prompt 的记忆片段。
- `MemoryConsolidationService`：从聊天中判断是否要沉淀为长期记忆。
- `MemoryService`：对 API、skill 和 agent 暴露统一入口。

## 修改建议

- API 读写 facts：先看 `facts.py` 和 `service.py`。
- Serana prompt 里缺上下文：先看 `injector.py`、`resident.py`、`working.py`。
- 自然语言触发记忆工具：先看 `skills_store/memory_manager/` 和 `agents/serana/nodes.py`。

## 维护约定

新增记忆类型时要同时考虑数据库模型、`MemoryService` 门面、prompt 注入和 skill/API 暴露；新增或调整模块后同步更新本 README。
