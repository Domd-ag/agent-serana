# weather skill

天气 skill，提供指定地点的当前天气和短期预报。

## 目录结构

```text
weather/
+-- __init__.py
+-- skill.json
+-- SKILL.md
```

## 工具能力

- `get_current_weather`：获取当前天气。
- `get_forecast`：获取短期天气预报。

## 数据来源

工具优先尝试公共天气接口，并对地点名、天气描述、温度、湿度、风速等字段做中文化输出。

## 使用位置

Serana 会通过 LLM tool selection 或本地参数归一化把“北京天气怎么样”“明天上海下雨吗”等问题映射到这里。

## 维护约定

调整数据源或地点中文展示时同步更新 `skill.json`、`SKILL.md` 和本 README；返回给前端的摘要应保持中文、简洁、可直接展示。
