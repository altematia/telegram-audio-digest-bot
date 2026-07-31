#!/usr/bin/env bash
set -euo pipefail

SSH_TARGET="${SSH_TARGET:-root@109.172.6.81}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SSH_IDENTITY_FILE="${SSH_IDENTITY_FILE:-${REPO_DIR}/.deploy/server_access_ed25519}"
EXPECTED_REV="$(git -C "${REPO_DIR}" rev-parse HEAD)"

if [[ ! -f "${SSH_IDENTITY_FILE}" ]]; then
  echo "Missing deployment identity: ${SSH_IDENTITY_FILE}" >&2
  exit 1
fi

ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=30 \
  -o ConnectionAttempts=3 \
  -o IdentitiesOnly=yes \
  -o ServerAliveInterval=10 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=yes \
  -i "${SSH_IDENTITY_FILE}" \
  "${SSH_TARGET}" \
  "deploy ${EXPECTED_REV}"
