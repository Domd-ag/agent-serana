# 常用命令入口

这份文档记录容易踩坑的本地命令入口。后续开发时优先使用这里的脚本，减少 PowerShell 路径、编码和引号问题。

## 后端测试

从仓库根目录运行：

```bat
test-backend.bat
```

运行单个测试：

```bat
test-backend.bat test_api_flows.ApiFlowTests.test_lightweight_route_can_create_html_preview
```

这个脚本会自动：

- 切换到 `backend/` 目录。
- 设置 `PYTHONPATH`，避免 `backend/test_api_flows.py` 找不到 `app` 包。
- 设置 `PYTHONUTF8=1`，减少 Windows 终端编码差异。

## PowerShell 引号约定

PowerShell 容易把 `|`、括号、引号和反斜杠误解释掉。以后尽量避免在 PowerShell 里直接拼复杂的 `python -c "..."`。

推荐做法：

- 后端测试统一用 `test-backend.bat`。
- 复杂 Python 探针优先写成临时 `.py` 文件再运行，验证完删除。
- 必须执行单行 Python 时，避免在字符串里混用多层引号、管道和反斜杠。

## 文档编码检查

从仓库根目录运行：

```bat
check-doc-encoding.bat
```

这个脚本会按严格 UTF-8 读取所有 Markdown，并扫描常见 mojibake 特征。它通过时，说明文档文件本身没有写坏；如果终端仍显示乱码，优先检查当前 shell、RTK 输出链路或控制台代码页。

## Android 编译

从 `frontend-android/` 目录运行：

```bat
C:\Users\ASUS\gradle\gradle-8.2\bin\gradle.bat :app:compileDebugKotlin --no-daemon --offline
```

后续如果新增更多固定验证命令，也放到这里，并尽量提供根目录脚本入口。
