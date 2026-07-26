#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

MINIMUM = (3, 5, 0)
REQUIRED_GROUPS = {"X25519", "MLKEM768", "X25519MLKEM768"}


def command(*args: str) -> str:
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ).stdout


def version_tuple(text: str) -> tuple[int, int, int]:
    match = re.search(r"OpenSSL\s+(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise ValueError(f"Could not parse OpenSSL version from: {text.strip()}")
    return tuple(map(int, match.groups()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openssl", default="/opt/openssl-3.5.7/bin/openssl")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report: dict[str, object] = {"ok": True, "checks": {}}
    checks = report["checks"]
    assert isinstance(checks, dict)

    try:
        version = command(args.openssl, "version", "-a")
        parsed = version_tuple(version)
        checks["openssl_version"] = {"ok": parsed >= MINIMUM, "value": version.splitlines()[0]}
        if parsed < MINIMUM:
            report["ok"] = False

        groups_text = command(args.openssl, "list", "-tls1_3", "-tls-groups")
        available = set(re.findall(r"\b(?:X25519MLKEM768|MLKEM768|X25519)\b", groups_text))
        missing = sorted(REQUIRED_GROUPS - available)
        checks["tls_groups"] = {
            "ok": not missing,
            "required": sorted(REQUIRED_GROUPS),
            "missing": missing,
        }
        if missing:
            report["ok"] = False
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        checks["openssl"] = {"ok": False, "error": str(error)}
        report["ok"] = False

    for utility in ("ip", "tc"):
        try:
            path = command("sh", "-c", f"command -v {utility}").strip()
            checks[utility] = {"ok": bool(path), "path": path}
        except subprocess.CalledProcessError:
            checks[utility] = {"ok": False}
            report["ok"] = False

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for name, result in checks.items():
            assert isinstance(result, dict)
            mark = "PASS" if result.get("ok") else "FAIL"
            print(f"{mark:4} {name}: {json.dumps(result, sort_keys=True)}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

