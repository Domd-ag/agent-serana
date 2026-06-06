# screens 目录说明

这里放 Compose 页面和页面级弹窗。

## 当前重点

- `ChatScreen.kt`
  - 聊天主界面、流式状态、审批弹窗、键盘 inset、HTML 预览浮层和执行链展示。
  - thinking blocks 和 tool traces 会合并成 Sebastian 风格的 `Thought for Ns` 执行摘要。
  - 浏览器步骤默认展示为 `Browser Open`、`Browser Observe`、`Browser Act` 等用户可读块。
- `SkillsScreen.kt`
  - 技能列表、SkillHub 市场、本地 ZIP 导入、生命周期状态、更新、范围切换和卸载入口。
- `SettingsScreen.kt`
  - 服务器连接与 LLM 配置切换；服务器地址本地保存，Base URL、API Key、模型三项保存到当前服务器。

## 聊天页维护约定

- 业务状态和网络调用放到 ViewModel，不要堆在 `Composable` 里。
- 键盘避让依赖 `MainActivity` 的 edge-to-edge inset 分发，以及消息区容器的 `imePadding()`；顶部悬浮栏不要跟着键盘移动。
- 输入框聚焦、键盘展开和用户发送消息时会把消息区轻推到最新位置；流式输出时，只有用户原本就在底部附近或刚发送消息后才自动跟随，手动翻历史时不要抢滚动位置。
- 消息时间统一通过 `formatMessageTimestamp()` 解析服务端 ISO 时间，并转换为手机本地时区显示。
- 设置弹窗读取服务器配置时也必须保留“连接服务器”表单可编辑；服务器不可达不能用整块 loading 阻塞地址修改。
- `html_preview` 类型产物在聊天页内以“打开演示”卡片触发浮层 `WebView` 预览，不走外部下载。
- 顶部 Serana 胶囊在等待回复、thinking、streaming 或重试期间，会在名称后显示轻量旋转等待图标。
- 工具执行摘要优先读取后端统一的 `output.tool_result.user_summary`，旧字段只作为兼容兜底。

## 正文排版

- 助手正文使用轻量 Markdown 风格渲染，支持标题、段落、项目列表、编号列表、代码块、粗体、行内代码和引用块。
- 用户消息保留右侧胶囊气泡；助手消息以自然文本块为主，减少过重的卡片包裹感。
