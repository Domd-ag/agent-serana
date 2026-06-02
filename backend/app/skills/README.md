# app/skills 目录说明

这里是后端 skill 管理层，负责本地技能扫描、启停、导入、卸载、更新，以及 SkillHub 远程市场接入。

## 文件结构

```text
skills/
+-- __init__.py
+-- loader.py      读取 skill.json / SKILL.md / Python entrypoint
+-- manager.py     SkillManager 单例，负责扫描、安装、缓存、卸载与工具查找
+-- models.py      本地 skill、市场 skill、生命周期响应模型
+-- skillhub.py    SkillHub HTTP 客户端与远程 skill 转换
+-- validator.py   skill 目录结构校验
```

## 当前运行方式

- `backend/skills_store/` 是 skill 文件仓库。
- `backend/skills_store/installed/` 存放运行时安装的 managed skills。
- `backend/skills_store/.staging/` 存放等待审批的本地 ZIP 导入暂存。
- 项目当前不再内置旧的 bundled skills，默认只加载运行时安装内容。
- `SkillManager.ensure_initialized()` 会扫描可用 skill，并把 instruction skill 注入到 Serana 的上下文构建流程。

## 关键链路

1. 扫描本地目录并加载 `skill.json`、`SKILL.md` 和 Python 工具。
2. 把工具注册成 `skill_name.tool_name`。
3. instruction skill 的 `SKILL.md` 会进入 Serana prompt 增强。
4. SkillHub 市场安装和更新走两步式审批。
5. 本地 ZIP 导入也走两步式审批，并先写入 `.staging/`。
6. 卸载只允许作用于 `installed/` 下的 managed skills。
7. 生命周期状态统一包含来源、信任状态、生效范围、是否可更新、是否可卸载。

## 维护约定

- 修改 skill 包格式时，优先检查 `models.py`、`validator.py`、`loader.py`。
- 修改安装、更新、卸载、暂存生命周期时，优先检查 `manager.py`。
- 修改 API 返回结构时，同步检查 [backend/app/api/skills.py](/D:/agent-serana/backend/app/api/skills.py) 和 Android `SkillsViewModel`。
- 新增运行时生成目录时，同步更新根目录 `.gitignore` 和 [backend/skills_store/README.md](/D:/agent-serana/backend/skills_store/README.md)。
