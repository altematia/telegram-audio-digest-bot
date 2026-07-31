#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/telegram-audio-digest-bot"
DATA_DIR="/var/lib/telegram-audio-digest-bot"
SERVICE_NAME="telegram-audio-digest-bot.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

if [[ ! -f /etc/telegram-audio-digest-bot.env ]]; then
  echo "Missing /etc/telegram-audio-digest-bot.env" >&2
  exit 1
fi

database_path="$(sed -n 's/^DATABASE_PATH=//p' /etc/telegram-audio-digest-bot.env | tail -n 1)"
if [[ "${database_path}" != /* ]]; then
  echo "DATABASE_PATH in the production env must be absolute" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg git python3-venv

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' || {
  echo "Python 3.12 or newer is required" >&2
  exit 1
}

if ! id telegrambot >/dev/null 2>&1; then
  useradd --system --home-dir "${DATA_DIR}" --shell /usr/sbin/nologin telegrambot
fi

install -d -m 0750 -o telegrambot -g telegrambot "${DATA_DIR}"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

install -m 0644 "${APP_DIR}/deploy/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
install -m 0755 "${APP_DIR}/deploy/deploy-key-command" "/usr/local/sbin/deploy-telegram-audio-digest-bot"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
