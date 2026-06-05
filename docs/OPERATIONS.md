# 运行与维护说明

这份文档记录 Serana 后端的日常运行、配置和排查入口。

## 启动

推荐在项目根目录运行：

```bat
start-backend.bat
```

手动启动后端：

```powershell
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-use-colors
```

根目录 `start-backend.bat` 会固定使用 UTF-8，并关闭 Uvicorn ANSI 彩色日志，避免不支持 ANSI 的终端把颜色控制码显示成 `□[32m` 一类乱码。

## 常用配置

- `LOG_LEVEL`：日志级别。排查问题用 `DEBUG`，日常运行建议 `INFO`。
- `DATABASE_URL`：数据库连接，默认 SQLite。
- `HOST` / `PORT`：服务监听地址。
- `CORS_ALLOW_ORIGINS`：允许访问后端的前端来源。
- `SKILLHUB_BASE_URL`：SkillHub API 地址，默认 `https://api.skillhub.cn`。
- `SKILLHUB_PUBLIC_BASE_URL`：SkillHub 站点地址，默认 `https://skillhub.cn`。

LLM 配置由客户端通过 `/api/v1/llm/config` 写入数据库。后端没有默认 LLM；未配置时聊天和目标链路会返回明确的配置错误。

## 技能维护

- 支持 SkillHub 市场搜索、安装、更新。
- 支持本地 ZIP 导入。
- 支持启用、停用、卸载。
- 生命周期状态会展示来源、信任状态和生效范围。

## 编码约定

- 仓库文本文件统一使用 UTF-8。
- `.editorconfig` 和 `.gitattributes` 已声明默认编码与换行策略。
- 批量修改中文文件时，不要再用 PowerShell 5.1 默认的 `Get-Content` / `Set-Content` 直接改写无 BOM 的 UTF-8 文件。
- 手工改文件优先使用补丁方式；需要脚本处理时，必须显式指定 UTF-8 读写。

## 排查顺序

1. 看后端日志里是否有请求、工具或 LLM 网关错误。
2. 用 `/docs` 检查接口是否可访问。
3. 用 `/api/v1/skills/marketplace/search?q=weather` 验证 SkillHub 搜索。
4. 用 Android 设置页确认后端地址是否指向当前机器的局域网 IP。
5. 如果是流式聊天问题，优先检查 `/api/v1/chat/message` 的 SSE 事件输出。
