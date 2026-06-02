# Sebastian 风格后端演进路线图

这份文档用于记录 Serana 后端向 Sebastian 风格靠拢的改造路径，同时保留我们当前项目里已经验证过的有效设计。

## 总目标

把当前后端逐步演进成更统一的个人管家式架构：

- 以对话为优先入口
- 简单请求优先走轻链路和工具
- 复杂任务按需升级，而不是默认变重
- skill、tool、memory、persona 的边界清晰
- 审批、浏览器、技能生命周期完整可维护

## 当前阶段状态

### 第一阶段：基础统一

已完成：

- 统一 `ConversationLoop` 作为 chat / goal 的主入口。
- direct tool 轻链路已拆成 planner、tool intent resolver、shared executor。
- `Loaded tool`、`Loaded skill` 等噪音日志已下调，启动日志、请求日志、工具日志已基本分层。
- `SeranaContextBundle` 已作为统一 context builder 落地。
- skill 运行分类已明确为 instruction、tool、browser、integration 等几类。

仍需持续维护：

- 保持 regex / 本地规则只做兜底，不重新长回主路径。
- 新增工具时继续走统一 direct tool executor。

### 第二阶段：运行时模型统一

已完成：

- `ConversationLoop` 已承载轻链路、planning flow 和升级决策。
- goals 已支持 `direct` / `planned` / `delegated` 三档执行。
- Aide / Forge 已作为 loop 内原生 delegation 动作，而不是旧 graph 阶段资产。
- 旧 `GraphExecutor`、`serana_graph_stage` 等兼容入口已移除。
- direct tools、browser tools、Aide、Forge、delegate 已统一使用 `serana.tool_result.v1`。

仍需持续优化：

- 委派决策的智能度还可以继续提升。
- 子代理生命周期 trace 仍可继续细化。
- 工具结果回灌虽然统一了协议，但前后端消费还可以继续收口。

### 第三阶段：产品化收尾

已完成：

- 浏览器工具已经接入 skill / tool 层，并纳入主执行模型。
- 浏览器工具支持 `open / search / observe / act / capture / look / download / preview / close` 等产品化状态返回。
- 审批流已具备“本次允许 / 持续允许 / 拒绝”链路。
- skill 生命周期已覆盖安装、更新、卸载、来源、信任状态和生效范围。
- 本地启动脚本、配置集中化、运行文档已初步收口。

仍需继续打磨：

- 浏览器链路的稳定性、失败恢复和多步网页任务质量。
- SkillHub 市场链路的兼容性和可观测性。
- 部署、版本、更新流程的一致性。

## 推荐实施顺序

1. 保持 chat 轻链路持续收口
2. 保持 context builder 单一入口
3. 继续细化 agent loop 的委派决策
4. 继续优化 goals 的按需变重
5. 持续打磨 browser / web 工具链路
6. 继续增强审批与执行控制
7. 持续完善 skill 生命周期
8. 最后做部署、验证和文档收尾

## 现在最值得继续做的事

### 1. 浏览器链路继续产品化

原因：

- 它最直接影响“能不能像 Sebastian 那样替用户操作外部世界”。
- 当前已经接上主链路，继续优化收益最高。
- 前端执行摘要、浏览器观察、截图和 HTML preview 都已经有基础，适合继续打磨体验。

### 2. 记忆链路继续向 summary-first 靠拢

原因：

- 这决定 Serana 会不会因为历史对话而答非所问。
- summary、episode、facts、preference 的沉淀和检索策略，直接影响长会话质量。

### 3. 技能市场和技能生命周期继续收口

原因：

- SkillHub 已经接入，但市场搜索、安装、审批、更新、卸载、上下文注入这条链还需要长期验证。
- 这是后续扩展 Serana 能力的基础设施。
