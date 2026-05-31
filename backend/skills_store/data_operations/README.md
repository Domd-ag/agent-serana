# data_operations skill

本地文本和数据处理 skill，适合不需要外部服务的轻量数据整理。

## 目录结构

```text
data_operations/
+-- __init__.py
+-- skill.json
+-- SKILL.md
```

## 工具能力

- `text_stats`：文本长度、词数、行数等统计。
- `json_pretty`：格式化 JSON 字符串。
- `extract_keywords`：从文本提取简单关键词。
- `word_frequency`：统计高频词。
- `base64_encode`：文本转 Base64。
- `base64_decode`：Base64 转文本。

## 维护约定

新增数据处理工具时同步更新 `skill.json`、`SKILL.md` 和本 README；工具应保持纯本地、无副作用。
