#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/work/skj"
RUNNER="${BASE_DIR}/run_static.sh"
LOG_DIR="${BASE_DIR}/静态版本/log/multi"
PID_DIR="${BASE_DIR}/静态版本/log/multi/pids"
POOL_DAEMON="${BASE_DIR}/refresh_eip_pool_daemon.sh"
POOL_DAEMON_PID="${BASE_DIR}/.refresh_eip_pool_daemon.pid"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

declare -a CONFIGS=()

if [[ $# -gt 0 ]]; then
  for cfg in "$@"; do
    if [[ -f "${cfg}" ]]; then
      CONFIGS+=("$(readlink -f "${cfg}")")
    else
      echo "[WARN] skip missing config: ${cfg}"
    fi
  done
else
  while IFS= read -r f; do CONFIGS+=("${f}"); done < <(
    find "${BASE_DIR}" -maxdepth 1 -type f -name 'config*.ini' ! -name 'config.sample.ini' | sort
  )
fi

if [[ ${#CONFIGS[@]} -eq 0 ]]; then
  echo "[ERROR] no config ini found. Pass ini paths explicitly, e.g.:"
  echo "  bash run_static_multi.sh /home/ubuntu/work/skj/config.ini /home/ubuntu/work/skj/config.a.ini"
  exit 1
fi

echo "[INFO] launching ${#CONFIGS[@]} normal-mode workers"
leader_cfg="${CONFIGS[0]}"
for cfg in "${CONFIGS[@]}"; do
  name="$(basename "${cfg}" .ini)"
  log="${LOG_DIR}/${name}.log"
  pidf="${PID_DIR}/${name}.pid"

  export LOOP_MODE="normal"
  export CONFIG_INI="${cfg}"
  if [[ "${cfg}" == "${leader_cfg}" ]]; then
    export ROTATE_ON_LOOP_END="1"
    rotate_role="leader"
  else
    export ROTATE_ON_LOOP_END="0"
    rotate_role="follower"
  fi
  nohup "${RUNNER}" > "${log}" 2>&1 &
  pid=$!
  echo "${pid}" > "${pidf}"
  echo "[OK] ${cfg} -> pid=${pid}, log=${log}, rotate=${rotate_role}"
done

echo "[INFO] done. tail logs with:"
echo "  tail -f ${LOG_DIR}/*.log"

if [[ "${ENABLE_EIP_POOL_REFRESH:-1}" == "1" ]]; then
  if [[ -f "${POOL_DAEMON_PID}" ]] && kill -0 "$(cat "${POOL_DAEMON_PID}")" 2>/dev/null; then
    echo "[INFO] EIP pool refresh daemon already running (pid=$(cat "${POOL_DAEMON_PID}"))"
  else
    nohup "${POOL_DAEMON}" >/dev/null 2>&1 &
    sleep 0.2
    if [[ -f "${POOL_DAEMON_PID}" ]]; then
      echo "[OK] EIP pool refresh daemon started (pid=$(cat "${POOL_DAEMON_PID}"))"
    else
      echo "[WARN] EIP pool refresh daemon start requested, but pid file missing"
    fi
  fi
  echo "[INFO] pool refresh log: ${BASE_DIR}/refresh_eip_pool.log"
fi
