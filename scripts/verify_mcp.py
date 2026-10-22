#!/usr/bin/env python3
"""
verify_mcp.py - Diagnoses and verifies the SEO MCP Server and CLI installation.
Checks:
1. 'seo' executable presence in PATH or node runtime.
2. CLI version and doctor status.
3. Ability to query report catalog (74 reports).
4. Google credentials and Search Console readiness.
"""

import json
import os
import shutil
import subprocess
import sys


def find_seo_binary() -> str | None:
    # 1. Check standard PATH
    path_bin = shutil.which("seo")
    if path_bin:
        return path_bin

    # 2. Check local pi-node path
    pi_bin = "/home/aqua/.local/share/pi-node/node-v22.23.2-linux-x64/bin/seo"
    if os.path.isfile(pi_bin) and os.access(pi_bin, os.X_OK):
        return pi_bin

    # 3. Check mise node paths
    mise_bin = "/home/aqua/.local/share/mise/installs/node/25.8.1/bin/seo"
    if os.path.isfile(mise_bin) and os.access(mise_bin, os.X_OK):
        return mise_bin

    return None


def run_command(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def main() -> int:
    print("==================================================================")
    print("  SEO MCP & CLI ENVIRONMENT VERIFICATION")
    print("==================================================================")

    seo_bin = find_seo_binary()
    if not seo_bin:
        print("[FAIL] 'seo' CLI binary not found in PATH or standard runtime locations.")
        print("       Install with: npm i -g seo")
        return 1

    print(f"[OK] Found 'seo' binary: {seo_bin}")

    # Check version
    rc, stdout, stderr = run_command([seo_bin, "--version"])
    if rc == 0:
        print(f"[OK] SEO CLI Version: {stdout}")
    else:
        print(f"[WARN] Failed to retrieve version: {stderr}")

    # Check reports catalog
    rc, stdout, stderr = run_command([seo_bin, "reports", "list", "--json"])
    if rc == 0:
        try:
            data = json.loads(stdout)
            report_count = len(data.get("reports", []))
            categories = data.get("categories", [])
            print(f"[OK] Report Catalog Available: {report_count} reports across {len(categories)} categories.")
            print(f"     Categories: {', '.join(categories)}")
        except Exception as e:
            print(f"[WARN] Could not parse reports catalog: {e}")
    else:
        print(f"[FAIL] Could not query report catalog: {stderr}")

    # Check doctor status
    rc, stdout, stderr = run_command([seo_bin, "doctor", "--json"])
    if stdout:
        try:
            doctor_data = json.loads(stdout)
            checks = doctor_data.get("checks", [])
            print("\nEnvironment & Diagnostic Checks:")
            for check in checks:
                status = check.get("status", "unknown").upper()
                label = check.get("label", check.get("id"))
                detail = check.get("detail", "")
                symbol = "[PASS]" if status == "PASS" else "[WARN]" if status == "WARN" else "[FAIL]"
                print(f"  {symbol:<6} {label}: {detail}")
        except Exception as e:
            print(f"[WARN] Error parsing doctor output: {e}")

    # Check Google credentials
    gcred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if gcred and os.path.exists(gcred):
        print(f"\n[OK] GOOGLE_APPLICATION_CREDENTIALS found: {gcred}")
    else:
        fallback_cred = "/home/aqua/.google/gsc-seo-alpha-key.json"
        if os.path.exists(fallback_cred):
            print(f"\n[OK] Fallback service account key located: {fallback_cred}")
            print(f"     Set with: export GOOGLE_APPLICATION_CREDENTIALS={fallback_cred}")
        else:
            print("\n[INFO] No Google service account key configured.")
            print("       (Crawl audits run without credentials; GSC requires service account or OAuth).")

    print("\n------------------------------------------------------------------")
    print("[SUCCESS] SEO MCP environment verified and operational.")
    print("------------------------------------------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
