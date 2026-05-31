# Serana

Serana 是一个面向个人自托管的 AI Butler 项目，由 FastAPI 后端和 Android 客户端组成。当前目标是逐步对齐 Sebastian 风格：轻量对话优先、复杂任务按需升级、浏览器和 skill 能力可控接入。

## 当前状态

- 后端已切到统一 `ConversationLoop`，简单聊天优先走轻链路，复杂任务再升级到规划和 Aide/Forge 委派。
- 已接入 persona、working memory、instruction skills、工具结果回灌、浏览器 HTML preview、审批流。
- Android 端已具备聊天、设置、技能市场、审批弹窗和 App 内 WebView 演示预览。
- Skill 生命周期正在产品化：支持安装、启停、卸载、来源/信任/范围展示、远程更新入口。

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

Windows 下可以直接运行根目录脚本：

```bat
start-backend.bat
```

脚本会：

- 如果缺少 `backend/.env`，从 `backend/.env.example` 生成一份
- 如果缺少 `backend/venv`，自动创建虚拟环境
- 安装 `backend/requirements.txt`
- 启动 `http://127.0.0.1:8000`

常用地址：

- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Android

用 Android Studio 打开 `frontend-android/`。真机 USB 调试时，后端 Base URL 推荐配置为局域网地址，例如：

```text
http://192.168.31.30:8000/api/v1/
```

## 配置

后端集中配置在 `backend/.env`，示例见 [backend/.env.example](backend/.env.example)。常用项：

- `LOG_LEVEL`：日志级别，默认 `INFO`
- `DATABASE_URL`：数据库地址，默认本地 SQLite
- `DEFAULT_LLM_*`：默认 LLM 配置
- `HOST` / `PORT`：服务监听地址
- `CLAWHUB_BASE_URL`：ClawHub 市场地址

## 文档入口

- [后端说明](backend/README.md)
- [Android 说明](frontend-android/README.md)
- [Sebastian 风格后端路线图](docs/SEBASTIAN_BACKEND_ROADMAP.md)
- [后端 API 目录说明](backend/app/api/README.md)
- [后端 Skill 目录说明](backend/app/skills/README.md)

## 维护约定

- 以后新增、删除、重命名文件时，同步更新对应目录下的 `README.md`。
- 后端文档统一使用中文。
- GitHub 提交前先做一次后端测试、Android 编译和文档状态检查。
