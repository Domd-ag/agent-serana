# skills_store 目录说明

这里是 Serana 后端的本地 Skill 文件仓库。

## 目录结构

```text
skills_store/
+-- README.md
+-- browser/     项目内置浏览器基础工具
+-- installed/   已完成标准化并安装的 managed skills
+-- .staging/    等待审批的本地 ZIP 导入暂存
```

## 安装规则

- SkillHub 下载包先经过 `SkillStandardizer`，再进入 `installed/`。
- 有效的标准 Python 或 Script Skill 保留其运行时声明。
- 安全、唯一入口的 `.sh` 包会自动转换为 `runtime=script` 和 `adapter=shell`。
- 没有可执行入口的包保持 `runtime=instruction`。
- 危险、不明确或运行环境不兼容的包会拒绝安装，不会留在 `installed/`。
- 安装成功后，`SkillManager` 会立即注册工具，不需要重启或为领域单独写适配代码。
- 更新或覆盖安装使用备份替换；新版本注册失败时会恢复上一版本。

## 运行产物

本地开发时，`browser/previews/` 保存 HTML 演示缓存，属于本地运行产物并由 `.gitignore` 忽略。
Linux 部署时，`SERANA_BROWSER_DATA_DIR` 默认指向 `/var/lib/serana/browser`，预览、下载和截图会写到持久目录，升级源码不会删除。
HTML 预览缓存只在已经生成过有效页面时复用；空缓存探测不能写入空白页面或缓存索引。

## 维护约定

- 删除、移动或重命名目录时同步更新本 README。
- 新增 Runtime adapter 时同步更新 `backend/app/skills/README.md` 和 `docs/SKILL_RUNTIME_SPEC.md`。
- `browser` 是基础能力，不属于 SkillHub 市场安装项。
