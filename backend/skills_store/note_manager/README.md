# note_manager skill

本地笔记 skill，当前使用进程内存存储，适合作为轻量演示或临时笔记能力。

## 目录结构

```text
note_manager/
+-- __init__.py
+-- skill.json
+-- SKILL.md
```

## 工具能力

- `create_note`：创建笔记。
- `get_note`：按 ID 获取笔记。
- `search_notes`：按关键词或标签搜索。
- `update_note`：更新标题或内容。
- `delete_note`：删除笔记。
- `list_notes`：列出最近笔记。

## 注意事项

当前笔记存储在进程内存中，后端重启后会丢失。需要持久化时应改为数据库表或文件存储，并同步更新 manifest 和文档。

## 维护约定

新增或改变笔记字段时同步更新 `skill.json`、`SKILL.md` 和本 README；如果改成持久化，也要更新后端根 README 的功能说明。
