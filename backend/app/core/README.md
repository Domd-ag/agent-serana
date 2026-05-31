# core 目录说明

这里放后端跨模块共享的基础设施。凡是 API、Agent、Memory、Skills、Approvals 都会复用的能力，优先放在这里。

## 目录结构

```text
core/
+-- __init__.py
+-- artifacts.py   前端可展示 artifact 的统一结构
+-- audit.py       审计记录写入、摘要和 timeline
+-- config.py      应用配置
+-- database.py    Async SQLAlchemy engine / session
+-- deps.py        FastAPI 依赖注入
+-- exceptions.py  自定义异常与全局异常处理
+-- init_db.py     初始化数据库与默认用户
+-- llm_gateway.py LLM provider 与实例创建
+-- logger.py      日志分层与 logger 工厂
+-- models.py      ORM 模型
+-- schemas.py     API 与前后端共享的 Pydantic schema
+-- security.py    敏感配置加解密
+-- tool_results.py 工具执行结果回灌协议
```

## 与本轮开发相关的文件

- `config.py`
  - 集中读取 `.env` 配置，包含应用版本、日志级别、CORS、数据库、默认 LLM、服务端口和 ClawHub 地址。
- `schemas.py`
  - 现在包含聊天审批使用的 `ApprovalRequest` 和 `ApprovalResponse`。
- `artifacts.py`
  - 负责截图、HTML 预览、下载文件等统一 artifact 结构。
- `tool_results.py`
  - 统一生成 `serana.tool_result.v1`，包含工具名、输入、输出、状态、用户摘要、artifact 和元数据。
  - Agent、Skill、Browser 等链路需要向用户回复回灌工具结果时优先使用这里的 `build_tool_result()` / `attach_tool_result()` / `append_tool_result()`。
- `audit.py`
  - 审计工具调用、路由决策和后续调试查看。
  - planning flow 的汇总字段是 `planning_stages`；旧 `graph_stages` 兼容字段已经移除。
  - `tool_result` 会在 audit payload 中提升为顶层字段，并汇总到 `tool_result_names`、`tool_result_statuses`、`tool_result_schema_versions` 和 `artifact_kinds`。

## 维护约定

- 只服务单一路由或单个 skill 的逻辑，不要提前塞进 `core/`。
- 新增共享 schema、artifact 或 `tool_result` 字段时，要同步检查 Android DTO 是否需要更新。
- 改动 `schemas.py` 后，优先回看 `api/README.md` 和相关客户端解析代码。
- 新增环境变量时，同步更新 `backend/.env.example`、根目录 `README.md` 和 `docs/OPERATIONS.md`。
