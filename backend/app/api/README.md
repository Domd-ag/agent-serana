# app/api 目录说明

这里集中放后端 HTTP 路由，默认挂载在 `/api/v1` 下。

## 文件结构

```text
api/
+-- agents.py      Agent 相关接口
+-- approvals.py   审批请求、审批决策
+-- audit.py       审计查询、时间线与调试摘要
+-- browser.py     截图、HTML 预览、下载文件访问
+-- chat.py        聊天消息、流式事件、会话历史
+-- goals.py       目标、子任务与目标调试
+-- llm.py         LLM 配置读写；旧模式接口只保留兼容
+-- memory.py      记忆事实、摘要、检索
+-- skills.py      本地技能、SkillHub 市场、导入与卸载
```

## 维护约定

- 路由文件只处理 HTTP 请求、响应组装、依赖注入和错误转换。
- 业务逻辑优先放在 `app/agents/`、`app/memory/`、`app/skills/` 或 `app/core/`。
- `chat.py` 在准备 Serana runtime 时会分别传递动态记忆与当前会话最近历史；不要在 API 层自行解释短跟进或拼接用户意图。
- 修改 API 契约时，同步检查 Android data models、ViewModel 和对应 README。
- 后端不再提供默认 LLM；聊天、目标等需要模型的接口必须先由前端保存用户 LLM 配置。
