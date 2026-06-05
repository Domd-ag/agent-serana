# scripts 目录说明

这里放项目维护和部署脚本。

## 文件职责

- `check-doc-encoding.ps1`
  - Windows 下检查文档编码和潜在乱码。
- `deploy-linux.sh`
  - Linux 一键部署脚本。
  - 从 GitHub 拉取代码，创建 Python 虚拟环境，安装后端依赖，生成 `/etc/serana/serana.env`，写入 systemd 服务并启动 `serana-backend`。

## 维护约定

- 脚本默认保持幂等：重复执行应当更新代码、保留配置和数据、重启服务。
- Linux 脚本优先兼容 Ubuntu / Debian；新增依赖时同步更新 [docs/LINUX_DEPLOYMENT.md](/D:/agent-serana/docs/LINUX_DEPLOYMENT.md)。
- 不要在脚本里写入真实 API Key。LLM 配置统一由 Android App 设置页写入后端。
