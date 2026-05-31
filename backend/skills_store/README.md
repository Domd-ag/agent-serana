# skills_store 目录说明

这里是后端技能文件仓库，按来源分成三层：

```text
skills_store/
+-- browser/            项目内置 bundled skill
+-- calculator/         项目内置 bundled skill
+-- data_operations/    项目内置 bundled skill
+-- memory_manager/     项目内置 bundled skill
+-- note_manager/       项目内置 bundled skill
+-- time_manager/       项目内置 bundled skill
+-- weather/            项目内置 bundled skill
+-- installed/          运行时安装的 managed skills，可卸载
+-- .staging/           等待审批的本地 ZIP 导入暂存目录
```

## 约定

- 根目录下现有技能视为 bundled skills，由项目代码直接维护
- `installed/` 只放运行时安装的技能，前端允许对它们执行卸载
- `.staging/` 只做审批前暂存，不参与正常扫描
- 新增 bundled skill 时，在根目录直接建子目录，并补对应 `README.md`
- 不要把运行时产物提交到仓库；相关目录应由 `.gitignore` 忽略
