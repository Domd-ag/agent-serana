# app 目录说明

这里是 Serana 后端应用源码根目录。

## 目录结构

```text
app/
+-- agents/      Serana、Forge 以及 agent loop
+-- api/         FastAPI 路由
+-- approvals/   策略门、审批管理与审批文案
+-- browser/     浏览器会话、截图、HTML 预览和下载文件
+-- core/        配置、数据库、日志、schema、LLM 网关
+-- memory/      长期记忆、工作记忆、摘要和检索
+-- skills/      本地 skill 管理与 SkillHub 对接
+-- main.py      FastAPI 应用入口
```

## 维护约定

- 涉及聊天执行链路，先看 `agents/serana/README.md` 和 `api/README.md`。
- 涉及审批或高风险动作，先看 `approvals/README.md`。
- 涉及技能生命周期，先看 `skills/README.md` 和 `../skills_store/README.md`。
