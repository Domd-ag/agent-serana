# memory_manager skill

记忆管理 skill，用于让聊天自然调用长期记忆和 working memory。

## 目录结构

```text
memory_manager/
+-- __init__.py
+-- skill.json
+-- SKILL.md
```

## 工具能力

- `memory_save`：保存长期用户记忆。
- `memory_search`：搜索长期记忆、resident memory 和历史线索。
- `working_memory_save`：保存当前会话或目标的临时工作记忆。
- `working_memory_clear`：清空当前会话或目标的临时工作记忆。

## 依赖关系

工具内部通过 `app.memory.MemoryService` 操作数据库；默认使用本地默认用户。

## 维护约定

新增记忆工具时同步更新 `app/memory/README.md`、`skill.json`、`SKILL.md` 和本 README；注意区分长期记忆与 working memory 的作用域。
