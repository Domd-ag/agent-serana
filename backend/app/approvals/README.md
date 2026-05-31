# approvals 目录说明

这里放 Serana 的统一审批能力，用来拦住高风险动作，再把结果回灌给聊天、技能页和审计时间线。

## 文件结构

```text
approvals/
+-- __init__.py
+-- manager.py   维护待审批请求、持续允许授权、等待结果、消费结果与清理
+-- policy.py    PolicyGate，判断某个动作是否需要审批以及风险等级
+-- reviewer.py  生成面向前端展示的中文审批文案
+-- service.py   通用审批提交逻辑与审计落库
```

## 当前职责

- 为聊天里的浏览器动作提供审批门禁
- 为技能市场安装、本地 ZIP 导入、已安装技能卸载提供审批门禁
- 统一输出 `approval_requested` / `approval_resolved` 审计事件
- 审批请求会带 `reason` 和 `approval_options`，前端可以展示“为什么需要审批”以及“本次允许 / 持续允许 / 拒绝”
- `approval_scope=always` 会创建内存级持续允许授权；授权按 tool、operation、risk 和关键参数匹配，服务重启后失效
- `ApprovalManager.shutdown()` 会同时清理 pending 请求和持续允许授权，避免测试或重启后的授权残留
- 管理两步式审批流程：
  1. 业务接口先返回 `approval_required`
  2. 前端提交审批结果
  3. 业务接口再用 `approval_request_id` 完成后续动作

## 维护约定

- 新增高风险动作时，先改 `policy.py`，不要把审批判断散落在业务节点里。
- 前端可见的标题、摘要、风险提示统一放在 `reviewer.py`。
- 高风险动作默认只允许 `once / deny`，中风险动作可以提供 `always`。
- 需要审批后继续执行的流程，要明确是否保留请求：
  - `skills_marketplace`：审批通过后保留，等待真正安装
  - `skills_upload`：审批通过后保留，并保留暂存技能包
  - 其他来源：审批结果落库后直接清理
- 本地技能上传的暂存目录由 `SkillManager` 管理；如果审批拒绝或过期，要同步清理暂存文件。
