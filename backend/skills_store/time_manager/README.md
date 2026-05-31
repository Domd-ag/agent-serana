# time_manager skill

本地时间和时区 skill，处理当前时间、时区转换、时长计算和日期信息。

## 目录结构

```text
time_manager/
+-- __init__.py
+-- skill.json
+-- SKILL.md
```

## 工具能力

- `get_current_time`：获取指定 IANA 时区当前时间。
- `convert_timezone`：把时间字符串转换到目标时区。
- `calculate_duration`：计算两个时间之间的时长。
- `get_day_info`：获取日期、星期、是否周末等日历信息。

## 使用位置

Serana 会把“现在几点”“今天星期几”“两个时间差多久”等自然语言问题映射到这里。

## 维护约定

新增时间工具时同步更新 `skill.json`、`SKILL.md` 和本 README；注意默认时区与用户地区预期保持一致。
