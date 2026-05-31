# aide 目录

Aide 是 Serana 的协调层 agent，负责把已委派的任务整理成可执行批次，并管理重试与 Forge 分发。

## 目录结构

```text
aide/
+-- __init__.py
+-- aide.py        AideAgent 实现
+-- manifest.json  Aide 元数据、技能和工具声明
```

## 主要职责

- 根据子任务内容推断任务类型。
- 将复杂任务组织成批次。
- 协调 Forge 执行并汇总结果。
- 在失败时提供有限重试和降级结果。

## 入口文件

- `aide.py`：实现 `AideAgent`。
- `manifest.json`：描述 Aide 的展示名、类型、实例上限、可用技能和工具。

## 维护约定

修改 Aide 执行策略时同步检查 `agents/README.md` 中的 agent 流程描述；新增 manifest 字段时也要确认 `app/agents/base.py` 的模型是否支持。
