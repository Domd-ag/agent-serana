# Serana

<div align="center">

**一个面向个人自托管场景的 AI 私人管家。**

由 FastAPI 后端和 Android 原生客户端组成。Serana 参考
[Sebastian](https://github.com/PhantomButler/Sebastian) 的个人 AI 管家方向：以对话为入口，按需调用浏览器、记忆、Skill 和工具，把“回答问题”逐步推进到“处理事情”。

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Android](https://img.shields.io/badge/Android-Jetpack%20Compose-3DDC84)
![Self Hosted](https://img.shields.io/badge/Self--Hosted-yes-6b8f71)

</div>

---

## 项目定位

Serana 是一个自托管的个人 AI 管家系统。你在手机 App 里向 Serana 发起请求，后端负责理解上下文、选择执行链路、调用工具、沉淀记忆，并把结果以聊天、卡片、浏览器预览或审批事件的形式返回。

它目前更适合个人实验和自用部署，而不是企业级产品。项目的核心目标是：

- 私有部署：后端运行在你自己的电脑或服务器上。
- 手机优先：Android App 是主要交互入口。
- 管家人格：Serana 有稳定的人设、语气和长期记忆。
- 工具可控：浏览器、Skill、脚本和高风险操作都有明确边界。
- 渐进增强：简单问题直接回答，复杂任务再升级到规划和执行链路。

## 当前能力

- 实时聊天：支持流式响应、思考状态、工具过程和最终回答。
- Android 客户端：Jetpack Compose 实现聊天、设置、技能页、审批弹窗和 App 内 WebView 演示。
- LLM 配置：App 内配置服务器地址、Base URL、API Key 和模型；后端不内置默认 LLM。
- Serana 人格：后端启动时加载 Serana 人设，日常对话保持个人管家风格。
- 记忆系统：支持 resident memory、working memory、summary、episode 和后台 consolidation。
- 浏览器能力：支持网页打开、观察、搜索结果整理、HTML 演示预览和 artifact 复用。
- SkillHub 集成：支持远程搜索、安装、卸载、启停和本地技能列表。
- `@skill` 调用：Python/Script 类型 Skill 不再自然语言自动命中，用户显式输入 `@skill_name 参数` 后执行。
- 审批机制：安装、卸载、敏感操作通过后端审批事件和前端弹窗确认。
- Linux 部署：提供从 GitHub 下载源码包的一键部署脚本和 `serana` 管理菜单。

## 架构概览

```text
Android App
  - Chat UI
  - Settings
  - SkillHub / Local Skills
  - Approval Dialogs
  - WebView Preview

        |
        | HTTP / Streaming
        v

FastAPI Backend
  - Chat API
  - LLM Config API
  - Skill API
  - Browser Artifact API
  - Approval API

        |
        v

Serana Runtime
  - ConversationLoop
  - Context Builder
  - Persona
  - Memory Injector
  - Tool Result Protocol
  - Browser Chain
  - Script Skill Runtime

        |
        +-- SQLite / Memory Store
        +-- SkillHub Packages
        +-- Browser Previews
        +-- LLM Provider
```

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、SQLAlchemy、Pydantic、LangChain/LangGraph |
| 数据 | SQLite 默认，本地文件持久化 |
| 浏览器 | Playwright、HTML preview artifact |
| Android | Kotlin、Jetpack Compose、Retrofit、OkHttp、Material 3 |
| Skill | Sebastian 风格 `SKILL.md` / `skill.json`，SkillHub 市场，Python/Script Runtime |
| 部署 | systemd、bash、GitHub source archive |

## 目录结构

```text
.
+-- backend/             FastAPI 后端、Serana runtime、memory、skills、测试
+-- frontend-android/    Android / Jetpack Compose 客户端
+-- docs/                路线图、部署说明、阶段文档
+-- scripts/             Linux 部署和项目维护脚本
+-- skills_store/        项目内置 skill 与本地开发默认仓库
+-- start-backend.bat    Windows 本地后端启动脚本
+-- test-backend.bat     Windows 后端测试脚本
+-- PROJECT_SUMMARY.md   项目阶段总结
```

## 快速开始

### 1. 启动后端

Windows 本地开发可以直接运行：

```bat
start-backend.bat
```

脚本会创建虚拟环境、安装依赖并启动：

```text
http://127.0.0.1:8000
```

常用地址：

- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. 打开 Android 工程

用 Android Studio 打开：

```text
frontend-android/
```

真机调试时，手机不能直接访问电脑的 `127.0.0.1`。请在 App 设置页把服务器地址配置为电脑或服务器的局域网地址，例如：

```text
http://192.168.31.30:8000/api/v1/
```

### 3. 配置 LLM

首次使用需要在 App 设置页配置：

```text
Base URL
API Key
模型名称
```

后端不再提供默认 LLM 配置。这样同一个后端可以服务不同手机端配置，也避免把密钥写进服务器环境变量。

## Linux 一键部署

在服务器上执行：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh | sudo bash
```

部署完成后使用管理菜单：

```bash
serana
```

菜单提供启动、关闭、查看状态、实时日志、重启、健康检查和重新部署。

默认路径：

```text
代码目录: /opt/serana
配置文件: /etc/serana/serana.env
数据目录: /var/lib/serana
Skill 持久目录: /var/lib/serana/skills
浏览器产物目录: /var/lib/serana/browser
服务名: serana-backend
默认端口: 8000
```

如果服务器下载依赖很慢，可以参考 [Linux 部署方案](docs/LINUX_DEPLOYMENT.md) 中的国内源参数。

## Skill 使用方式

Serana 当前把 Skill 分成两类：

- `instruction`：安装后参与 prompt 增强，适合人格、工作流、经验规则。
- `python` / `script`：不会被自然语言自动调用，只能通过聊天框显式 `@` 调用。

示例：

```text
@restaurant_crosscheck 上海浦东新区 火锅
```

安装 SkillHub 技能后，Android 输入框输入 `@` 会显示可调用技能、参数提示和示例。如果参数不足，前端会提示补齐；后端不会进入 LLM 规划链路。

Linux 部署时，SkillHub 安装的技能不会写入源码目录，而是持久化到：

```text
/var/lib/serana/skills/installed
```

这样重新部署或升级 `/opt/serana` 不会删除已安装技能。

## 与 Sebastian 的关系

Serana 不是 Sebastian 的复制版。它参考 Sebastian 的产品方向和工程风格，但做了适合本项目当前阶段的取舍：

- 保留个人 AI 管家的核心体验：手机入口、长期记忆、工具调用、浏览器能力、Skill 扩展。
- 后端采用 FastAPI API 服务形态，更贴近 Android App 直连使用。
- Agent loop 更偏轻量：简单请求直接处理，复杂任务再升级。
- Skill 策略更保守：可执行 Skill 必须显式 `@` 调用，避免自然语言误触发脚本。
- 部署目标优先覆盖个人 Linux 服务器和 Windows 本地开发。

## 文档入口

- [后端说明](backend/README.md)
- [Android 说明](frontend-android/README.md)
- [Linux 一键部署方案](docs/LINUX_DEPLOYMENT.md)
- [后端演进路线图](docs/SEBASTIAN_BACKEND_ROADMAP.md)
- [Skill Runtime 规范](docs/SKILL_RUNTIME_SPEC.md)
- [命令约定](docs/COMMANDS.md)
- [项目阶段总结](PROJECT_SUMMARY.md)

## 常用命令

```bat
test-backend.bat
check-doc-encoding.bat
```

Android 编译示例：

```bat
C:\Users\ASUS\gradle\gradle-8.2\bin\gradle.bat -p frontend-android :app:compileDebugKotlin --no-daemon
```

## 项目状态

Serana 仍在快速开发中。当前重点包括：

- 稳定 Script Skill Runtime 和 SkillHub 安装体验。
- 优化浏览器搜索、观察、HTML preview 和 artifact 复用链路。
- 继续收敛 memory 的提取、沉淀、检索和上下文注入。
- 打磨 Android 前端的聊天滚动、设置、技能页和审批体验。
- 补齐部署文档、运行维护脚本和全量验证流程。

## 维护约定

- 项目文档统一使用中文。
- 新增、删除、重命名文件时，同步更新对应目录下的 `README.md`。
- 修改 API 返回结构时，同步检查 Android 端 Retrofit models 和 ViewModel。
- 修改 Skill 生命周期时，同步检查 `backend/app/skills/README.md` 与 `docs/SKILL_RUNTIME_SPEC.md`。

