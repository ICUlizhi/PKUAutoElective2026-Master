#!/usr/bin/env python3
"""
Rotate one SNAT rule's EIP on Tencent Cloud NAT Gateway.

Typical usage (dry run):
  python3 rotate_snat.py \
    --region ap-beijing \
    --nat-id nat-xxxxx \
    --snat-id snat-xxxxx \
    --eips eip-a,eip-b,eip-c \
    --dry-run

Real run requires TencentCloud credentials in env:
  TENCENTCLOUD_SECRET_ID
  TENCENTCLOUD_SECRET_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass


@dataclass
class State:
    index: int = -1
    last_eip: str = ""
    updated_at: int = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rotate SNAT EIP on Tencent Cloud NAT")
    p.add_argument("--region", required=True, help="TencentCloud region, e.g. ap-beijing")
    p.add_argument("--nat-id", required=True, help="NAT Gateway ID, e.g. nat-xxxx")
    p.add_argument("--snat-id", default="", help="SNAT rule ID, e.g. snat-xxxx (recommended)")
    p.add_argument(
        "--snat-subnet-id",
        default="",
        help="Optional subnet id used to auto-locate SNAT rule if --snat-id not set",
    )
    p.add_argument(
        "--eips",
        required=True,
        help="Comma-separated EIP IDs or addresses, e.g. eip-1,eip-2,eip-3",
    )
    p.add_argument(
        "--state-file",
        default="/home/ubuntu/work/skj/.rotate_snat_state.json",
        help="State file path",
    )
    p.add_argument(
        "--lock-file",
        default="/home/ubuntu/work/skj/.rotate_snat.lock",
        help="Lock file path",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not call TencentCloud API")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args()


def parse_eips(raw: str) -> list[str]:
    eips = [x.strip() for x in raw.split(",") if x.strip()]
    if len(eips) < 2:
        raise ValueError("Need at least 2 EIPs for rotation")
    return eips


def read_state(path: str) -> State:
    if not os.path.exists(path):
        return State()
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return State(
        index=int(d.get("index", -1)),
        last_eip=str(d.get("last_eip", "")),
        updated_at=int(d.get("updated_at", 0)),
    )


def write_state(path: str, state: State) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "index": state.index,
                "last_eip": state.last_eip,
                "updated_at": state.updated_at,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def next_index(cur: int, total: int) -> int:
    return (cur + 1) % total


def find_snat_rule(client, nat_id: str, subnet_id: str, verbose: bool) -> dict:
    # Lazy import model here to keep --dry-run usable without sdk.
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.DescribeNatGatewaySourceIpTranslationNatRulesRequest()
    req.from_json_string(json.dumps({"NatGatewayId": nat_id}))
    resp = client.DescribeNatGatewaySourceIpTranslationNatRules(req)
    data = json.loads(resp.to_json_string())
    rules = data.get("SourceIpTranslationNatRuleSet", [])
    if not rules:
        raise RuntimeError(f"No SNAT rules found for NAT {nat_id}")

    if verbose:
        print(f"[DEBUG] fetched {len(rules)} SNAT rules")

    if not subnet_id:
        if len(rules) == 1:
            rid = rules[0].get("NatGatewaySnatId") or ""
            if rid:
                return rules[0]
        raise RuntimeError(
            "Multiple SNAT rules found; please set --snat-id or --snat-subnet-id"
        )

    for r in rules:
        candidates = {
            str(r.get("SourceIpTranslationSubnetId", "")),
            str(r.get("ResourceId", "")),
            str(r.get("SubnetId", "")),
        }
        if subnet_id in candidates:
            rid = r.get("NatGatewaySnatId") or ""
            if rid:
                return r

    raise RuntimeError(f"Cannot find SNAT rule for subnet {subnet_id}")


def get_client(region: str):
    try:
        from tencentcloud.common import credential  # type: ignore
        from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore
        from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore
        from tencentcloud.vpc.v20170312 import vpc_client  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing TencentCloud SDK. Install with: pip install tencentcloud-sdk-python"
        ) from e

    sid = os.getenv("TENCENTCLOUD_SECRET_ID", "")
    skey = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
    token = os.getenv("TENCENTCLOUD_TOKEN", "")
    if not sid or not skey:
        raise RuntimeError(
            "Missing credentials. Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY"
        )

    cred = credential.Credential(sid, skey, token or None)
    http_profile = HttpProfile(endpoint="vpc.tencentcloudapi.com")
    client_profile = ClientProfile(httpProfile=http_profile)
    return vpc_client.VpcClient(cred, region, client_profile)


def resolve_eip_tokens(client, tokens: list[str], verbose: bool) -> list[str]:
    """
    Accept EIP IDs (eip-xxxx) or raw public IPs, return all as public IP strings.
    """
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    ids = [x for x in tokens if x.startswith("eip-")]
    if not ids:
        return tokens

    req = models.DescribeAddressesRequest()
    req.from_json_string(json.dumps({"AddressIds": ids}))
    resp = client.DescribeAddresses(req)
    data = json.loads(resp.to_json_string())
    addr_set = data.get("AddressSet", [])
    id_to_ip = {}
    for a in addr_set:
        aid = str(a.get("AddressId", ""))
        ip = str(a.get("AddressIp", ""))
        if aid and ip:
            id_to_ip[aid] = ip

    resolved: list[str] = []
    for t in tokens:
        if t.startswith("eip-"):
            ip = id_to_ip.get(t, "")
            if not ip:
                raise RuntimeError(f"Cannot resolve EIP id to IP: {t}")
            resolved.append(ip)
        else:
            resolved.append(t)

    if verbose:
        pairs = [f"{k}->{id_to_ip.get(k, '?')}" for k in ids]
        print(f"[DEBUG] resolved EIPs: {', '.join(pairs)}")
    return resolved


def modify_snat_eip(
    client,
    nat_id: str,
    snat_id: str,
    eip: str,
    resource_id: str = "",
    resource_type: str = "",
    private_ip: str = "",
) -> None:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.ModifyNatGatewaySourceIpTranslationNatRuleRequest()
    req.NatGatewayId = nat_id

    rule = models.SourceIpTranslationNatRule()
    rule.NatGatewaySnatId = snat_id
    rule.PublicIpAddresses = [eip]
    # Some API versions expect NatGatewayId both at top-level and in rule body.
    rule.NatGatewayId = nat_id
    if resource_id:
        rule.ResourceId = resource_id
    if resource_type:
        rule.ResourceType = resource_type
    if private_ip:
        rule.PrivateIpAddress = private_ip
    req.SourceIpTranslationNatRule = rule

    client.ModifyNatGatewaySourceIpTranslationNatRule(req)


def main() -> int:
    args = parse_args()
    eips = parse_eips(args.eips)

    # Best effort lock to avoid overlapping timer/cron runs.
    try:
        import fcntl

        lock_fp = open(args.lock_file, "w", encoding="utf-8")
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("[ERROR] Another rotate task seems running, skip this round.")
        return 2

    state = read_state(args.state_file)
    nxt = next_index(state.index, len(eips))
    target_eip = eips[nxt]

    snat_id = args.snat_id
    snat_rule = None
    if args.dry_run:
        print(
            f"[DRY-RUN] region={args.region} nat={args.nat_id} snat={snat_id or '<auto>'} "
            f"next_index={nxt} target_eip={target_eip}"
        )
        state.index = nxt
        state.last_eip = target_eip
        state.updated_at = int(time.time())
        write_state(args.state_file, state)
        return 0

    client = get_client(args.region)
    if not snat_id:
        snat_rule = find_snat_rule(client, args.nat_id, args.snat_subnet_id, args.verbose)
        snat_id = snat_rule.get("NatGatewaySnatId", "")
        if not snat_id:
            raise RuntimeError("Found SNAT rule but missing NatGatewaySnatId")

    eips_runtime = eips
    if not args.dry_run:
        eips_runtime = resolve_eip_tokens(client, eips, args.verbose)
        target_eip = eips_runtime[nxt]

    if args.verbose:
        print(
            f"[INFO] rotating nat={args.nat_id}, snat={snat_id}, "
            f"index {state.index} -> {nxt}, eip={target_eip}"
        )

    resource_id = ""
    resource_type = ""
    private_ip = ""
    if snat_rule:
        resource_id = str(snat_rule.get("ResourceId", "") or "")
        resource_type = str(snat_rule.get("ResourceType", "") or "")
        private_ip = str(snat_rule.get("PrivateIpAddress", "") or "")

    modify_snat_eip(
        client,
        args.nat_id,
        snat_id,
        target_eip,
        resource_id=resource_id,
        resource_type=resource_type,
        private_ip=private_ip,
    )

    state.index = nxt
    state.last_eip = target_eip
    state.updated_at = int(time.time())
    write_state(args.state_file, state)
    print(f"[OK] SNAT rotated to {target_eip}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"[ERROR] {e}")
        raise SystemExit(1)
