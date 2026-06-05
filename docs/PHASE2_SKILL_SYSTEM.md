# 第二阶段：Skill 系统

## 目标

为 Serana 后端提供统一、本地可管理的扩展能力，使 Python 工具、受控脚本和 instruction skill 都能通过同一套生命周期和对话路由接入。

## 当前能力

- 从 `backend/skills_store` 扫描和加载 Skill 包。
- 使用 `skill.json` 描述身份、作用域、能力标签、工具 schema、权限和运行方式。
- 支持安装、更新、启用、停用、卸载和 SkillHub 市场接入。
- 工具统一注册为 `skill_name.tool_name`。
- 对话优先选择相关的本地可执行 Skill，失败后才走 Browser 兜底。
- `runtime=instruction` 的 `SKILL.md` 会按当前问题相关性注入上下文。

## 三种运行方式

### Python Skill

`runtime=python` 会把入口模块加载到后端进程，并注册 manifest 中声明的 Python 函数。适合项目内置、经过代码审查且需要直接访问后端模块的能力。

### Script Skill

`runtime=script` 由 `PythonScriptAdapter` 在独立 Python 进程中执行。它适合需要跨平台运行、又不应直接加载到后端进程的外部能力。

协议：

1. 入口必须是 Skill 目录内的 `.py` 文件。
2. stdin 接收一个 JSON 对象：

```json
{"tool":"lookup","arguments":{"query":"上海"}}
```

3. stdout 必须只返回一个 JSON 对象：

```json
{"summary":"查询完成","result":{"value":"..."}}
```

4. stderr 仅用于内部诊断，不直接展示给用户。

安全限制：

- 不使用 shell，不允许子进程。
- 默认禁止网络和写入。
- 仅支持显式声明 `network`、`filesystem_write`。
- 写入范围始终限制在 Skill 自身目录。
- 隔离敏感环境变量。
- 校验工具参数 schema。
- 限制输入、输出、执行时长和并发实例数。

### Instruction Skill

`runtime=instruction` 不执行文件，只把相关 `SKILL.md` 作为领域指导注入 Serana。市场包即使附带 shell 脚本，只要没有标准 `runtime=script` 清单，也不会自动执行。

## 当前边界

- Script Runtime 支持 Python adapter，以及经过自动标准化和静态安全检查的 Shell adapter。
- Windows 使用 Shell Skill 前需要一次性安装 Git Bash，或配置 `SERANA_BASH_PATH`。
- 应用级审计和独立进程不是容器级强隔离；来源不可信的代码仍不应被转换为可执行 Skill。
- 已卸载的市场 Skill 不会保留本地工具注册；重新安装后必须具有有效标准清单，或能够由 `SkillStandardizer` 安全转换为唯一入口 Shell Skill，才能作为可执行工具加载。
