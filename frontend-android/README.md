# frontend-android 目录说明

这里是 Serana 的 Android 前端工程，负责聊天、设置、技能页和后端 API 对接。

## 当前重点模块

- `app/src/main/java/com/serana/app/ui/screens/`
  - Compose 页面层
- `app/src/main/java/com/serana/app/viewmodel/`
  - 页面状态、请求编排、审批交互
- `app/src/main/java/com/serana/app/data/api/`
  - Retrofit 接口、流式聊天和基础网络配置

## 当前技能页能力

- 本地技能列表、启停、详情
- 已安装 managed skill 的卸载审批
- ClawHub 远程技能安装审批
- 本地 ZIP 技能包导入与审批续传

## 维护约定

- 涉及页面交互先看 `ui/screens/README.md`
- 涉及状态和审批链路先看 `viewmodel/README.md`
- 涉及后端协议或上传方式先看 `data/api/README.md`
