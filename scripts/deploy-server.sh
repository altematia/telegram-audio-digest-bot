#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/telegram-audio-digest-bot"
SERVICE_NAME="telegram-audio-digest-bot.service"
EXPECTED_REV="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

if [[ ! "${EXPECTED_REV}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Expected a full 40-character Git revision" >&2
  exit 1
fi

cd "${APP_DIR}"
if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Production checkout must be on main" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Production checkout has tracked local changes" >&2
  exit 1
fi
git fetch origin main
if [[ "$(git rev-parse origin/main)" != "${EXPECTED_REV}" ]]; then
  echo "origin/main does not match the requested revision" >&2
  exit 1
fi
git pull --ff-only origin main
if [[ "$(git rev-parse HEAD)" != "${EXPECTED_REV}" ]]; then
  echo "Checked-out revision does not match the requested revision" >&2
  exit 1
fi
"${APP_DIR}/.venv/bin/pip" install -q -r requirements.txt
install -m 0644 "deploy/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
install -m 0755 "deploy/deploy-key-command" "/usr/local/sbin/deploy-telegram-audio-digest-bot"
systemctl daemon-reload
systemctl restart "${SERVICE_NAME}"
sleep 5
systemctl is-active --quiet "${SERVICE_NAME}"
restart_count="$(systemctl show "${SERVICE_NAME}" --property=NRestarts --value)"
sleep 5
systemctl is-active --quiet "${SERVICE_NAME}"
if [[ "$(systemctl show "${SERVICE_NAME}" --property=NRestarts --value)" != "${restart_count}" ]]; then
  echo "Service restarted during the health-check window" >&2
  journalctl --no-pager -n 50 -u "${SERVICE_NAME}"
  exit 1
fi
systemctl --no-pager --full status "${SERVICE_NAME}"
journalctl --no-pager -n 30 -u "${SERVICE_NAME}"
