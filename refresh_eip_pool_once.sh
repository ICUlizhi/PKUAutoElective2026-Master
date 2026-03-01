#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/work/skj"
ENV_FILE="${BASE_DIR}/rotate_snat.env"
CRED_FILE="${BASE_DIR}/.tencentcloud_env"

# shellcheck disable=SC1090
[[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}"
# shellcheck disable=SC1090
[[ -f "${CRED_FILE}" ]] && source "${CRED_FILE}"

export PYTHONPATH="/home/ubuntu/work/pydeps:${PYTHONPATH:-}"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

REGION="${REGION:-ap-beijing}"
NAT_ID="${NAT_ID:-nat-4nh66qpd}"
SUBNET_ID="${SUBNET_ID:-subnet-iet24bf7}"
EIPS="${EIPS:-}"
STATE_FILE="${ROTATE_SNAT_STATE_FILE:-${BASE_DIR}/.rotate_snat_state.prod.json}"
ROTATE_ENV_FILE="${ENV_FILE}"

EIP_REFRESH_COUNT="${EIP_REFRESH_COUNT:-10}"
EIP_REFRESH_BW="${EIP_REFRESH_BW:-50}"
EIP_REFRESH_CHARGE_TYPE="${EIP_REFRESH_CHARGE_TYPE:-TRAFFIC_POSTPAID_BY_HOUR}"
EIP_REFRESH_LINE_TYPE="${EIP_REFRESH_LINE_TYPE:-BGP}"
EIP_POOL_REFRESH_DRY_RUN="${EIP_POOL_REFRESH_DRY_RUN:-0}"

if [[ -z "${EIPS}" ]]; then
  echo "[ERROR] EIPS is empty in ${ENV_FILE}" >&2
  exit 1
fi

python3 "${BASE_DIR}/refresh_eip_pool.py" \
  --region "${REGION}" \
  --nat-id "${NAT_ID}" \
  --snat-subnet-id "${SUBNET_ID}" \
  --old-eips "${EIPS}" \
  --count "${EIP_REFRESH_COUNT}" \
  --internet-max-bandwidth-out "${EIP_REFRESH_BW}" \
  --internet-charge-type "${EIP_REFRESH_CHARGE_TYPE}" \
  --line-type "${EIP_REFRESH_LINE_TYPE}" \
  --rotate-env-file "${ROTATE_ENV_FILE}" \
  --state-file "${STATE_FILE}" \
  $([[ "${EIP_POOL_REFRESH_DRY_RUN}" == "1" ]] && echo "--dry-run")
