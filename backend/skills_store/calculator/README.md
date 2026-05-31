# calculator skill

基础计算 skill，服务自然语言中的简单四则运算。

## 目录结构

```text
calculator/
+-- __init__.py  工具函数实现
+-- skill.json   工具 manifest
+-- SKILL.md     Serana 使用说明
```

## 工具能力

- `add`：加法。
- `subtract`：减法。
- `multiply`：乘法。
- `divide`：除法，包含除零保护。

## 使用位置

Serana 会在 lightweight route 或 tool selection 中把简单算数请求映射到这里。

## 维护约定

新增计算工具时同步更新 `skill.json`、`SKILL.md` 和本 README；返回结构保持 `result`/`summary` 风格，方便前端和 Serana 复用。
