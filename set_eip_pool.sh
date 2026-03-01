#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/ubuntu/skj_system"
ENV_FILE="${BASE_DIR}/rotate_snat.env"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"eip-1,eip-2,...,eip-10\" [reset]"
  echo "Example:"
  echo "  $0 \"eip-d7zqku07,eip-4vrvy677,eip-hlqd8ezz,eip-b4xz7ex1,eip-lbx5y5pn,eip-fiirelqn,eip-pioqzpnt,eip-2akt52ct,eip-pr281xnp,eip-gyux2bl1\" reset"
  exit 1
fi

NEW_EIPS="$1"
RESET_STATE="${2:-}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

TMP_FILE="$(mktemp)"
awk -v eips="${NEW_EIPS}" '
  BEGIN{updated=0}
  /^EIPS=/ {print "EIPS=" eips; updated=1; next}
  {print}
  END{
    if(updated==0){
      print "EIPS=" eips
    }
  }
' "${ENV_FILE}" > "${TMP_FILE}"
mv "${TMP_FILE}" "${ENV_FILE}"

echo "[OK] Updated EIPS in ${ENV_FILE}"
echo "EIPS=${NEW_EIPS}"

if [[ "${RESET_STATE}" == "reset" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  rm -f "${ROTATE_SNAT_STATE_FILE:-${BASE_DIR}/.rotate_snat_state.prod.json}"
  echo "[OK] Rotation state reset"
fi

echo "Now run:"
echo "  /home/ubuntu/work/skj/rotate_snat_cron.sh"
