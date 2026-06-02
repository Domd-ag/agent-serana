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
   - memory context 现在包含 profile facts、summary-first artifacts、episode 兜底和当前会话历史证据。
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
   - 普通一次性请求，比如旅行行程、学习计划、日程安排、实现思路、代码示例、解释说明和对比总结，会优先转成 direct reply，避免把内部 planning/delegation 步骤当作最终回答展示给用户。
   - `delegated` 不是最终判决；进入委派前会先经过 LLM route reviewer 复判。只要当前消息可在一轮内直接回答，就直接生成用户可读回复；只有确实需要工具、网页、项目文件、编译测试、部署或长期任务时才继续委派。
   - direct tool 轻链路已经拆成工具意图解析、审批执行、结果回灌几个 helper，`try_lightweight_conversation()` 只负责串联 route。
   - `memory_manager.memory_search` 只用于显式记忆查询；“继续、统计、合计、估算、总共多少钱”等上下文推理问题会转为 contextual direct reply，避免把原始历史问答当成最终回答。
   - 上下文承接现在是常态能力，不再只识别固定短语；像“继续”“详细一点”“那代码呢”“帮我去网上看看”这类省略式跟进，会优先结合最近上下文补全主题，再决定是直接续答还是转成具体浏览器查询。代码类跟进也会基于上一轮主题生成，不再落回泛化示例。
   - 省略式跟进会先经过轻量 `contextual_followup_assessment`：由 LLM 判断是否承接上一轮、承接主题是什么、要直接续答还是查网页；规则判断只作为兜底，避免继续靠短语表堆补丁。
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
- 它集中组合 persona、用户可见回复风格、resident memory、working memory、dynamic memory、instruction skills、runtime context 和当前可见工具。
- 节点层需要 system prompt 时使用 `build_state_system_prompt(...)`，需要用户请求上下文时使用 `build_state_request_context(...)`。
- 轻量路由会把可见工具清单放入 system prompt，后续分析、拆解和总结默认复用同一套 bundle，避免各节点手写不同格式的 prompt。
- 轻量路由判断当前意图时只带当前用户消息和 instruction skill，不带历史 memory、runtime 标签或工具清单进 user message，避免旧上下文或工具名污染路由。
- 对话持久化后会触发 memory consolidation：LLM 先提取 `fact/preference/summary/episode` 候选，再由本地流程校验、去重、写入；后续检索优先注入 summary。

## 回复风格

- `persona.md` 定义 Serana 的完整人格和用户可见回答习惯；当前版本以用户提供的《上古卷轴5·瑟拉娜》人物卡为底层设定，覆盖瓦尔奇哈家族、哈孔、瓦蕾莉卡、千年封印、用户作为当前龙裔、黎明守卫、纯血吸血鬼身份、场景化反应和现代私人管家关系。
- `context.py` 的 `USER_FACING_RESPONSE_STYLE` 会随 system prompt 注入，确保 direct reply、工具结果总结和委派总结都遵守同一套输出规范。
- 生活建议、旅行、美食、购物、日程、技术、代码和架构类回答都可以使用少量 emoji；技术类只用于提示、风险、修复、验证等结构标记，不能干扰代码块和命令。
- 所有 emoji 必须符合 Serana 人设：清冷、克制、实用，偏夜色、烛光、罗盘、警示、防护、刀锋、天气等意象，避免可爱、庆祝、表情包式符号。
- 计算、时间、天气、浏览器和记忆等工具直返路径会统一补一个符合人设的前缀 emoji，避免绕过 LLM 时风格丢失。
- 记忆、工具和代理结果要转成自然语言，不向用户暴露内部类别、route、artifact 或 tool trace。
- `persona.md` 也包含 Serana 的背景设定与场景化反应：当用户问她的家庭、经历、身份、龙裔，或提到阳光、十字架、大蒜、黎明守卫、古墓等语境时，可以露出少量清冷吸血鬼式口吻；普通任务仍以私人管家的实用回答为主。

## HTML 预览链路

- browser.create_html_preview 由 nodes.py 先做轻量路由，再调用 LLM 现场生成自包含 HTML。
- 生成结果会检查占位代码、交互脚本和控件事件绑定，避免出现空白页或按钮无响应的演示页。

## 浏览器执行链

- `browser.open_page` / `browser.observe_page` / `browser.act_page` 不再只做一次性工具总结，而是进入浏览器 session flow：先执行当前工具，再把页面观察结果交给 LLM 判断下一步。
- 浏览器 session flow 最多追加少量安全步骤，例如公开页面打不开时尝试公共替代入口，或打开后自动观察当前页面。
- 每个浏览器步骤都会即时发出 `tool_call` 流式事件，Android 端按 `Browser Open`、`Browser Observe`、`Browser Act` 展示，效果对齐 Sebastian 的执行链。
