#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/work/skj"
ENV_FILE="${BASE_DIR}/rotate_snat.env"
CRED_FILE="${BASE_DIR}/.tencentcloud_env"

# shellcheck disable=SC1090
if [[ -f "${ENV_FILE}" ]]; then
  source "${ENV_FILE}"
fi

# shellcheck disable=SC1090
if [[ -f "${CRED_FILE}" ]]; then
  source "${CRED_FILE}"
fi

export PYTHONPATH="/home/ubuntu/work/pydeps:${PYTHONPATH:-}"
export ROTATE_SNAT_STATE_FILE="${ROTATE_SNAT_STATE_FILE:-${BASE_DIR}/.rotate_snat_state.prod.json}"

# Avoid local proxy hijacking egress checks / requests.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

REGION="${REGION:-ap-beijing}"
NAT_ID="${NAT_ID:-nat-4nh66qpd}"
SUBNET_ID="${SUBNET_ID:-subnet-iet24bf7}"
EIPS="${EIPS:-eip-0z0dmwg1,eip-9att7vz7,eip-87cogwwb,eip-j6ja6gdd,eip-fyu4nkbl,eip-qy6cy3in,eip-nbikfzal,eip-rea8xbxn,eip-5cj76s01,eip-pj3valkd}"

if [[ -z "${TENCENTCLOUD_SECRET_ID:-}" || -z "${TENCENTCLOUD_SECRET_KEY:-}" ]]; then
  echo "[ERROR] Missing credentials. Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY" >&2
  exit 1
fi

python3 "${BASE_DIR}/rotate_snat.py" \
  --region "${REGION}" \
  --nat-id "${NAT_ID}" \
  --snat-subnet-id "${SUBNET_ID}" \
  --eips "${EIPS}" \
  --state-file "${ROTATE_SNAT_STATE_FILE}" \
  --verbose
