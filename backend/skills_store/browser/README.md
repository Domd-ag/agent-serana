# browser skill

受控浏览器 skill，参考 Sebastian 的浏览器能力，提供公开网页打开、搜索、页面观察、轻量交互、截图、模型视觉观察、下载管理和 HTML 预览生成。

## 目录结构

```text
browser/
+-- __init__.py  Playwright 受控浏览器运行时和工具实现
+-- skill.json   工具 manifest
+-- SKILL.md     Serana 使用说明
```

运行时会生成：

- `profile/`：Playwright persistent context，用于保存 cookie/local storage。
- `screenshots/`：用户可见截图，以及 `look_page` 的短期运行时视觉快照。
- `previews/`：自包含 HTML 预览页。
- `downloads/`：浏览器下载文件和 `downloads.jsonl` 清单。

这些目录是本地运行产物，已在 `.gitignore` 中忽略，不作为源码目录维护 README。

## 工具能力

- `open_page`：打开公开 HTTP/HTTPS 页面，返回正文摘要和可交互元素摘要。
- `observe_page`：读取当前页面标题、URL、正文和可交互元素。
- `search_web`：打开搜索页并提取可见搜索结果。
- `act_page`：执行 `click`、`type`、`press`、`select`、等待、前进后退、刷新等小动作。
- `capture_page`：生成用户可见截图 artifact。
- `look_page`：生成运行时视觉快照，只供 Serana 多模态总结使用，不暴露为用户 artifact。
- `browser_downloads`：列出浏览器下载，或把下载文件作为 artifact 发给前端。
- `create_html_preview`：生成安全的自包含 HTML 演示页；运行时要求传入真实 HTML 草稿，不再自动替换成内置 demo。若仍是占位代码，或包含按钮等可操作控件但没有真实事件绑定，会直接拒绝。
- `close_browser`：释放 Playwright 资源。

## 产品化返回结构

- 所有浏览器工具都会返回 `browser_state`，用于前端和调试层判断当前页面状态。
- `browser_state.status` 常见值：`ready`、`missing_page`、`failed`、`blocked`、`preview_ready`、`download_ready`、`closed`。
- `browser_state.page_open` 表示当前是否存在可继续操作的页面。
- `browser_state.next_actions` 给出下一步可尝试动作，例如 `open_page`、`search_web`、`observe_page`、`capture_page`。
- 可恢复失败会返回 `recoverable: true`，Serana 可以继续建议用户下一步，而不是把浏览器链路直接中断。

## 安全边界

- 只允许公开 `http`/`https` URL，拦截 localhost、本机、内网、保留地址和带账号密码的 URL。
- `act_page` 会拦截看起来涉及凭证、支付、账号、删除、提交等高影响操作的目标。
- `look_page` 和 `capture_page` 分离：前者只给模型看，后者才生成前端 artifact。
- HTML 预览过滤外链、表单、iframe 和网络访问能力。
- screenshot、preview、download 都由 `app/api/browser.py` 通过受控路径暴露。

## 维护约定

新增浏览器工具时同步更新 `skill.json`、`SKILL.md`、本 README，以及前端 artifact 展示逻辑。修改运行时产物目录时，同步检查 `.gitignore` 和 `app/api/browser.py`。
