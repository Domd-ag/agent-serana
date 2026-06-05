# agents 目录

这里实现 Serana 后端的 agent 运行时：Serana 是唯一主 Agent 和协调者，Forge 是按需创建的执行 worker。

## 目录结构

```text
agents/
+-- __init__.py
+-- agent_limits.json  agent 实例上限配置
+-- base.py            AgentManager、manifest、状态模型和池化逻辑
+-- forge/             Forge 执行 agent
+-- serana/            Serana 主 agent
```

## 职责划分

- `serana/`：理解用户请求、构建上下文、选择直接回复/工具调用/委派执行，并生成最终回复。
- `forge/`：执行具体子任务，并按任务类型选择执行策略。
- `base.py`：读取 manifest、应用 `agent_limits.json`、维护 agent 池和状态。

## 运行方式

1. `Serana` 先进行 lightweight route，尽量用一次 LLM 判断直接回复、工具调用或委派。
2. 简单请求走直接回复或本地 tool。
3. 复杂请求进入 Serana planning loop，由 Serana 拆解任务、控制并发与重试，并直接分发给 Forge。
4. 所有关键阶段写入 thinking blocks、tool calls 和 audit traces。

## Loop 化进展

- Serana 的重链路 planning flow 已放到 `serana/loop.py`，由 ConversationLoop 执行 analyze/decompose/delegate/summarize。
- Forge 委派会作为 `serana_loop_action` 记录 started/completed。
- 阶段 trace 统一使用 `serana_planning_stage`，旧的 graph 入口和审计字段已经移除。
- 子代理委派会记录 `serana_agent_lifecycle`，并把 Forge 与 delegate 汇总写成统一 `tool_result`。

## 维护约定

调整 agent 数量先改 `agent_limits.json`；调整某个 agent 的行为先进入对应子目录。新增 agent 类型时同步更新本 README、`base.py` 和 API 暴露逻辑。
