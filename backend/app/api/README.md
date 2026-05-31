# api 目录说明

这里是 FastAPI 路由层。职责是处理协议边界、调用应用服务、返回统一响应，不在这里堆太多业务细节。

## 文件结构

```text
api/
+-- __init__.py   汇总并挂载 /api/v1 路由
+-- approvals.py  通用审批提交入口
+-- agents.py     agent 状态与清单
+-- audit.py      审计查询、时间线与调试摘要
+-- browser.py    截图、HTML 预览、下载文件访问
+-- chat.py       聊天消息、流式事件、会话历史、审批别名入口
+-- goals.py      目标、子任务、目标调试
+-- llm.py        LLM 配置与模式切换
+-- memory.py     记忆事实与检索
+-- skills.py     本地技能、ClawHub 市场、技能导入与卸载
```

## 当前重点接口

- `POST /approvals/{request_id}`
  - 通用审批提交入口
  - 聊天审批和技能页审批都走这一条
  - `approval_scope=once` 表示本次允许，`approval_scope=always` 表示在当前后端进程内持续允许同类中风险动作
- `POST /skills/marketplace/install`
  - 两步式远程安装：
    1. 首次调用返回 `approval_required`
    2. 审批通过后携带 `approval_request_id` 再次调用完成安装
- `POST /skills/upload`
  - 两步式本地 ZIP 导入：
    1. 上传 ZIP 并返回 `approval_required`
    2. 审批通过后只携带 `approval_request_id` 再次调用完成导入
- `DELETE /skills/{skill_name}`
  - 只允许卸载 managed skills
  - bundled skills 会直接返回不能卸载
- `GET /skills/{skill_name}/lifecycle`
  - 返回来源、信任状态、生效范围、可更新状态和版本信息
- `POST /skills/{skill_name}/scope`
  - 修改 skill 对 Serana / Aide / Forge / all 的生效范围
- `POST /skills/{skill_name}/update`
  - 对 ClawHub managed skill 执行两步式审批更新
- `POST /goals`
  - 目标创建会复用 Serana 的统一 loop。
  - 简单目标直接完成，中等目标只生成计划，复杂目标才进入 Aide/Forge 委派。

## 维护约定

- 新增请求/响应结构时，先同步 `core/schemas.py` 或 `skills/models.py`
- 新增流式事件时，同步检查 Android 的 `RetrofitClient` 与 `ChatViewModel`
- 涉及审批的接口，必须同时检查：
  - `approvals/` 策略和 reviewer 文案
  - 审计记录是否完整
  - 前端是否有对应的确认交互
