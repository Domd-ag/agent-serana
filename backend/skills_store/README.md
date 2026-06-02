# skills_store 目录说明

这里是 Serana 后端的本地 skill 文件仓库。

当前旧的内置 skill 已经全部清理，仓库默认不再携带 `weather`、`calculator`、`browser`、`time_manager` 等历史技能包。后续 skill 应通过 SkillHub 下载、远程安装或本地 ZIP 导入重新进入这里。

## 目录结构

```text
skills_store/
+-- README.md
+-- installed/   运行时安装的 managed skills
+-- .staging/    等待审批的本地 ZIP 导入暂存区
```

`installed/` 与 `.staging/` 是运行时目录，内容不应作为默认内置能力提交。

## 维护约定

- 新增默认内置 skill 前，先确认它是否真的应该随项目分发。
- SkillHub 安装的 skill 会被转换为本地 `skill.json` + `SKILL.md` 结构。
- 删除、移动、重命名这里的目录时，同步更新 `app/skills/README.md`。
