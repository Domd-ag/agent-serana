# Serana Skill 下载、标准化与运行规范

## 目标

用户在 App 中从 SkillHub 点击安装后，后端负责完成下载、检查、标准化、注册和对话接入。领域能力不再通过天气、日历等硬编码特判逐个适配。

## 一步安装到使用流程

```text
App 点击安装
  -> SkillHubClient 下载 ZIP
  -> 校验 ZIP 路径与符号链接
  -> SkillStandardizer 检查包结构
  -> 生成或补全统一 skill.json
  -> SkillValidator 校验清单与入口
  -> SkillManager 安装并注册工具
  -> 对话路由根据 capabilities / intents / 工具描述选择
  -> ScriptSkillRunner 执行
  -> 统一工具结果回灌并回复用户
```

只有整个流程完成后，安装接口才返回 `installed`。标准化、校验或注册失败时不会留下半安装目录；更新已有 Skill 失败时会自动恢复上一版本。

运行时还会执行以下稳定性检查：

- `skill.json` 支持标准 UTF-8 与带 BOM 的 UTF-8。
- `instruction_file` 和所有入口文件必须位于 Skill 自身目录。
- 参数严格遵守工具 schema，布尔值不会被当作整数或数字。
- 超时、输出过大、非 JSON 输出和非零退出码都会转换成统一的 `ScriptSkillError`。
- 更新过程先保留旧版本备份；只有新版本完成运行时注册后才删除备份。

## 包类型处理

### 已声明标准运行时

下载包已经包含有效的 `skill.json`，并声明 `runtime=python` 或 `runtime=script` 时，保留其工具和运行时声明，再补充 SkillHub 来源、版本和能力标签。

### 单入口 Shell Skill

满足以下条件时自动转换为可执行 Shell Script Skill：

- 包中只有一个 `.sh`，或 `SKILL.md` 明确引用唯一 `.sh` 入口。
- 脚本是 UTF-8。
- 脚本通过静态安全检查。
- 后端存在 Bash。

标准化后：

- `runtime=script`
- `script.adapter=shell`
- 自动生成一个工具
- 用户当前请求通过 `query` 参数传给脚本第一个位置参数
- stdout 作为工具 `summary` 回灌给用户

### 纯说明 Skill

没有可执行入口的包保持 `runtime=instruction`，其 `SKILL.md` 只参与提示增强。

### 不兼容或危险 Skill

以下情况直接拒绝安装，并向 App 返回明确原因：

- 多个 Shell 入口且 `SKILL.md` 没有声明唯一入口。
- 包含越界 ZIP 路径或符号链接。
- 包含系统管理、破坏性删除、动态执行、远程执行或其他解释器启动命令。
- 声明网络或文件写入行为但缺少对应权限。
- 当前后端没有 Bash。

## Shell 运行环境

Windows 后端推荐安装 Git Bash。运行时按以下顺序查找：

1. 环境变量 `SERANA_BASH_PATH`
2. 系统 `PATH` 中的 `bash`
3. Git Bash 常见安装位置
4. Linux/macOS 的 `/bin/bash`、`/usr/bin/bash`

示例：

```powershell
[Environment]::SetEnvironmentVariable(
  "SERANA_BASH_PATH",
  "C:\Program Files\Git\bin\bash.exe",
  "User"
)
```

配置后重新启动后端即可，不需要为每个 Shell Skill 单独配置。

## 标准 Script Skill 清单

```json
{
  "name": "sample_query",
  "version": "1.0.0",
  "description": "查询指定内容",
  "runtime": "script",
  "entrypoint": "query.sh",
  "capabilities": ["query"],
  "intents": ["查询指定内容"],
  "permissions": ["network"],
  "script": {
    "adapter": "shell",
    "timeout_seconds": 20,
    "max_input_chars": 8192,
    "max_output_chars": 32768,
    "argument_order": ["query"],
    "output_format": "text"
  },
  "tools": [
    {
      "name": "query",
      "description": "查询指定内容",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "交给脚本处理的主要对象或查询内容"
          }
        },
        "required": ["query"]
      }
    }
  ]
}
```

## 安全边界

Python Script Skill 使用独立 Python 进程和审计钩子。Shell Script Skill 使用参数数组启动 Bash，不使用 `shell=True`，并限制环境变量、执行时长、并发和输出大小，同时在安装和加载阶段执行静态危险指令检查。

Shell 静态检查仍不等于容器或操作系统级强隔离。来源不可信、需要广泛文件权限或需要执行任意命令的 Skill 不应自动安装；后续如需更强隔离，应将 Runner 放入容器或受限工作进程。
