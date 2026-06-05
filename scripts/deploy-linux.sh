#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SERANA_REPO_URL:-https://github.com/Domd-ag/agent-serana.git}"
BRANCH="${SERANA_BRANCH:-main}"
APP_DIR="${SERANA_APP_DIR:-/opt/serana}"
DATA_DIR="${SERANA_DATA_DIR:-/var/lib/serana}"
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
    apt-get install -y git curl ca-certificates python3 python3-venv python3-pip
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    log "Installing system packages with dnf"
    dnf install -y git curl ca-certificates python3 python3-pip
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    log "Installing system packages with yum"
    yum install -y git curl ca-certificates python3 python3-pip
    return
  fi

  log "No supported package manager found. Please install git, curl, python3, python3-venv and python3-pip first."
  exit 1
}

ensure_user() {
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    return
  fi

  log "Creating service user: $SERVICE_USER"
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
}

sync_repo() {
  mkdir -p "$APP_DIR"
  if [ -d "$APP_DIR/.git" ]; then
    log "Updating repository in $APP_DIR"
    git -C "$APP_DIR" fetch --prune origin
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
  else
    log "Cloning $REPO_URL#$BRANCH into $APP_DIR"
    rm -rf "$APP_DIR"
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
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
  run_as_service_user "$PYTHON_BIN" -m venv "$backend_dir/venv"
  run_as_service_user "$backend_dir/venv/bin/python" -m pip install --upgrade pip wheel setuptools
  run_as_service_user "$backend_dir/venv/bin/pip" install -r "$backend_dir/requirements.txt"

  if [ "${SERANA_INSTALL_PLAYWRIGHT:-true}" = "true" ]; then
    log "Installing Playwright Chromium runtime"
    "$backend_dir/venv/bin/python" -m playwright install --with-deps chromium
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
ExecStart=$APP_DIR/backend/venv/bin/python -m uvicorn app.main:app --host $HOST --port $PORT --no-use-colors
Restart=always
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
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
  printf 'Health:      http://%s:%s/health\n' "${ip:-SERVER_IP}" "$PORT"
  printf 'API docs:    http://%s:%s/docs\n' "${ip:-SERVER_IP}" "$PORT"
  printf '\n'
  printf 'Useful commands:\n'
  printf '  systemctl status %s\n' "$SERVICE_NAME"
  printf '  journalctl -u %s -f\n' "$SERVICE_NAME"
  printf '  systemctl restart %s\n' "$SERVICE_NAME"
}

main() {
  need_root
  install_packages
  ensure_user
  sync_repo
  write_env_file
  install_python_deps
  write_systemd_service
  print_summary
}

main "$@"
