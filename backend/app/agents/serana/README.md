# serana 目录说明

这里是 Serana 作为主 Agent 的核心实现。它负责理解请求、组合上下文、选择工具、在必要时升级到 planning flow，并把结果整理成用户可读回复。

## 目录结构

```text
serana/
+-- __init__.py
+-- context.py    统一 context builder、请求上下文、working memory、instruction skill 注入
+-- graph.py      AgentState 类型与初始状态构建
+-- loop.py       ConversationLoop 统一运行时、lightweight route、planning flow、Aide/Forge loop action、流式事件转发
+-- nodes.py      路由、工具选择、浏览器总结、委派与总结节点
+-- persona.md    Serana 人设定义
+-- persona.py    人设加载与 system prompt 构建
+-- runtime.py    聊天前的 runtime context 准备
+-- serana.py     SeranaAgent 对外入口
```

## 当前执行链

1. `runtime.py`
   - 准备 memory context、resident snapshot、working memory 和 LLM。
2. `serana.py`
   - 创建初始状态，并把审批运行时能力注入到 state。
   - loop 升级后用显式 planning flow 调用 analyze/decompose/delegate/summarize。
3. `loop.py`
   - 由 `ConversationLoop` 统一承载 plan-act-escalate 决策。
   - 先尝试 lightweight direct route；安全的简单 goal 也可以在这里直接完成。
   - 需要更重处理时进入 loop 内置 planning flow，并携带 lightweight route 决策作为上下文。
   - `execute_planning_flow(...)` 在 loop 内按 analyze/decompose/delegate/summarize 运行；Aide/Forge 委派会记录为 `serana_loop_action`。
   - 流式模式下负责把运行时审批事件转成 SSE 事件。
4. `nodes.py`
   - 负责 direct reply、direct tool、browser summarize、委派、多步总结。
   - direct tool 轻链路已经拆成工具意图解析、审批执行、结果回灌几个 helper，`try_lightweight_conversation()` 只负责串联 route。
   - regex/local fallback 只负责兜底解析安全工具意图，执行仍复用同一套 direct tool executor。
- 实际工具执行会通过 `core/tool_results.py` 生成 `serana.tool_result.v1`，在原始 `output` 内附加 `tool_result`，并同步写入 `tool_results`，统一包含工具名、输入、输出、状态、用户摘要和 artifact。
   - 这里已经接入统一 `PolicyGate`，高风险工具会先走审批。

## Goal 执行模式

- `direct`：简单 goal 在 lightweight loop 内直接完成，Goals API 会把唯一子任务标记为 `completed`。
- `planned`：中等 goal 进入 planning flow 做 analyze/decompose/summarize，但不调用 Aide/Forge，适合普通计划和清单。
- `delegated`：高复杂度或明确需要多代理的任务才进入 decompose/delegate/summarize，并调用 Aide/Forge。

## Aide / Forge Loop Action

- Aide/Forge 委派现在由 `loop.py` 的 planning flow 承载，不再保留旧 graph 入口。
- 阶段 trace 统一使用 `serana_planning_stage`，不再写出 `serana_graph_stage` 镜像。
- 新增 `serana_loop_action` trace，用来明确记录 `delegate_agents` 的 started/completed 状态，以及并发槽、Aide/Forge 会话数量。
- `delegate_node()` 会为每个 subtask 生成 assignment，包括任务类型、Aide/Forge 选择、优先级、重试次数和 Forge 并发数。
- 子代理生命周期使用 `serana_agent_lifecycle` 记录 started/completed/failed。
- Aide、Forge 和 Serana delegate 汇总都会输出统一 `tool_result`，并同步写入 state 内部 `tool_results`。
- 子任务部分失败时不会中断整轮对话；Serana 会保留失败原因并生成 `delegation_fallback_summary`，最后总结已完成项和剩余缺口。

## 与审批相关的入口

- `graph.py`
  - 初始状态包含 `approval_runtime` 和 `event_emitter`。
- `loop.py`
  - 流式执行时通过事件队列转发 `approval_requested` / `approval_resolved`。
- `nodes.py`
  - `_authorize_tool_call(...)` 统一处理策略判断、审批等待和拒绝后的用户回复。

## 维护约定

- 新增可自动调用的工具时，优先在 `nodes.py` 走统一工具选择和审批门禁。
- 改动轻量链路和 planning 升级策略时，优先在 `loop.py` 的 `ConversationLoop` 内集中处理，不要把 loop 决策散落到 API 层。
   - 新增流式事件时，先改 `loop.py`，再检查 `api/chat.py` 和 Android 端消费逻辑。
   - `nodes.py` 已经比较大；如果新增的是审批、浏览器或上下文公共逻辑，优先拆到 helper 或独立模块。

## Context Builder

- `context.py` 的 `SeranaContextBundle` 是当前统一上下文入口。
- 它集中组合 persona、resident memory、working memory、dynamic memory、instruction skills、runtime context 和当前可见工具。
- 节点层需要 system prompt 时使用 `build_state_system_prompt(...)`，需要用户请求上下文时使用 `build_state_request_context(...)`。
- 轻量路由会把可见工具清单放入 system prompt，后续分析、拆解和总结默认复用同一套 bundle，避免各节点手写不同格式的 prompt。
- 轻量路由判断当前意图时只带当前用户消息和 instruction skill，不带历史 memory、runtime 标签或工具清单进 user message，避免旧上下文或工具名污染路由。

## HTML 预览链路

- browser.create_html_preview 由 nodes.py 先做轻量路由，再调用 LLM 现场生成自包含 HTML。
- 生成结果会检查占位代码、交互脚本和控件事件绑定，避免出现空白页或按钮无响应的演示页。
