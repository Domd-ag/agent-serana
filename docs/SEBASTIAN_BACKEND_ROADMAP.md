# Sebastian 风格后端演进路线图

这份文档用于记录 Serana 后端向 Sebastian 风格靠拢的改造计划，同时保留我们当前项目里已经做得不错的部分。

## 总目标

把当前“部分轻链路 + 部分固定重链路”的后端，逐步演进成更统一的个人管家式后端：

- 以对话为优先入口
- 简单请求优先走工具
- 复杂任务按需变重
- skill、tool、memory、persona 的边界更清晰
- 审批、浏览器工具、技能生命周期更完整

---

## 第一阶段：立即可做

目标：先把当前已经在运行的架构彻底收顺，避免新旧执行模型长期并存。

### 1. 统一轻量对话链路

当前状态：

- chat 已经开始优先走轻链路
- 但部分 direct tool 逻辑仍然残留在旧分支和 fallback 里

要做的事：

- 把天气、时间、计算等简单请求统一收进一条 direct path
- regex 保留为兜底，而不是主路径
- direct reply 和 direct tool 使用同一套 planner 协议

预期结果：

- 简单请求全部走一条一致的轻链路

### 2. 降低请求内初始化和日志噪音

当前状态：

- skill 初始化已经从请求期挪到了启动期
- 启动日志仍然偏吵

要做的事：

- 将 `Loaded tool`、`Loaded skill` 等日志降为 `DEBUG`
- 明确区分：
  - 启动日志
  - 请求日志
  - 工具日志
- 保留高信号执行日志，压低细碎输出

预期结果：

- 后端终端更清爽，排查问题更轻松

### 3. 抽统一 context builder

当前状态：

- persona、memory、instruction skills、runtime context 都已经在用
- 但 prompt 组装仍然稍微有点分散

要做的事：

- 抽出一个统一的 context builder，负责组装：
  - persona
  - memory
  - instruction skills
  - runtime context
  - 当前可见工具

预期结果：

- 更接近 Sebastian 那种统一 `effective_system_prompt` 的组织方式

### 4. 明确 skill 运行分类

当前状态：

- 现在实际上已经存在 tool skill 和 instruction skill 的区别

要做的事：

- 正式定义 skill 分类：
  - 工具型 skill
  - 指令型 skill
  - 浏览器型 skill
  - 集成型 skill

预期结果：

- 后续继续扩展能力时结构更稳定，不容易混

---

## 第二阶段：中期重构

目标：从 graph-first 执行模型，逐步切到 loop-first 执行模型。

### 5. 引入真正的 agent loop

当前状态：

- chat 已经比以前轻
- goals 仍然是固定重链路

要做的事：

- 新建 `SeranaLoop` 或 `ConversationLoop`
- 行为类似 Sebastian：
  - 组装 prompt/context
  - 调一次模型
  - 如果有 tool intent / tool call，就执行工具
  - 再把结果回灌进 loop
  - 直到响应完成

预期结果：

- 请求会按需要变重，而不是默认就重

### 6. 让 goals 按需变重

当前状态：

- goals 目前默认还是：
  - analyze
  - decompose
  - delegate
  - summarize

要做的事：

- 简单 goal 在 loop 内直接完成
- 中等 goal 只在必要时拆解
- 真正复杂的 goal 才进入多代理 delegation

预期结果：

- goals 不再默认就是 3 次或更多模型调用

### 7. 让 Aide / Forge 融入 loop

当前状态：

- Aide 和 Forge 已经能工作
- 但它们仍然更偏 graph delegation 阶段的资产

要做的事：

- 让 delegation 成为 loop 内的原生动作
- 让 loop 自己决定：
  - 要不要委派
  - 委派给谁
  - 子代理结果如何回到当前会话

预期结果：

- 多代理执行成为运行时模型的一部分，而不只是图中的一个阶段

### 8. 统一工具结果回灌协议

当前状态：

- 工具结果已经会影响用户回复
- 但返回结构还没有完全统一

要做的事：

- 为所有工具定义统一结果结构：
  - tool 名
  - 输入
  - 输出
  - 状态
  - 面向用户的摘要

预期结果：

- 后续 weather、time、calculator、browser 都能走同一套回灌逻辑

---

## 第三阶段：产品化收尾

目标：把现在这个强原型，逐步推进成更完整的个人管家平台。

### 9. 接浏览器 / 网页工具

当前状态：

- 本地工具已经有了
- weather 已经能联网
- browser tooling 还没进主执行链

要做的事：

- 把浏览器和网页工具接进 skill/tool 层
- 再统一纳入主执行模型

预期结果：

- 系统不只是“会回答”，而是“能替你操作外部世界”

### 10. 做审批流

当前状态：

- audit / timeline / trace 已经很强
- 但审批和执行控制还没产品化

要做的事：

- 对高风险动作加入审批
- 支持：
  - 本次允许
  - 持续允许
  - 执行前说明原因

预期结果：

- 系统从“可观察”提升到“可控执行”

### 11. 补完整个 skill 生命周期

当前状态：

- 本地和远程 skill 安装已经有基础能力
- instruction skill 已经能影响 chat 和 goals

要做的事：

- 完整支持：
  - 安装
  - 更新
  - 卸载
  - 来源显示
  - 信任状态
  - 生效范围

预期结果：

- skill 变成平台能力，而不是附属功能

### 12. 完善部署与运行维护

当前状态：

- 本地启动已经可用
- 开发体验正在逐步变好

要做的事：

- 完善启动脚本
- 做集中配置
- 明确版本 / 更新流程
- 支持日志级别配置
- 收口部署文档

预期结果：

- 系统更容易运行、更新和维护

---

## 推荐实施顺序

1. 彻底统一 chat 的轻链路
2. 抽统一 context builder
3. 引入真正的 agent loop
4. 让 goals 按需变重
5. 接 browser / web 工具
6. 做审批流
7. 补完整个 skill 生命周期

---

## 当前建议的下一步

最值得现在立刻继续做的是：

### 彻底统一 chat 的轻链路

原因：

- 风险最低
- 收益最大
- 最直接贴近 Sebastian 风格
- 能继续减少简单请求的不必要模型调用

