# core 目录说明

这里放后端跨模块共享的基础设施。凡是 API、Agent、Memory、Skills、Approvals 都会复用的能力，优先放在这里。

## 目录结构

```text
core/
+-- __init__.py
+-- artifacts.py     前端可展示 artifact 的统一结构
+-- audit.py         审计记录写入、摘要和时间线
+-- config.py        应用配置
+-- database.py      Async SQLAlchemy engine / session
+-- deps.py          FastAPI 依赖注入
+-- exceptions.py    自定义异常与全局异常处理
+-- init_db.py       初始化数据库与默认用户
+-- llm_gateway.py   LLM provider 与实例创建
+-- logger.py        日志分层与 logger 工厂
+-- models.py        ORM 模型
+-- schemas.py       API 与前后端共享的 Pydantic schema
+-- security.py      敏感配置加解密
+-- tool_results.py  工具执行结果回灌协议
```

## 当前重点

- `config.py`
  - 集中读取 `backend/.env`。
  - 包含应用版本、日志级别、CORS、数据库、默认 LLM、服务端口和 SkillHub 配置。
- `schemas.py`
  - 定义聊天、审批、技能、记忆等接口的共享模型。
- `artifacts.py`
  - 统一截图、HTML 预览、下载文件等 artifact 结构。
- `tool_results.py`
  - 统一生成 `serana.tool_result.v1`。
  - Agent、Skill、Browser 等链路向用户回灌工具结果时，优先复用这里的 helper。
- `audit.py`
  - 负责审计记录、调试摘要和关键执行洞察。
  - `planning_stages`、`tool_result_names`、`artifact_kinds` 等聚合字段也从这里产出。
- `database.py`
  - SQLite 运行时启用 WAL、15 秒 busy timeout 和外键约束，允许后台 Memory consolidation 与新的聊天请求安全并行。

## 维护约定

- 只服务单一路由或单个 skill 的逻辑，不要提前塞进 `core/`。
- 新增共享 schema、artifact 或 `tool_result` 字段时，同步检查 Android DTO 是否需要更新。
- 修改 `schemas.py` 后，优先回看 [backend/app/api/README.md](/D:/agent-serana/backend/app/api/README.md) 和客户端解析代码。
- 新增环境变量时，同步更新 `backend/.env.example`、根目录 [README.md](/D:/agent-serana/README.md) 和 [docs/OPERATIONS.md](/D:/agent-serana/docs/OPERATIONS.md)。
