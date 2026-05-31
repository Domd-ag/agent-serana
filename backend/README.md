# Serana 后端目录

这里是 Serana 的 FastAPI 后端，负责聊天、LLM 配置、记忆、目标规划、agent 编排、技能加载、浏览器 artifact 和审计调试数据。

## 目录结构

```text
backend/
+-- app/                 后端应用源码
+-- skills_store/        本地 Sebastian 风格 skill 包
+-- requirements.txt     Python 依赖
+-- test_api_flows.py    主要 API/agent 回归测试
+-- test_full_system.py  全链路手动/集成验证
+-- test_init_db.py      数据库初始化验证
+-- test_memory_system.py
+-- test_new_agent.py
+-- test_new_skills.py
+-- test_skill_system.py
```

`venv/`、`__pycache__/`、浏览器截图和 HTML 预览属于本地运行产物，不属于源码结构。

## 主要功能

- `app/main.py` 创建 FastAPI 应用、注册中间件、异常处理和 `/api/v1` 路由。
- `app/api/` 提供 Android 端和调试端使用的 HTTP 接口。
- `app/agents/` 实现 Serana、Aide、Forge 的 agent 运行时。
- `app/core/` 放置数据库、模型、schema、LLM 网关、审计、日志等共享基础设施。
- `app/memory/` 管理长期事实记忆、resident snapshot、working memory、历史检索和 prompt 注入。
- `app/skills/` 负责 Sebastian 风格 skill 的加载、校验、启停、ClawHub 搜索/安装、更新、卸载和生命周期状态。
- `skills_store/` 存放可被 `SkillManager` 扫描加载的本地 skill 包。

## 常用入口

- 推荐启动：根目录运行 `start-backend.bat`
- 手动启动：`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- 健康检查：`GET /health`
- API 文档：`GET /docs`
- 主聊天：`POST /api/v1/chat/message`
- LLM 配置：`/api/v1/llm/*`
- 技能管理：`/api/v1/skills/*`
- 浏览器 artifact：`/api/v1/browser/*`

## 配置与运行维护

- 配置集中在 `backend/.env`，缺失时可从 `.env.example` 复制。
- `LOG_LEVEL` 控制后端日志级别，常用值为 `DEBUG`、`INFO`、`WARNING`。
- `CORS_ALLOW_ORIGINS` 默认允许所有来源；正式部署时可以改成逗号分隔的可信前端地址。
- `CLAWHUB_BASE_URL` 控制 ClawHub 市场来源，默认 `https://clawhub.ai`。
- SQLite 默认文件是后端工作目录下的 `serana.db`；需要换库时修改 `DATABASE_URL`。
- 运行维护说明见 `../docs/OPERATIONS.md`。

## 清理记录

- 已删除历史一次性编码修复脚本：`fix_all.py`、`fix_files.py`、`fix_html_encoding.py`。
- 已删除旧导入诊断脚本：`test_import.py`、`test_import_full.py`、`test_step_by_step.py`。
- 已移除空遗留目录：`app/browser`、`app/tools`、`skills`、`tests`。

## 维护约定

以后改动后端文件时，先读对应目录的 `README.md` 判断职责边界；新增、删除、重命名文件，或改变目录职责时，同步更新该目录的 `README.md`。
