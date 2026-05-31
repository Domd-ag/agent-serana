# screens 目录说明

这里放 Compose 页面和页面级弹窗。

## 当前重点

- `ChatScreen.kt`
  - 聊天主界面、流式状态、审批弹窗和键盘 inset 处理
- `SkillsScreen.kt`
  - 技能列表、ClawHub 市场、本地 ZIP 导入、生命周期状态、更新、范围切换和卸载入口

## 技能页链路

1. 用户点击“导入 ZIP”
2. 系统文件选择器返回本地文件
3. `SkillsScreen` 读取字节后交给 `SkillsViewModel`
4. ViewModel 调用 `ApiService.uploadSkill(...)`
5. 如果后端返回 `approval_required`，页面弹出审批对话框
6. 审批通过后，ViewModel 再次调用上传接口完成导入
7. 已安装技能的生命周期状态通过 `/skills/{skill_name}/lifecycle` 获取，更新和卸载都走审批流

## 维护约定

- 需要文件选择器、权限或 Activity Result 时，优先放在页面层处理
- 业务状态和网络调用放到 ViewModel，不要堆在 `Composable` 里
- 聊天页的键盘避让依赖 `MainActivity` 的 edge-to-edge inset 分发，以及消息区容器的 `imePadding()`；顶部悬浮栏不要跟着键盘移动
- 聊天首页已经手动处理顶部和底部 inset，`Scaffold` 根容器不要再把默认 `paddingValues` 叠到整页根节点上
- 聊天页流式输出时，只有用户原本就在底部附近才会自动跟随到最新消息；手动上翻历史时不要抢滚动位置
- 输入区保持胶囊风格，但收紧的是最外层包裹栏的高度和轮廓，内层文字输入区尽量维持原有手感
- `html_preview` 类型的浏览器产物不再走外部下载入口，而是在聊天页内以“打开演示”卡片触发浮层 `WebView` 预览
- “已完成”状态徽标只在消息首次切换到 `FINALIZED` 时短暂显示一次，避免同一条消息后续刷新时闪烁
- 顶部 Serana 胶囊在等待回复、thinking、streaming 或重试期间，会在名称后显示轻量旋转等待图标，对齐 Sebastian 的 agent pill 状态反馈。

## 聊天输出格式

- 聊天页参考 Sebastian 的块流式输出：用户消息保留右侧胶囊气泡，助手消息以自然文本块为主，减少大卡片包裹感。
- thinking blocks 和 tool traces 会在 UI 层合并为可折叠执行摘要，折叠态显示胶囊步骤条和当前步骤摘要，展开后只展示用户可理解的简短步骤。

## 助手正文排版

- 助手正文使用轻量 Markdown 风格渲染，不新增依赖；当前支持标题、段落、项目列表、编号列表和代码块。
- 浏览器 artifact 卡片参考 Sebastian 附件块，作为消息内容的一部分展示，避免过重的按钮感。
- 工具执行摘要和浏览器 artifact 优先读取后端统一的 `output.tool_result`，旧的 `summary` / `artifact` 字段只作为兼容兜底。

## 行内排版

- 轻量 Markdown 渲染已支持 **粗体**、行内代码 和 > 引用块；引用块使用淡色背景和左侧竖线展示。
- 行内代码使用等宽字体和轻量底色，保持文本可读，不引入额外 Markdown 依赖。
