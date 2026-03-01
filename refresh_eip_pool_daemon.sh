#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/work/skj"
ONCE_SCRIPT="${BASE_DIR}/refresh_eip_pool_once.sh"
PID_FILE="${BASE_DIR}/.refresh_eip_pool_daemon.pid"
LOCK_FILE="${BASE_DIR}/.refresh_eip_pool_daemon.lock"
LOG_FILE="${BASE_DIR}/refresh_eip_pool.log"

INTERVAL_SECONDS="${EIP_POOL_REFRESH_INTERVAL_SECONDS:-3600}"

if [[ ! -x "${ONCE_SCRIPT}" ]]; then
  echo "[ERROR] ${ONCE_SCRIPT} is not executable" >&2
  exit 1
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[INFO] refresh daemon lock busy, another instance running"
  exit 0
fi

echo $$ > "${PID_FILE}"
trap 'rm -f "${PID_FILE}"' EXIT

echo "[$(date '+%F %T')] daemon start, interval=${INTERVAL_SECONDS}s" >> "${LOG_FILE}"

while true; do
  echo "[$(date '+%F %T')] refresh cycle start" >> "${LOG_FILE}"
  set +e
  "${ONCE_SCRIPT}" >> "${LOG_FILE}" 2>&1
  rc=$?
  set -e
  echo "[$(date '+%F %T')] refresh cycle done, rc=${rc}" >> "${LOG_FILE}"
  sleep "${INTERVAL_SECONDS}"
done
