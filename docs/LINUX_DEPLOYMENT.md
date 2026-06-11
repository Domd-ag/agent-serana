# Linux 一键部署方案

本文档描述 Serana 后端在 Linux 服务器上的推荐部署方式：通过 HTTP 下载 GitHub 源码包，创建 Python 虚拟环境，安装依赖，生成 systemd 服务，并由 Android App 在设置页配置服务器地址与 LLM 配置。

## 目标形态

```text
Android App
    |
    | http://SERVER_IP:8000/api/v1
    v
Serana Backend (systemd: serana-backend)
    |
    +-- /opt/serana              后端代码目录
    +-- /etc/serana/serana.env   运行配置
    +-- /var/lib/serana          SQLite 数据、Skill、浏览器缓存和 Python 虚拟环境
        +-- skills/              SkillHub 安装和本地导入的持久 skill
        +-- browser/             HTML 预览、下载、截图等浏览器运行产物
```

默认只部署后端。Android 客户端仍由 Android Studio 或 APK 安装；首次打开 App 后，在设置里先配置服务器地址，再配置 LLM 的 Base URL、API Key 和模型。

## 推荐系统

- Ubuntu 22.04 / 24.04 LTS
- Debian 12
- Python 3.10+
- systemd

CentOS / Rocky / Fedora 也可以运行脚本，但 Playwright 的系统依赖在 Debian/Ubuntu 上最稳。

## 一键部署

在服务器上执行：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh | sudo bash
```

脚本默认参数：

```text
源码包: https://codeload.github.com/Domd-ag/agent-serana/tar.gz/refs/heads/main
分支: main
代码目录: /opt/serana
配置文件: /etc/serana/serana.env
数据目录: /var/lib/serana
Python 虚拟环境: /var/lib/serana/venv
Skill 持久目录: /var/lib/serana/skills
浏览器产物目录: /var/lib/serana/browser
服务用户: serana
服务名: serana-backend
监听地址: 0.0.0.0:8000
```

部署脚本只安装服务和菜单，不会开机自启，也不会在部署结束后自动启动后端。部署完成后用菜单手动启动：

```bash
serana
```

选择：

```text
1. 启动 Serana
```

然后检查：

```bash
systemctl status serana-backend
curl http://127.0.0.1:8000/health
```

以后 SSH 到服务器后也可以直接输入：

```bash
serana
```

菜单默认提供：

```text
1. 启动 Serana
2. 关闭 Serana
3. 查看状态
4. 查看实时日志
5. 重启 Serana
6. 健康检查
7. 重新部署/更新
0. 退出
```

菜单文件位于 `/root/serana-menu.sh`，命令入口位于 `/usr/local/bin/serana`。后续如果要增加数据库备份、清理缓存、查看配置等操作，可以继续在这个菜单里扩展。

systemd 服务默认 `Restart=no`，并且不会 `enable` 开机自启。如果启动失败，服务会停在失败状态，不会一直重试刷日志。

启动、关闭和重启后，菜单会显示当前服务状态，并提示可以选择 `4` 查看实时日志。健康检查只显示健康检查结果；重新部署会保留部署过程的命令行输出。

查看日志：

```bash
journalctl -u serana-backend -f
```

## 自定义部署参数

可以用环境变量覆盖默认值：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh \
  | sudo SERANA_BRANCH=main SERANA_PORT=8000 bash
```

常用参数：

```text
SERANA_ARCHIVE_URL    源码包下载地址
SERANA_BRANCH         部署分支
SERANA_APP_DIR        代码目录
SERANA_DATA_DIR       数据目录
SERANA_VENV_DIR       Python 虚拟环境目录
SERANA_SKILLS_DIR     SkillHub 安装和本地导入的持久 skill 目录
SERANA_BROWSER_DATA_DIR 浏览器预览、下载和截图目录
SERANA_ENV_DIR        配置目录
SERANA_SERVICE_USER   systemd 运行用户
SERANA_SERVICE_NAME   systemd 服务名
SERANA_HOST           后端监听 host
SERANA_PORT           后端监听端口
SERANA_INSTALL_PLAYWRIGHT=true|false
```

## 配置文件

脚本会生成：

```text
/etc/serana/serana.env
```

示例：

```env
APP_NAME=Serana Backend
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
CORS_ALLOW_ORIGINS=*

DATABASE_URL=sqlite+aiosqlite:////var/lib/serana/serana.db
SERANA_SKILLS_DIR=/var/lib/serana/skills
SERANA_BROWSER_DATA_DIR=/var/lib/serana/browser

SECRET_KEY=...
ENCRYPTION_KEY=...
ALGORITHM=HS256

HOST=0.0.0.0
PORT=8000

SKILLHUB_BASE_URL=https://api.skillhub.cn
SKILLHUB_PUBLIC_BASE_URL=https://skillhub.cn
```

注意：后端不再提供默认 LLM。不要在服务器环境变量里配置默认模型。LLM 配置统一由 Android App 设置页写入 `/api/v1/llm/config`。

修改配置后重启：

```bash
systemctl restart serana-backend
```

## Android App 配置

部署后，在手机 App 的设置页：

1. 进入 `连接服务器`
2. 填写服务器地址：

```text
http://SERVER_IP:8000
```

或者：

```text
http://SERVER_IP:8000/api/v1
```

3. 进入 `LLM 配置`
4. 填写：

```text
Base URL: https://api.deepseek.com 或其他 OpenAI 兼容地址
API Key: 你的 Key
模型: deepseek-chat / openai/gpt-5 / 其他模型 ID
```

## 防火墙

如果直接暴露 8000 端口：

```bash
ufw allow 8000/tcp
```

生产环境更推荐只开放 80/443，用 Nginx 反代到本机 8000。

## 可选 Nginx 反代

安装 Nginx：

```bash
apt-get install -y nginx
```

站点配置示例：

```nginx
server {
    listen 80;
    server_name your-domain.example;

    client_max_body_size 64m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
    }
}
```

启用：

```bash
nginx -t
systemctl reload nginx
```

Android 服务器地址填写：

```text
http://your-domain.example
```

HTTPS 可以后续用 certbot 接入。

## 升级

重新执行一键脚本即可：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh | sudo bash
```

脚本会：

1. 通过 HTTP 下载最新源码包
2. 覆盖 `/opt/serana` 代码目录
3. 复用 `/var/lib/serana/venv` 虚拟环境并更新 Python 依赖
4. 保留 `/etc/serana/serana.env`
5. 保留 `/var/lib/serana/serana.db`
6. 重启 `serana-backend`

如果服务器已经手动安装了 Python 3.11，可以继续指定 Python：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh \
  | SERANA_PYTHON_BIN=/opt/python-3.11/bin/python3.11 bash
```

## 回滚

脚本默认部署 `main` 分支源码包。如果要回滚到某个提交，可以在 GitHub 上找到提交 SHA，然后指定对应源码包地址：

```bash
SERANA_ARCHIVE_URL=https://codeload.github.com/Domd-ag/agent-serana/tar.gz/<commit-sha> \
SERANA_PYTHON_BIN=/opt/python-3.11/bin/python3.11 \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh)"
```

也可以回滚到某个分支：

```bash
curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh \
  | SERANA_BRANCH=main SERANA_PYTHON_BIN=/opt/python-3.11/bin/python3.11 bash
```

## 常见问题

### 部署速度很慢

如果服务器访问 PyPI 或下载 Playwright 依赖很慢，可以临时使用国内 pip 源，并跳过 Playwright 安装。示例：

```bash
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
PIP_TRUSTED_HOST=mirrors.aliyun.com \
PIP_DEFAULT_TIMEOUT=120 \
PIP_RETRIES=5 \
PIP_ONLY_BINARY=:all: \
PIP_PREFER_BINARY=1 \
SERANA_PYTHON_BIN=/opt/miniconda3/envs/serana/bin/python \
SERANA_INSTALL_PLAYWRIGHT=false \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh)"
```

这条命令适合已经准备好 Python/Conda 环境的服务器。`SERANA_PYTHON_BIN` 请按实际 Python 路径调整；跳过 Playwright 后，浏览器能力需要后续单独安装依赖。

### GitHub 下载卡住或 `Encountered end of file`

这通常是服务器到 GitHub 的网络连接中断，不是 Serana 代码本身的问题。部署脚本现在只依赖 HTTP 下载源码包，不要求服务器安装 Git。

如果第一条一键命令没有任何输出，可以先改成分步执行，方便看到卡在哪一步：

```bash
curl -fL --connect-timeout 15 --max-time 60 \
  -o /tmp/deploy-linux.sh \
  https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh

bash -x /tmp/deploy-linux.sh
```

部署脚本会覆盖 `/opt/serana` 代码目录。新版脚本会自动切到 `/` 后再执行覆盖操作；如果手动拆开执行命令，也不要站在 `/opt/serana` 或它的子目录里删除/覆盖代码目录。

如果 `raw.githubusercontent.com` 或 `github.com` 在服务器上都不稳定，需要给服务器配置代理后再执行：

```bash
export https_proxy=http://PROXY_HOST:PROXY_PORT
export http_proxy=http://PROXY_HOST:PROXY_PORT
```

### App 连不上服务器

检查：

```bash
systemctl status serana-backend
curl http://127.0.0.1:8000/health
curl http://SERVER_IP:8000/health
```

如果本机通、外网不通，多半是安全组或防火墙没开放端口。

### 聊天提示需要配置 LLM

这是预期行为。后端不再内置默认模型。到 App 设置页保存 LLM 配置即可。

### 浏览器功能不可用

确认 Playwright 已安装：

```bash
/var/lib/serana/venv/bin/python -m playwright install --with-deps chromium
systemctl restart serana-backend
```

### 查看后端错误日志

```bash
journalctl -u serana-backend -n 200 --no-pager
```
