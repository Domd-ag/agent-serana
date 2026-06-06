# app/skills 目录说明

这里是后端 skill 管理层，负责本地技能扫描、启停、导入、卸载、更新，以及 SkillHub 远程市场接入。

## 文件结构

```text
skills/
+-- __init__.py
+-- loader.py      读取 skill.json / SKILL.md，并注册 Python / Script 工具
+-- manager.py     SkillManager 单例，负责扫描、安装、缓存、卸载与工具查找
+-- models.py      本地 skill、市场 skill、生命周期响应模型
+-- script_bootstrap.py  Script Skill 子进程安全边界与审计钩子
+-- script_runtime.py    ScriptSkillRunner、PythonScriptAdapter 与 ShellScriptAdapter
+-- standardizer.py      将 SkillHub 下载包转换为统一 Skill 清单
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

## 统一接入协议

- `runtime=python` 且 `tools` 非空：
  安装后会被 `SkillManager` 注册成真实可执行工具，统一进入 `skill_name.tool_name` 命名空间。
  对话时优先由轻量 route 和 direct tool executor 选择并执行，再走统一结果回灌。
- `runtime=instruction`：
  安装后不会直接执行，而是把 `SKILL.md` 作为行为和领域指导注入到 Serana 上下文。
  对话时会优先挑选和当前问题相关的 instruction skill，再生成 direct reply 或辅助 planning。
  SkillHub 包内即使附带 `.sh` 等脚本，只要清单仍是 `runtime=instruction` 且 `tools=[]`，后端就不会把脚本当作已注册工具自动执行；这样可以避免未声明参数、运行环境和权限的市场脚本绕过统一工具协议与审批门禁。
  如果 `SKILL.md` 同时引用多个 `.sh`，且包内没有显式 `runtime=script` 清单，安装器会按 instruction skill 保留它，而不是猜测脚本入口。
- `runtime=script`：
  Python 包由 `PythonScriptAdapter` 执行技能目录内声明的 `.py` 入口。
  入口明确的 SkillHub `.sh` 包会在安装时由 `SkillStandardizer` 自动转换，并通过 `ShellScriptAdapter` 执行。
  Python adapter 使用 JSON stdin/stdout 协议；Shell adapter 按 `argument_order` 传递位置参数，并把文本或 JSON stdout 统一包装为工具结果。
  安装后会注册为普通 `skill_name.tool_name` 工具；相关可执行 Skill 会在 Browser 兜底之前参与选择，失败后才继续走 Browser。
- `capabilities` / `intents`：
  skill 包现在可以在 `skill.json` 中显式声明能力标签和意图短语。
  `capabilities` 适合写领域或能力名，比如 `weather`、`calendar`、`coding`。
  `intents` 适合写用户会提出的请求类型，比如 `天气查询`、`写代码`、`行程安排`。
  对话相关性匹配会优先使用这两个字段，再回退到 skill 名称和描述。
- 浏览器兜底：
  只有本地可执行 skill 不命中，且没有相关 instruction skill 可以直接支撑回答，或者用户明确要求“上网搜 / 用浏览器 / 打开网页”时，才会走 browser 工具链。

这意味着以后从 SkillHub 下载的新 skill，不需要再为每个领域单独写一条天气式特判。只要 skill 包本身声明清楚自己是工具型还是 instruction 型，就会进入同一套对话接入流程。

## Script Skill 安全边界

- 入口必须是 Skill 自身目录内的 `.py` 文件。
- Shell 入口必须是 Skill 自身目录内、UTF-8 编码且通过静态安全检查的 `.sh` 文件。
- 使用当前后端 Python 启动独立隔离进程，默认不继承敏感环境变量。
- Python adapter 禁止 shell、`subprocess`、`multiprocessing` 和 `ctypes`。
- Shell adapter 需要后端一次性安装 Bash，并拒绝系统管理、破坏性删除、动态执行和远程执行命令。
- Script Runtime 会严格校验参数类型，布尔值不会被误当成整数；输入、输出和执行时长超过限制时会返回统一可读错误，并在终止子进程后完整回收读写任务。
- Skill 的 `instruction_file`、Python 入口和 Script 入口都必须位于自身目录；带 UTF-8 BOM 的市场清单也可以正常加载。
- 远程 Skill 更新采用备份替换：新版本复制或运行时注册失败时，会自动恢复并重新注册上一版本。
- 默认禁止网络和文件写入；仅支持显式声明 `network`、`filesystem_write`。
- 即使声明 `filesystem_write`，也只能修改 Skill 自身目录。
- 读取范围限制为 Skill 自身目录和 Python 运行时目录。
- 工具参数必须符合 manifest 中声明的 schema，未知参数会被拒绝。
- Runner 强制执行输入上限、输出上限、超时和 `max_instances` 并发限制。
- 这是一层应用级安全边界，不等同于容器或操作系统级强隔离；不应把来源不可信的脚本标记为可执行 Skill。

完整下载、标准化和运行规范见 [docs/SKILL_RUNTIME_SPEC.md](/D:/agent-serana/docs/SKILL_RUNTIME_SPEC.md)。

标准清单示例：

```json
{
  "name": "example_script",
  "version": "1.0.0",
  "description": "示例 Script Skill",
  "runtime": "script",
  "entrypoint": "main.py",
  "agent_type": "all",
  "max_instances": 1,
  "permissions": ["network"],
  "script": {
    "adapter": "python",
    "timeout_seconds": 15,
    "max_input_chars": 32768,
    "max_output_chars": 65536
  },
  "tools": [
    {
      "name": "lookup",
      "description": "查询数据",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"}
        },
        "required": ["query"]
      }
    }
  ]
}
```

## 维护约定

- 修改 skill 包格式时，优先检查 `models.py`、`validator.py`、`loader.py`。
- 修改安装、更新、卸载、暂存生命周期时，优先检查 `manager.py`。
- 修改 API 返回结构时，同步检查 [backend/app/api/skills.py](/D:/agent-serana/backend/app/api/skills.py) 和 Android `SkillsViewModel`。
- 新增运行时生成目录时，同步更新根目录 `.gitignore` 和 [backend/skills_store/README.md](/D:/agent-serana/backend/skills_store/README.md)。
