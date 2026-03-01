#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/work/skj"
POOLS_FILE="${BASE_DIR}/eip_pools.env"
STATE_FILE="${BASE_DIR}/.eip_pool_state"

if [[ ! -f "${POOLS_FILE}" ]]; then
  echo "[ERROR] Missing ${POOLS_FILE}"
  exit 1
fi

# shellcheck disable=SC1090
source "${POOLS_FILE}"

if [[ -z "${POOL_A:-}" || -z "${POOL_B:-}" ]]; then
  echo "[ERROR] POOL_A or POOL_B is empty in ${POOLS_FILE}"
  exit 1
fi

last="A"
if [[ -f "${STATE_FILE}" ]]; then
  last="$(cat "${STATE_FILE}" 2>/dev/null || echo A)"
fi

if [[ "${last}" == "A" ]]; then
  next="B"
  target_pool="${POOL_B}"
else
  next="A"
  target_pool="${POOL_A}"
fi

current_pool="$(grep '^EIPS=' "${BASE_DIR}/rotate_snat.env" | cut -d= -f2- || true)"
echo "[INFO] switch start: last=${last}, next=${next}"
echo "[INFO] current_pool=${current_pool}"

if [[ "${current_pool}" == "${target_pool}" ]]; then
  echo "${next}" > "${STATE_FILE}"
  echo "[INFO] target pool already active, state moved to ${next}"
  exit 0
fi

"${BASE_DIR}/set_eip_pool.sh" "${target_pool}" reset

set +e
"${BASE_DIR}/rotate_snat_cron.sh"
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
  echo "[CRITICAL] hourly pool switch failed on pool ${next}, rolling back"
  "${BASE_DIR}/set_eip_pool.sh" "${current_pool}" reset
  "${BASE_DIR}/rotate_snat_cron.sh" || true
  exit 1
fi

echo "${next}" > "${STATE_FILE}"
echo "[OK] switched pool to ${next}"
