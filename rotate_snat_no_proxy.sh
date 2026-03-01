#!/usr/bin/env bash
set -euo pipefail

# Run SNAT rotation without proxy env, so only this task bypasses local proxy.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EIPS="eip-0z0dmwg1,eip-9att7vz7,eip-87cogwwb,eip-j6ja6gdd,eip-fyu4nkbl,eip-qy6cy3in,eip-nbikfzal,eip-rea8xbxn,eip-5cj76s01,eip-pj3valkd"
STATE_FILE="${SCRIPT_DIR}/.rotate_snat_state.prod.json"
LOG_FILE="${SCRIPT_DIR}/rotate_snat.log"

export PYTHONPATH="/home/ubuntu/work/pydeps:${PYTHONPATH:-}"

# Optional credential file:
#   export TENCENTCLOUD_SECRET_ID=...
#   export TENCENTCLOUD_SECRET_KEY=...
if [[ -f "${SCRIPT_DIR}/.tencentcloud_env" ]]; then
  # shellcheck disable=SC1090
  source "${SCRIPT_DIR}/.tencentcloud_env"
fi

if [[ -z "${TENCENTCLOUD_SECRET_ID:-}" || -z "${TENCENTCLOUD_SECRET_KEY:-}" ]]; then
  echo "[ERROR] Missing TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY" >> "${LOG_FILE}"
  exit 1
fi

{
  date '+[%F %T] rotate_snat start'
  env \
    -u http_proxy \
    -u https_proxy \
    -u HTTP_PROXY \
    -u HTTPS_PROXY \
    -u all_proxy \
    -u ALL_PROXY \
    python3 "${SCRIPT_DIR}/rotate_snat.py" \
      --region ap-beijing \
      --nat-id nat-4nh66qpd \
      --snat-subnet-id subnet-iet24bf7 \
      --eips "${EIPS}" \
      --state-file "${STATE_FILE}" \
      --verbose
  date '+[%F %T] rotate_snat done'
} >> "${LOG_FILE}" 2>&1
