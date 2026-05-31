# app 目录说明

这里是后端应用主目录，把 API、Agent、Memory、Skills、Approvals 和基础设施组织成一个可运行的 Serana 服务。

## 目录结构

```text
app/
+-- main.py
+-- api/         HTTP 路由层
+-- agents/      Serana / Aide / Forge 的执行与编排
+-- approvals/   PolicyGate、reviewer、approval manager、审批服务
+-- core/        数据库、schema、日志、LLM、artifact、审计
+-- memory/      resident / working / dynamic memory
+-- skills/      本地 skill 管理与 ClawHub 对接
```

## 当前重点

- 聊天流里已经支持审批事件回推
- 浏览器动作、远程技能安装、本地技能导入、可卸载技能删除都走统一审批链路
- `skills_store` 现在区分 bundled / installed / staging 三类目录

## 维护约定

- 涉及聊天执行链，先看 `agents/serana/README.md` 和 `api/README.md`
- 涉及审批或高风险动作，先看 `approvals/README.md`
- 涉及技能生命周期，先看 `skills/README.md` 和 `skills_store/README.md`
