# Serana

## 常用命令

- 后端测试：`test-backend.bat`
- 文档编码检查：`check-doc-encoding.bat`
- 命令约定：[docs/COMMANDS.md](/D:/agent-serana/docs/COMMANDS.md)

Serana 是一个面向个人自托管场景的 AI 管家项目，由 FastAPI 后端和 Android 客户端组成。当前目标是持续向 Sebastian 风格对齐：轻量对话优先、复杂任务按需升级、浏览器与 skill 能力可控接入。

## 当前状态

- 后端已经统一到 `ConversationLoop`，简单请求优先走轻链路，复杂任务再由 Serana 升级到 planning flow 并直接调度 Forge。
- 已接入 persona、working memory、instruction skills、工具结果回灌、浏览器 HTML 预览和审批流。
- Android 端已具备聊天、设置、技能市场、审批弹窗和 App 内 `WebView` 演示预览。
- Skill 生命周期已产品化到安装、启停、更新、卸载、来源、信任状态和生效范围。

## 目录结构

```text
.
+-- backend/            FastAPI 后端、agent 运行时、memory、skills、测试
+-- frontend-android/   Android / Jetpack Compose 客户端
+-- docs/               路线图、阶段文档和项目说明
+-- start-backend.bat   Windows 一键启动后端脚本
+-- PROJECT_SUMMARY.md  项目阶段总结
```

## 快速启动

### 后端

Windows 下可直接运行根目录脚本：

```bat
start-backend.bat
```

脚本会：

- 缺少 `backend/.env` 时从 `backend/.env.example` 生成一份。
- 缺少 `backend/venv` 时自动创建虚拟环境。
- 安装 `backend/requirements.txt`。
- 启动 `http://127.0.0.1:8000`。

常用地址：

- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Android

用 Android Studio 打开 `frontend-android/`。真机 USB 调试时，后端 Base URL 建议配置为局域网地址，例如：

```text
http://192.168.31.30:8000/api/v1/
```

## 配置

后端集中配置在 `backend/.env`，示例见 [backend/.env.example](/D:/agent-serana/backend/.env.example)。

常用配置项：

- `LOG_LEVEL`：日志级别，默认 `INFO`
- `DATABASE_URL`：数据库地址，默认本地 SQLite
- `HOST` / `PORT`：服务监听地址
- `SKILLHUB_BASE_URL`：SkillHub API 地址
- `SKILLHUB_PUBLIC_BASE_URL`：SkillHub 站点地址

LLM 不再由后端环境变量提供默认配置。首次使用时，先在 Android 设置里配置服务器地址，再保存 LLM 的 Base URL、API Key 和模型。

## 文档入口

- [后端说明](/D:/agent-serana/backend/README.md)
- [Android 说明](/D:/agent-serana/frontend-android/README.md)
- [后端演进路线图](/D:/agent-serana/docs/SEBASTIAN_BACKEND_ROADMAP.md)
- [后端 API 目录说明](/D:/agent-serana/backend/app/api/README.md)
- [后端 Skill 目录说明](/D:/agent-serana/backend/app/skills/README.md)

## 维护约定

- 新增、删除、重命名文件时，同步更新对应目录下的 `README.md`。
- 项目文档统一使用中文。
- 修改完功能后，同步更新相关 README，避免后续再次全盘扫目录找结构。
