# skills 目录说明

这里是后端 skill 管理层，负责本地技能扫描、启停、导入、卸载、更新、生命周期状态，以及 ClawHub 远程市场对接。

## 文件结构

```text
skills/
+-- __init__.py
+-- clawhub.py    ClawHub HTTP 客户端与远程 skill 转换
+-- loader.py     读取 skill.json / SKILL.md / Python entrypoint
+-- manager.py    SkillManager 单例，负责扫描、安装、暂存、卸载与工具查找
+-- models.py     本地 skill、市场 skill、技能动作响应模型
+-- validator.py  skill 目录结构校验
```

## 当前运行方式

- `backend/skills_store/` 根目录存放项目自带的 bundled skills
- `backend/skills_store/installed/` 存放运行时安装的可卸载技能
- `backend/skills_store/.staging/` 存放等待审批的本地 ZIP 导入暂存包
- `SkillManager.ensure_initialized()` 会同时扫描 bundled 和 installed 两类目录

## 关键流程

1. 扫描本地目录并加载 manifest / 指令 / Python 工具
2. 把工具注册成 `skill_name.tool_name`
3. instruction 类型 skill 的 `SKILL.md` 会注入 Serana prompt
4. ClawHub 市场安装和更新走两步式审批
5. 本地 ZIP 导入也走两步式审批，并在审批前把解压后的 skill 暂存到 `.staging/`
6. 卸载只允许作用于 `installed/` 下的 managed skills，不允许删除项目内置 bundled skills
7. 生命周期状态包含来源、信任状态、生效范围、是否可更新、是否可卸载

## 维护约定

- 修改 skill 包格式时，优先检查 `models.py`、`validator.py`、`loader.py`
- 修改安装/更新/卸载/暂存生命周期时，优先检查 `manager.py`
- 修改 API 返回结构时，同步检查 `app/api/skills.py` 和 Android `SkillsViewModel`
- 如果新增运行时生成目录，记得同步更新根目录 `.gitignore` 和 `skills_store/README.md`
