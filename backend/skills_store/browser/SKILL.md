# Browser

当 Serana 需要打开公开网页、检查页面、进行轻量网页搜索、截图、观察视觉状态或管理浏览器下载时使用这个技能。

## 工具

- `open_page(url, max_chars=4000)`：打开公开 `http` 或 `https` URL，返回标题、URL、正文文本和可交互元素摘要。
- `observe_page(max_chars=4000)`：观察当前由 `open_page` 或 `search_web` 打开的页面。
- `search_web(query, max_results=5)`：打开搜索结果页，返回可见结果候选和页面文本。
- `act_page(action, target=None, value=None)`：执行小型受控动作。支持 `click`、`type`、`press`、`select`、`wait_for_text`、`wait_for_selector`、`back`、`forward`、`reload`。
- `capture_page(full_page=False)`：截取当前页面，返回用户可见截图 artifact。
- `look_page(full_page=False)`：截取运行时视觉快照，只交给 Serana 的模型观察，不作为用户可见 artifact。
- `browser_downloads(action="list", filename=None)`：列出浏览器下载，或把指定下载文件作为 artifact 发给前端。
- `create_html_preview(title, html)`：创建本地交互式 HTML 预览 artifact，用于演示或小型可视化说明。
- `close_browser()`：关闭受控浏览器会话并释放 Playwright 资源。

## 策略

- 优先使用天气、计算器、时间、记忆等结构化本地技能；只有用户明确要求浏览、搜索、打开网页，或本地技能无法回答当前网页信息时再使用浏览器。
- 不访问本机、内网、私有 IP、包含账号密码的 URL。
- 不替用户输入密码、密钥、支付信息，也不执行提交、购买、删除、账号设置等高影响操作。
- `act_page` 会拦截看起来涉及凭证、付款、账号、提交或删除的目标；遇到这类页面请让用户自己操作。
- `look_page` 是模型内部视觉观察通道，不要把它描述成已经给用户发送了截图；需要给用户看图时使用 `capture_page`。
- `create_html_preview` 必须是自包含页面，只允许内联 CSS/JS，不允许外链、表单、iframe、fetch、XMLHttpRequest、WebSocket 或 EventSource。
