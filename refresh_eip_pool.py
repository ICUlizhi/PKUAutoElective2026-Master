#!/usr/bin/env python3
"""
Refresh one NAT's EIP pool in-place:
1) create N fresh EIPs
2) bind them to NAT
3) switch SNAT rule to first fresh EIP
4) update rotate_snat.env EIPS list
5) release old EIPs
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from typing import List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh NAT EIP pool")
    p.add_argument("--region", required=True)
    p.add_argument("--nat-id", required=True)
    p.add_argument("--snat-subnet-id", required=True)
    p.add_argument("--old-eips", required=True, help="comma-separated old eip ids")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--rotate-env-file", required=True)
    p.add_argument("--state-file", required=True)
    p.add_argument("--lock-file", default="/home/ubuntu/work/skj/.rotate_snat.lock")
    p.add_argument("--internet-max-bandwidth-out", type=int, default=50)
    p.add_argument(
        "--internet-charge-type",
        default="TRAFFIC_POSTPAID_BY_HOUR",
        help="TencentCloud InternetChargeType",
    )
    p.add_argument("--line-type", default="BGP")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def get_client(region: str):
    from tencentcloud.common import credential  # type: ignore
    from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore
    from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore
    from tencentcloud.vpc.v20170312 import vpc_client  # type: ignore

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


def _j(resp) -> dict:
    return json.loads(resp.to_json_string())


def _parse_csv(v: str) -> List[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def find_snat_rule(client, nat_id: str, subnet_id: str) -> dict:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.DescribeNatGatewaySourceIpTranslationNatRulesRequest()
    req.from_json_string(json.dumps({"NatGatewayId": nat_id}))
    data = _j(client.DescribeNatGatewaySourceIpTranslationNatRules(req))
    rules = data.get("SourceIpTranslationNatRuleSet", [])
    for r in rules:
        candidates = {
            str(r.get("SourceIpTranslationSubnetId", "")),
            str(r.get("ResourceId", "")),
            str(r.get("SubnetId", "")),
        }
        if subnet_id in candidates and r.get("NatGatewaySnatId"):
            return r
    raise RuntimeError(f"Cannot find SNAT rule for subnet {subnet_id}")


def create_eips(client, count: int, charge_type: str, bandwidth: int, line_type: str) -> List[str]:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.AllocateAddressesRequest()
    req.from_json_string(
        json.dumps(
            {
                "AddressCount": count,
                "AddressChargePrepaid": {"InternetChargeType": charge_type},
                "InternetMaxBandwidthOut": bandwidth,
                "AddressType": "EIP",
                "InternetServiceProvider": line_type,
            }
        )
    )
    data = _j(client.AllocateAddresses(req))
    ids = [str(x) for x in data.get("AddressSet", []) if str(x)]
    if len(ids) != count:
        raise RuntimeError(f"CreateAddresses returned {len(ids)} ids, expected {count}")
    return ids


def describe_addresses(client, ids: List[str]) -> dict:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.DescribeAddressesRequest()
    req.from_json_string(json.dumps({"AddressIds": ids}))
    data = _j(client.DescribeAddresses(req))
    out = {}
    for a in data.get("AddressSet", []):
        aid = str(a.get("AddressId", ""))
        if aid:
            out[aid] = a
    return out


def wait_eips_ready(client, ids: List[str], timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = describe_addresses(client, ids)
        ok = True
        for eid in ids:
            ip = str(info.get(eid, {}).get("AddressIp", ""))
            if not ip:
                ok = False
                break
        if ok:
            return
        time.sleep(2)
    raise RuntimeError("Timeout waiting new EIPs ready")


def associate_nat(client, nat_id: str, eip_ids: List[str]) -> None:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.AssociateNatGatewayAddressRequest()
    req.from_json_string(json.dumps({"NatGatewayId": nat_id, "AddressIds": eip_ids}))
    client.AssociateNatGatewayAddress(req)


def disassociate_nat(client, nat_id: str, eip_ids: List[str]) -> None:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.DisassociateNatGatewayAddressRequest()
    req.from_json_string(json.dumps({"NatGatewayId": nat_id, "AddressIds": eip_ids}))
    client.DisassociateNatGatewayAddress(req)


def release_eips(client, eip_ids: List[str]) -> None:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    req = models.ReleaseAddressesRequest()
    req.from_json_string(json.dumps({"AddressIds": eip_ids}))
    client.ReleaseAddresses(req)


def set_snat_public_ip(client, nat_id: str, snat_rule: dict, public_ip: str) -> None:
    from tencentcloud.vpc.v20170312 import models  # type: ignore

    snat_id = str(snat_rule.get("NatGatewaySnatId", ""))
    if not snat_id:
        raise RuntimeError("SNAT rule missing NatGatewaySnatId")

    req = models.ModifyNatGatewaySourceIpTranslationNatRuleRequest()
    req.NatGatewayId = nat_id

    rule = models.SourceIpTranslationNatRule()
    rule.NatGatewaySnatId = snat_id
    rule.PublicIpAddresses = [public_ip]
    rule.NatGatewayId = nat_id

    resource_id = str(snat_rule.get("ResourceId", "") or "")
    resource_type = str(snat_rule.get("ResourceType", "") or "")
    private_ip = str(snat_rule.get("PrivateIpAddress", "") or "")
    if resource_id:
        rule.ResourceId = resource_id
    if resource_type:
        rule.ResourceType = resource_type
    if private_ip:
        rule.PrivateIpAddress = private_ip

    req.SourceIpTranslationNatRule = rule
    client.ModifyNatGatewaySourceIpTranslationNatRule(req)


def update_env_eips(path: str, eip_ids: List[str]) -> None:
    target = "EIPS=" + ",".join(eip_ids)
    lines = []
    found = False
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("EIPS="):
                    lines.append(target + "\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(target + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def write_state(path: str, new_ip: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"index": 0, "last_eip": new_ip, "updated_at": int(time.time())}, f, indent=2)


def main() -> int:
    args = parse_args()
    old_ids = _parse_csv(args.old_eips)
    if not old_ids:
        raise RuntimeError("old-eips is empty")

    lock_fp = open(args.lock_file, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("[ERROR] Another rotate task seems running, skip this round.")
        return 2

    if args.dry_run:
        print("[DRY-RUN] old_ids=%s count=%s nat=%s region=%s" % (",".join(old_ids), args.count, args.nat_id, args.region))
        return 0

    client = get_client(args.region)
    snat_rule = find_snat_rule(client, args.nat_id, args.snat_subnet_id)

    print("[INFO] creating %d fresh EIPs" % args.count)
    new_ids = create_eips(
        client,
        count=args.count,
        charge_type=args.internet_charge_type,
        bandwidth=args.internet_max_bandwidth_out,
        line_type=args.line_type,
    )
    print("[INFO] created ids: %s" % ",".join(new_ids))

    try:
        wait_eips_ready(client, new_ids, timeout=180)
        info = describe_addresses(client, new_ids)
        new_ips = [str(info[e].get("AddressIp", "")) for e in new_ids]
        if any(not x for x in new_ips):
            raise RuntimeError("Failed to resolve all new EIP addresses")

        print("[INFO] associating fresh EIPs to NAT")
        associate_nat(client, args.nat_id, new_ids)
        time.sleep(2)

        print("[INFO] switching SNAT to %s" % new_ips[0])
        set_snat_public_ip(client, args.nat_id, snat_rule, new_ips[0])

        update_env_eips(args.rotate_env_file, new_ids)
        write_state(args.state_file, new_ips[0])
        print("[INFO] updated %s and rotate state" % args.rotate_env_file)

        print("[INFO] disassociating old EIPs from NAT")
        try:
            disassociate_nat(client, args.nat_id, old_ids)
        except Exception as e:
            print("[WARNING] disassociate old EIPs failed: %s" % e)

        print("[INFO] releasing old EIPs")
        try:
            release_eips(client, old_ids)
        except Exception as e:
            print("[WARNING] release old EIPs failed: %s" % e)

        print("[OK] refreshed EIP pool to %s" % ",".join(new_ids))
        return 0
    except Exception:
        # Rollback: release the freshly created EIPs.
        try:
            disassociate_nat(client, args.nat_id, new_ids)
        except Exception:
            pass
        try:
            release_eips(client, new_ids)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("[ERROR] %s" % e)
        raise SystemExit(1)
