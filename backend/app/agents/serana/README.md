# serana 目录说明

这里是 Serana 作为主 Agent 的核心实现。它负责理解请求、组合上下文、选择工具、在必要时升级到 planning flow，并把结果整理成用户可读回复。

## 目录结构

```text
serana/
+-- __init__.py
+-- context.py    统一 context builder、请求上下文、working memory、instruction skill 注入
+-- graph.py      AgentState 类型与初始状态构建
+-- loop.py       ConversationLoop 统一运行时、lightweight route、planning flow、Forge loop action、流式事件转发
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
   - 当前会话最近消息会额外作为 `recent_history_context` 单独注入，短跟进恢复只依赖这段即时历史，避免把长期事实或相关记忆误当成上一轮澄清。
2. `serana.py`
   - 创建初始状态，并把审批运行时能力注入到 state。
   - loop 升级后用显式 planning flow 调用 analyze/decompose/delegate/summarize。
3. `loop.py`
   - 由 `ConversationLoop` 统一承载 plan-act-escalate 决策。
   - 先尝试 lightweight direct route；安全的简单 goal 也可以在这里直接完成。
   - 需要更重处理时进入 loop 内置 planning flow，并携带 lightweight route 决策作为上下文。
   - `execute_planning_flow(...)` 在 loop 内按 analyze/decompose/delegate/summarize 运行；Forge 委派会记录为 `serana_loop_action`。
   - 流式模式下负责把运行时审批事件转成 SSE 事件。
4. `nodes.py`
   - 负责 direct reply、direct tool、browser summarize、委派、多步总结。
   - 普通一次性请求，比如旅行行程、学习计划、日程安排、实现思路、代码示例、解释说明和对比总结，会优先转成 direct reply，避免把内部 planning/delegation 步骤当作最终回答展示给用户。
   - `delegated` 不是最终判决；进入委派前会先经过 LLM route reviewer 复判。只要当前消息可在一轮内直接回答，就直接生成用户可读回复；只有确实需要工具、网页、项目文件、编译测试、部署或长期任务时才继续委派。
   - direct tool 轻链路已经拆成工具意图解析、审批执行、结果回灌几个 helper，`try_lightweight_conversation()` 只负责串联 route。
   - `memory_manager.memory_search` 只用于显式记忆查询；“继续、统计、合计、估算、总共多少钱”等上下文推理问题会转为 contextual direct reply，避免把原始历史问答当成最终回答。
   - 上下文承接现在是常态能力，不再只识别固定短语；像“继续”“详细一点”“那代码呢”“帮我去网上看看”这类省略式跟进，会优先结合最近上下文补全主题，再决定是直接续答还是转成具体浏览器查询。代码类跟进也会基于上一轮主题生成，不再落回泛化示例。
   - 省略式跟进会先经过轻量 `contextual_followup_assessment`：由 LLM 判断是否承接上一轮、承接主题是什么、要直接续答、查网页，还是正在回答 Serana 上一轮提出的澄清问题；规则判断只作为兜底，避免继续靠短语表堆补丁。
   - 当用户用“上海”“Java”“5000 元”“明天”这类短回答补充缺失信息时，assessment 会先恢复成独立完整请求，再重新进入正常技能、工具和回复路由，不会把短回答当成全新话题。
   - 结构化阶段统一通过容错 JSON 解析器读取模型输出，支持 Markdown JSON 围栏、`<think>` 后正文、内容块列表和夹杂说明文字的 JSON。
   - 一次性旅行、学习、日程等计划请求会在 structured route 前直接生成实用答复；route JSON 失效时也会优先走 direct fallback，不再无条件升级到 analyze/decompose。
   - 完整的短社交消息，例如问候、致谢、告别和简短确认，会在上下文评估、Skill 选择与 structured route 前直接回复；它们只调用一次回复 LLM，不会因历史对话误判为跟进，也不会要求模型先输出路由 JSON。
   - 工具选择失败不再默认进入 `delegated`；能直接回答的请求走 direct fallback，剩余情况最多进入 `planned`，避免把简单问题误推给 Forge。
   - 已经能够自洽表达目标的一次性计划、解释和代码请求，不再额外调用 `contextual_followup_assessment`；只有确实省略主题或正在回答澄清问题的短消息才进入跟进判断。
   - analyze 使用结构化 fallback 后，decompose 会改用确定性任务模板，避免让同一模型连续返回无效 JSON 并重复产生告警。
   - conversation route、上下文跟进判断、Skill 选择、delegated reviewer、analyze 和 decompose 等结构化决策，在 OpenAI 兼容网关上会显式启用 JSON response mode，并保留确定性降级路径；可恢复的格式偏差只记录为 `DEBUG`，日常 `INFO` 日志不再刷内部恢复提示。
   - 流式状态使用用户可读中文文案；内部 route、tool selection、planning stage 和 summarize trace 只作为调试数据保留，不作为最终回答内容。
   - regex/local fallback 只负责兜底解析安全工具意图，执行仍复用同一套 direct tool executor。
- 实际工具执行会通过 `core/tool_results.py` 生成 `serana.tool_result.v1`，在原始 `output` 内附加 `tool_result`，并同步写入 `tool_results`，统一包含工具名、输入、输出、状态、用户摘要和 artifact。
   - 这里已经接入统一 `PolicyGate`，高风险工具会先走审批。

## Goal 执行模式

- `direct`：简单 goal 在 lightweight loop 内直接完成，Goals API 会把唯一子任务标记为 `completed`。
- `planned`：中等 goal 进入 planning flow 做 analyze/decompose/summarize，但不调用 Forge，适合普通计划和清单。
- `delegated`：高复杂度或明确需要 worker 执行的任务才进入 decompose/delegate/summarize，并调用 Forge。

`planned` 和 `delegated` 都是内部执行方式，不是用户答案格式：

- `planned` 的子任务仅作为内部推理提纲；最终总结必须重新回答用户原问题，不能返回 `待处理` 清单或执行状态。
- `delegated` 的最终总结必须基于 Forge 实际产出的内容；没有可用结果时应明确说明缺少什么，不能把步骤或完成状态冒充答案。
- 原始用户问题是所有路线共享的 answer contract。每个 Forge 子任务都会携带完整原始问题，避免拆解后丢失对象、约束和交付物。
- 最终回答出口会拦截内部执行报告样式，包括待处理/进行中/已完成状态、推进提示和内部任务清单。

## Forge Loop Action

- Forge 委派现在由 `loop.py` 的 planning flow 承载，不再保留旧 graph 入口。
- 阶段 trace 统一使用 `serana_planning_stage`，不再写出 `serana_graph_stage` 镜像。
- `serana_loop_action` trace 用来明确记录 `delegate_agents` 的 started/completed 状态，以及并发槽和 Forge 会话数量。
- `delegate_node()` 会为每个 subtask 生成 assignment，包括任务类型、优先级和重试次数；Serana 直接控制 Forge 并发与重试。
- Forge 必须为每个成功子任务返回可供最终回答使用的实质内容，由 Serana 在最终总结时统一回灌。
- 子代理生命周期使用 `serana_agent_lifecycle` 记录 started/completed/failed。
- Forge 和 Serana delegate 汇总都会输出统一 `tool_result`，并同步写入 state 内部 `tool_results`。
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
- instruction skill 不再无差别全部注入；现在会先按当前用户问题做相关性筛选，优先带入匹配领域的本地 skill 指导，避免一个领域的 skill 干扰另一个领域的回复。
- 相关性判断会优先读取 skill manifest 里的 `capabilities` 和 `intents`；没有显式声明时，才退回到 skill 名称、registry slug 和描述做兜底匹配。
- 天气领域会先区分实时数据查询和普通讨论；“上海明天天气”会进入天气能力链路，“你喜欢什么天气 / 什么天气适合跑步”保持为普通对话，不加载天气 skill，也不触发浏览器。
- 对话持久化后会触发 memory consolidation：LLM 先提取 `fact/preference/summary/episode` 候选，再由本地流程校验、去重、写入；后续检索优先注入 summary。

## Skill 接入优先级

- 普通自然语言不会自动触发 `runtime=python` 或 `runtime=script` 技能。
  这类技能只通过聊天框里的显式命令调用：`@skill_name 参数...`。API 层会在进入 Serana loop 之前解析命令、校验参数、调用对应工具，并把结果作为助手回复返回。
- `runtime=instruction` 技能会自动参与 Serana。
  安装并启用后，它的 `SKILL.md` 会按 `capabilities`、`intents`、名称和描述做相关性筛选，然后注入当前轮 prompt。它不会被当成脚本执行，也不会要求用户输入 `@`。
- 天气自然语言请求直接走浏览器链路。
  比如“上海天气如何”“明天北京会下雨吗”会进入 `browser.open_page` / observe / summarize，不再优先调用已安装的天气脚本技能。若用户明确想执行某个天气脚本，应使用 `@weather_cn_pro 上海` 这类显式调用。
- 内置安全直达工具仍保留。
  明确算术、时间、记忆保存/检索等系统内置能力继续走 direct tool executor；它们不属于 SkillHub 下载的 python/script 技能自动命中。
- Browser 仍是网页、实时搜索和 HTML preview 的统一入口。
  上网搜索、打开页面、网页观察、截图、下载列表和交互式演示预览都从 browser 工具链进入。

## 回复风格

- `persona.md` 定义 Serana 的完整人格和用户可见回答习惯；当前版本完整合并了用户提供的《上古卷轴5·瑟拉娜》人物卡与项目原有的人格行为规范，既保留瓦尔奇哈家族、哈孔、瓦蕾莉卡、千年封印、黎明守卫和纯血吸血鬼等原版背景，也保留用户作为当前龙裔、现代私人管家关系、自我介绍、场景化反应、记忆连续性、输出格式与现实任务执行规则。
- `context.py` 的 `USER_FACING_RESPONSE_STYLE` 会随 system prompt 注入，确保 direct reply、工具结果总结和委派总结都遵守同一套输出规范。
- 生活建议、旅行、美食、购物、日程、技术、代码和架构类回答都可以使用少量 emoji；技术类只用于提示、风险、修复、验证等结构标记，不能干扰代码块和命令。
- 所有 emoji 必须符合 Serana 人设：清冷、克制、实用，偏夜色、烛光、罗盘、警示、防护、刀锋、天气等意象，避免可爱、庆祝、表情包式符号。
- 计算、时间、天气、浏览器和记忆等工具直返路径会统一补一个符合人设的前缀 emoji，避免绕过 LLM 时风格丢失。
- 记忆、工具和代理结果要转成自然语言，不向用户暴露内部类别、route、artifact 或 tool trace。
- `persona.md` 也包含 Serana 的背景设定与场景化反应：当用户问她的家庭、经历、身份、龙裔，或提到阳光、十字架、大蒜、黎明守卫、古墓等语境时，可以露出少量清冷吸血鬼式口吻；普通任务仍以私人管家的实用回答为主。

## HTML 预览链路

- browser.create_html_preview 由 nodes.py 先做轻量路由，再调用 LLM 现场生成自包含 HTML。
- 生成结果会检查占位代码、交互脚本和控件事件绑定，避免出现空白页或按钮无响应的演示页。
- 复用缓存前只能做无副作用探测；缓存未命中时必须继续现场生成，不能把空 HTML 写成新的预览页。
- 只有用户明确说“之前、上次、刚才、打开之前那个”等复用语义时，才会直接返回已有缓存；普通“生成/演示某个主题”会重新生成并刷新该主题缓存，避免旧页面冒充新需求。
- 当用户对上一轮演示说“改成/修改/调整/加上/速度可调/重新生成”等短跟进时，会从最近会话恢复上一轮 HTML 预览主题，读取旧 HTML 作为编辑底稿，再生成新版本并更新同一主题缓存；取不到旧文件时才退回按上下文重新生成。

## 浏览器执行链

- `browser.open_page` / `browser.observe_page` / `browser.act_page` 不再只做一次性工具总结，而是进入浏览器 session flow：先执行当前工具，再把页面观察结果交给 LLM 判断下一步。
- 浏览器 session flow 最多追加少量安全步骤，例如公开页面打不开时尝试公共替代入口，或打开后自动观察当前页面。
- session flow 单轮最多执行 6 个步骤、最多打开 2 个页面；相同页面上的重复动作会被停止，失败步骤后不会继续 Observe。
- 浏览器失败回复会转成用户可读说明，不再把内部 URL、文件路径、原始异常或网页片段直接作为最终答案。
- 内置轻量运行时只访问公开 `http/https` 页面，并限制响应体积；页面交互、截图和视觉观察在没有完整浏览器运行时时会明确返回“不支持”。
- 每个浏览器步骤都会即时发出 `tool_call` 流式事件，Android 端按 `Browser Open`、`Browser Observe`、`Browser Act` 展示，形成稳定的执行链摘要。
