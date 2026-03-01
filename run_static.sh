#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/work/skj/静态版本

# Ensure outbound traffic uses NAT, not local proxy.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export ROTATE_SNAT_STATE_FILE="${ROTATE_SNAT_STATE_FILE:-/home/ubuntu/work/skj/.rotate_snat_state.prod.json}"
export ROTATE_ON_LOOP_END="${ROTATE_ON_LOOP_END:-1}"
export ROTATE_SNAT_SCRIPT="${ROTATE_SNAT_SCRIPT:-/home/ubuntu/work/skj/rotate_snat_cron.sh}"
export ROTATE_MIN_INTERVAL_SECONDS="${ROTATE_MIN_INTERVAL_SECONDS:-300}"
export LOOP_MODE="${LOOP_MODE:-normal}"
export CONFIG_INI="${CONFIG_INI:-/home/ubuntu/work/skj/config.ini}"

if [[ ! -f "${CONFIG_INI}" ]]; then
  echo "[ERROR] CONFIG_INI not found: ${CONFIG_INI}" >&2
  exit 1
fi

source /home/ubuntu/work/skj/.venv-static/bin/activate
exec python main.py -c "${CONFIG_INI}"
