# forge 目录

Forge 是具体执行层 agent，负责处理 Aide 分发过来的子任务。

## 目录结构

```text
forge/
+-- __init__.py
+-- forge.py       ForgeAgent 实现
+-- manifest.json  Forge 元数据、技能和工具声明
```

## 主要职责

- 根据任务内容推断 `research`、`planning`、`analysis`、`build`、`question`、`general` 等类型。
- 为不同任务类型选择对应的执行模板。
- 返回结构化执行结果，供 Aide/Serana 汇总。

## 入口文件

- `forge.py`：实现 `ForgeAgent`。
- `manifest.json`：描述 Forge 的展示名、类型、实例上限、可用技能和工具。

## 维护约定

新增任务类型时，先更新 `forge.py` 的类型推断与执行分支，再检查 Aide 和 Serana 是否需要识别同一类型。
