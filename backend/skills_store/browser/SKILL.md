# Browser

Serana 的内置浏览器技能，用于查询、打开和观察公开网页，并向前端返回统一 artifact。

## 工具

- `search_web`：搜索公开网页，并把搜索结果页保存为当前页面。
- `open_page`：打开一个公开 `http/https` 页面。
- `observe_page`：读取当前页面的可见文本。
- `act_page`：声明页面交互能力；轻量运行时会明确返回“不支持”，不会伪装成成功。
- `capture_page` / `look_page`：声明截图与视觉观察能力；轻量运行时不可用时会返回标准失败状态。
- `browser_downloads`：列出浏览器下载目录，或把指定文件作为 download artifact 发送给前端。
- `create_html_preview`：生成自包含 HTML 演示，并返回可在 Android WebView 内打开的 `html_preview` artifact。
- `close_browser`：清理当前页面状态。

## 安全边界

- 只允许公开 `http/https` 页面，拒绝本机、局域网和非全局 IP。
- 单次页面响应最多读取 2 MiB，文本最多回灌 12000 个字符。
- 重定向后的地址也会重新校验。
- HTML Preview 禁止外部联网、iframe 和未绑定事件的交互控件。
- 下载文件只能从受控下载目录按纯文件名发送。

## 会话约定

- 每一步都返回 `browser_state`，明确说明 `status`、`page_open` 和允许的下一步。
- 页面打开失败后不再继续 Observe。
- Agent Loop 会阻止重复浏览器动作，并限制单轮打开页面和总步骤数量。
