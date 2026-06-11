# app/skills 目录说明

这里是后端 Skill 管理层，负责本地技能扫描、启停、导入、卸载、更新，以及 SkillHub 远程市场接入。

## 文件结构

```text
skills/
+-- __init__.py
+-- invocation.py        从 SKILL.md / skill.json 提取统一的 `@skill 参数` 调用协议
+-- loader.py            读取 skill.json / SKILL.md，并注册 Python / Script 工具
+-- manager.py           SkillManager 单例，负责扫描、安装、缓存、卸载与工具查找
+-- models.py            本地 skill、市场 skill、生命周期响应模型
+-- script_bootstrap.py  Python Script Skill 子进程入口
+-- script_runtime.py    ScriptSkillRunner、PythonScriptAdapter 和 ShellScriptAdapter
+-- standardizer.py      将 SkillHub 下载包转换为统一 Skill 清单
+-- skillhub.py          SkillHub HTTP 客户端与远程 skill 转换
+-- validator.py         skill 目录结构校验
```

## 运行位置

- `backend/skills_store/` 是项目内置 skill 仓库，当前主要保留 `browser` 基础能力。
- `SERANA_SKILLS_DIR` 可以指定持久化 skill 仓库；Linux 部署默认写入 `/var/lib/serana/skills`。
- `$SERANA_SKILLS_DIR/installed/` 存放运行时安装的 managed skills。
- `$SERANA_SKILLS_DIR/.staging/` 存放等待审批的本地 ZIP 导入暂存。
- 未设置 `SERANA_SKILLS_DIR` 时，本地开发回落到 `backend/skills_store/installed/`。

## 当前调用协议

- `runtime=instruction`：
  安装启用后自动参与 Serana prompt 增强。它不直接执行，不显示在聊天框 `@` 调用候选里。
- `runtime=python` / `runtime=script`：
  普通自然语言不会自动命中。只有用户在聊天框输入 `@skill_name 参数...` 时，后端才会执行对应工具。
- 天气自然语言请求：
  统一走 browser / wttr 页面链路，不再优先调用已安装天气脚本。需要执行天气脚本时必须显式输入类似 `@weather_cn_pro 上海`。
- 安装或加载技能时，`SkillManager` 会根据 `skill.json` 的 `tools[].input_schema`、`script.argument_order` 和 `SKILL.md` 生成标准调用协议：
  - 会读取 Quick Start / Usage / 示例 / 用法等段落。
  - 会识别代码块里的 `./tool.sh 上海`、`bash tool.sh 北京 3`、已有 `@skill 参数` 等命令。
  - 会从 Markdown 参数表和项目符号里提取参数说明、示例值和可选/必填状态。
  - 对没有 `skill.json` 的 SkillHub shell 包，`standardizer.py` 会把这些信息写入生成的 `skill.json`，保证脚本参数顺序和前端示例一致。
  - `run_mode_description`：说明该技能如何参与 Serana。
  - `invocation_name`：聊天框里的 `@` 名称。
  - `invocation_parameters`：参数名、类型、描述和是否必填。
  - `invocation_examples`：前端展示给用户的调用示例。
- 后端 API 层会在进入 Serana agent loop 前拦截 `@` 命令，完成技能匹配、参数校验、工具执行和结果格式化。未补齐参数时会返回示例，不会进入 LLM 规划。

## 统一接入链路

1. SkillHub 或本地 ZIP 导入后，`standardizer.py` 尝试读取既有 `skill.json`。
2. 如果包内声明了有效 `runtime=python` 或 `runtime=script`，按声明注册工具。
3. 如果没有有效可执行清单，则作为 `runtime=instruction` 处理，只参与 prompt 增强。
4. `loader.py` 注册工具为 `skill_name.tool_name`。
5. `manager.py` 生成调用说明和 `@` 示例，并通过 `/api/v1/skills` 返回给前端。
6. 聊天 API 只在用户显式输入 `@skill_name 参数...` 时调用 python/script skill。

## 维护约定

- 修改 skill 包格式时，优先检查 `models.py`、`validator.py`、`loader.py`。
- 修改安装、更新、卸载、暂存生命周期时，优先检查 `manager.py` 和 `backend/app/api/skills.py`。
- 修改 API 返回结构时，同步检查 Android `ApiService.kt`、`SkillsViewModel.kt` 和聊天输入框提示逻辑。
- 新增运行时生成目录时，同步更新根目录 `.gitignore`、部署脚本和 `backend/skills_store/README.md`。
