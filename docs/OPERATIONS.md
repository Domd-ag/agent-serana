# Serana 运行维护说明

这份文档记录本地运行、配置、日志和发布前检查流程。

## 本地启动

推荐在项目根目录运行：

```bat
start-backend.bat
```

脚本会检查 `backend/.env`、`backend/venv` 和依赖，然后启动后端服务。

手动启动方式：

```powershell
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 配置文件

后端配置集中在 `backend/.env`。新环境可以先复制：

```powershell
Copy-Item backend\.env.example backend\.env
```

常用配置：

- `LOG_LEVEL`：日志级别。排查问题用 `DEBUG`，日常使用建议 `INFO`。
- `DATABASE_URL`：数据库连接。默认 SQLite。
- `DEFAULT_LLM_PROVIDER` / `DEFAULT_LLM_API_KEY` / `DEFAULT_LLM_BASE_URL` / `DEFAULT_LLM_MODEL`：默认 LLM 配置。
- `HOST` / `PORT`：服务监听地址。
- `CORS_ALLOW_ORIGINS`：允许访问后端的前端来源。
- `CLAWHUB_BASE_URL`：ClawHub 市场地址。

## 健康检查

- `GET /health`：服务状态和版本。
- `GET /docs`：FastAPI Swagger 文档。
- `GET /api/v1/skills`：确认 skill 管理器完成初始化。

## 日志

日志按命名空间区分：

- `app.startup.*`：启动、初始化、关闭。
- `app.request.*`：HTTP 请求链路。
- `app.tool.*`：工具、skill、浏览器动作。

如果终端输出太吵，优先把 `LOG_LEVEL` 调成 `INFO` 或 `WARNING`。

## Skill 生命周期

当前支持：

- 本地 bundled skill 扫描加载。
- ClawHub 市场搜索、安装、更新。
- 本地 ZIP 导入。
- 启用 / 停用。
- managed skill 卸载。
- 来源、信任状态、生效范围展示。
- 生效范围修改。

高风险或会改变本地能力的动作会进入审批流。

## 发布前检查

1. 后端测试：

```powershell
cd backend
venv\Scripts\python.exe -m unittest test_api_flows.py
```

2. Android 编译：

```powershell
cd frontend-android
C:\Users\ASUS\gradle\gradle-8.2\bin\gradle.bat :app:compileDebugKotlin
```

3. 文档检查：

- 根目录 `README.md`
- `backend/README.md`
- `frontend-android/README.md`
- 受影响目录的 `README.md`
- `docs/SEBASTIAN_BACKEND_ROADMAP.md`

4. Git 状态检查：

```powershell
git status --short
```
