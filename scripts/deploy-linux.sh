#!/usr/bin/env bash
set -Eeuo pipefail

BRANCH="${SERANA_BRANCH:-main}"
ARCHIVE_URL="${SERANA_ARCHIVE_URL:-https://codeload.github.com/Domd-ag/agent-serana/tar.gz/refs/heads/$BRANCH}"
APP_DIR="${SERANA_APP_DIR:-/opt/serana}"
DATA_DIR="${SERANA_DATA_DIR:-/var/lib/serana}"
VENV_DIR="${SERANA_VENV_DIR:-$DATA_DIR/venv}"
ENV_DIR="${SERANA_ENV_DIR:-/etc/serana}"
SERVICE_USER="${SERANA_SERVICE_USER:-serana}"
SERVICE_NAME="${SERANA_SERVICE_NAME:-serana-backend}"
HOST="${SERANA_HOST:-0.0.0.0}"
PORT="${SERANA_PORT:-8000}"
PYTHON_BIN="${SERANA_PYTHON_BIN:-python3}"

log() {
  printf '[serana-deploy] %s\n' "$*"
}

run_as_service_user() {
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- "$@"
    return
  fi

  if command -v su >/dev/null 2>&1; then
    su -s /bin/sh "$SERVICE_USER" -c "$(printf '%q ' "$@")"
    return
  fi

  log "Neither runuser nor su is available."
  exit 1
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    printf 'Please run as root, for example:\n'
    printf '  curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh | sudo bash\n'
    exit 1
  fi
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing system packages with apt"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y curl ca-certificates tar python3 python3-venv python3-pip
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    log "Installing system packages with dnf"
    dnf install -y curl ca-certificates tar python3 python3-pip
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    log "Installing system packages with yum"
    yum install -y curl ca-certificates tar python3 python3-pip
    return
  fi

  log "No supported package manager found. Please install curl, ca-certificates, tar, python3, python3-venv and python3-pip first."
  exit 1
}

ensure_user() {
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    return
  fi

  log "Creating service user: $SERVICE_USER"
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
}

sync_source() {
  local archive_path extract_dir
  log "Downloading Serana source archive: $ARCHIVE_URL"
  archive_path="$(mktemp /tmp/serana-src.XXXXXX.tar.gz)"
  extract_dir="$(mktemp -d /tmp/serana-src.XXXXXX)"

  curl -fL --connect-timeout 15 --retry 3 --retry-delay 2 -o "$archive_path" "$ARCHIVE_URL"
  tar -xzf "$archive_path" -C "$extract_dir" --strip-components=1

  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"
  cp -a "$extract_dir/." "$APP_DIR/"
  rm -rf "$archive_path" "$extract_dir"

  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
}

write_env_file() {
  mkdir -p "$ENV_DIR" "$DATA_DIR"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
  chmod 750 "$DATA_DIR"

  local env_file="$ENV_DIR/serana.env"
  if [ ! -f "$env_file" ]; then
    log "Creating $env_file"
    local secret_key encryption_key
    secret_key="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    encryption_key="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32)[:32])')"
    cat > "$env_file" <<EOF
APP_NAME=Serana Backend
APP_VERSION=0.1.0
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
SQL_ECHO=false
CORS_ALLOW_ORIGINS=*

DATABASE_URL=sqlite+aiosqlite:///$DATA_DIR/serana.db

SECRET_KEY=$secret_key
ENCRYPTION_KEY=$encryption_key
ALGORITHM=HS256

HOST=$HOST
PORT=$PORT

SKILLHUB_BASE_URL=https://api.skillhub.cn
SKILLHUB_PUBLIC_BASE_URL=https://skillhub.cn
EOF
    chmod 640 "$env_file"
    chown root:"$SERVICE_USER" "$env_file"
  else
    log "Keeping existing $env_file"
  fi
}

install_python_deps() {
  local backend_dir="$APP_DIR/backend"
  log "Creating Python virtual environment"
  mkdir -p "$(dirname "$VENV_DIR")"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$(dirname "$VENV_DIR")"
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    rm -rf "$VENV_DIR"
    run_as_service_user "$PYTHON_BIN" -m venv "$VENV_DIR"
  else
    log "Keeping existing Python virtual environment: $VENV_DIR"
  fi

  run_as_service_user "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
  run_as_service_user "$VENV_DIR/bin/pip" install -r "$backend_dir/requirements.txt"

  if [ "${SERANA_INSTALL_PLAYWRIGHT:-true}" = "true" ]; then
    log "Installing Playwright Chromium runtime"
    "$VENV_DIR/bin/python" -m playwright install --with-deps chromium
  fi
}

write_systemd_service() {
  local service_path="/etc/systemd/system/$SERVICE_NAME.service"
  log "Writing systemd service: $service_path"
  cat > "$service_path" <<EOF
[Unit]
Description=Serana Backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$ENV_DIR/serana.env
ExecStart=$VENV_DIR/bin/python -m uvicorn app.main:app --host $HOST --port $PORT --no-use-colors
Restart=no
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
}

write_management_menu() {
  local menu_path="/root/serana-menu.sh"
  local command_path="/usr/local/bin/serana"
  log "Writing Serana management menu: $menu_path"
  cat > "$menu_path" <<EOF
#!/usr/bin/env bash
set -u

SERVICE_NAME="$SERVICE_NAME"
APP_DIR="$APP_DIR"
PORT="$PORT"
PYTHON_BIN="$PYTHON_BIN"
VENV_DIR="$VENV_DIR"

pause() {
  printf '\n按回车返回菜单...'
  read -r _
}

show_status() {
  printf '\n---- 服务状态 ----\n'
  systemctl status "\$SERVICE_NAME" --no-pager || true
}

run_action() {
  local title="\$1"
  shift
  printf '\n---- %s ----\n' "\$title"
  "\$@" || true
  show_status
  printf '\n如需查看实时日志，请回到菜单选择 4。\n'
}

show_menu() {
  clear 2>/dev/null || true
  cat <<MENU
Serana 管理面板
================
1. 启动 Serana
2. 关闭 Serana
3. 查看状态
4. 查看实时日志
5. 重启 Serana
6. 健康检查
7. 重新部署/更新
0. 退出

MENU
}

while true; do
  show_menu
  printf '请选择操作: '
  read -r choice
  case "\$choice" in
    1)
      run_action "启动 Serana" systemctl start "\$SERVICE_NAME"
      pause
      ;;
    2)
      run_action "关闭 Serana" systemctl stop "\$SERVICE_NAME"
      pause
      ;;
    3)
      show_status
      pause
      ;;
    4)
      journalctl -u "\$SERVICE_NAME" -f
      ;;
    5)
      run_action "重启 Serana" systemctl restart "\$SERVICE_NAME"
      pause
      ;;
    6)
      printf '\n---- 健康检查 ----\n'
      curl -f "http://127.0.0.1:\$PORT/health" || true
      printf '\n'
      pause
      ;;
    7)
      printf '\n---- 重新部署/更新 ----\n'
      curl -fsSL https://raw.githubusercontent.com/Domd-ag/agent-serana/main/scripts/deploy-linux.sh \\
        | SERANA_PYTHON_BIN="\$PYTHON_BIN" SERANA_VENV_DIR="\$VENV_DIR" bash
      show_status
      printf '\n重新部署输出如上。如需查看实时日志，请回到菜单选择 4。\n'
      pause
      ;;
    0)
      exit 0
      ;;
    *)
      printf '无效选项：%s\n' "\$choice"
      pause
      ;;
  esac
done
EOF

  chmod 700 "$menu_path"

  cat > "$command_path" <<EOF
#!/usr/bin/env bash
exec /root/serana-menu.sh "\$@"
EOF
  chmod 755 "$command_path"
}

print_summary() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  log "Deployment complete"
  printf '\n'
  printf 'Service:     %s\n' "$SERVICE_NAME"
  printf 'App dir:     %s\n' "$APP_DIR"
  printf 'Env file:    %s/serana.env\n' "$ENV_DIR"
  printf 'Data dir:    %s\n' "$DATA_DIR"
  printf 'Venv dir:    %s\n' "$VENV_DIR"
  printf 'Health:      http://%s:%s/health\n' "${ip:-SERVER_IP}" "$PORT"
  printf 'API docs:    http://%s:%s/docs\n' "${ip:-SERVER_IP}" "$PORT"
  printf 'Autostart:   disabled\n'
  printf 'Run:         serana, then choose 1 to start\n'
  printf '\n'
  printf 'Useful commands:\n'
  printf '  serana\n'
  printf '  systemctl status %s\n' "$SERVICE_NAME"
  printf '  journalctl -u %s -f\n' "$SERVICE_NAME"
  printf '  systemctl restart %s\n' "$SERVICE_NAME"
}

main() {
  need_root
  cd /
  install_packages
  ensure_user
  sync_source
  write_env_file
  install_python_deps
  write_systemd_service
  write_management_menu
  print_summary
}

main "$@"
