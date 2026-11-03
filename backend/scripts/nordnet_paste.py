"""POST a Nordnet transaction-history paste to the running backend.

Usage (from the compose directory on the host):

    python backend/scripts/nordnet_paste.py --input /tmp/paste.txt
    # review the report, then:
    python backend/scripts/nordnet_paste.py --input /tmp/paste.txt --commit

Does a dry-run first (commit=false), prints a per-status breakdown + any
needs_review / error rows, and only writes when invoked with --commit.
Reads API_KEY and BACKEND_URL from .env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path


def _load_env(env_path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _post(url: str, api_key: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _print_report(payload: dict) -> None:
    data = payload.get("data", payload)
    rows = data.get("rows", [])
    summary = data.get("summary", {})
    if summary:
        print(f"summary: {summary}")
    status_counts = Counter(r.get("status", "unknown") for r in rows)
    print(f"\nparsed {len(rows)} records:")
    for status, n in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status:14s} {n}")

    # Per-row preview, grouped by status
    for status in ("committed", "ok", "duplicate", "needs_review", "error", "merged"):
        matching = [r for r in rows if r.get("status") == status]
        if not matching:
            continue
        print(f"\n--- {status} ({len(matching)}) ---")
        for r in matching:
            p = r.get("parsed", {})
            resolution = r.get("resolution", {})
            ticker = resolution.get("securityTicker") or "—"
            dup = r.get("existingTransactionId")
            commit = r.get("committedTransactionId")
            trailer = ""
            if dup:
                trailer = f" (dup of txn {dup})"
            if commit:
                trailer = f" (committed as txn {commit})"
            print(
                f"  {p.get('tradeDate')} {p.get('type'):17s} "
                f"{(p.get('securityName') or '—')[:45]:45s} "
                f"qty={p.get('quantity') or '—':>6} "
                f"total={p.get('total') or '—':>12} {p.get('totalCurrency') or ''} "
                f"→ {ticker}{trailer}"
            )
            for err in r.get("errors") or []:
                print(f"      ERROR: {err}")
            for warn in r.get("warnings") or []:
                print(f"      warn:  {warn}")


def main() -> int:
    parser = argparse.ArgumentParser(description="POST a Nordnet paste to the backend.")
    parser.add_argument("--input", required=True, help="Path to paste text file")
    parser.add_argument("--commit", action="store_true", help="Actually write (default: dry-run)")
    parser.add_argument("--env", default=".env", help="Path to .env (default: ./.env)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="Backend base URL (default: http://127.0.0.1:8000)")
    args = parser.parse_args()

    env = _load_env(Path(args.env))
    api_key = env.get("API_KEY") or os.environ.get("API_KEY", "")
    if not api_key:
        print(f"ERROR: no API_KEY found in {args.env} or env", file=sys.stderr)
        return 1

    paste_text = Path(args.input).read_text(encoding="utf-8")
    url = f"{args.base_url}/api/v1/portfolio/nordnet-paste"
    body = {"text": paste_text, "commit": args.commit}

    label = "COMMIT" if args.commit else "DRY RUN"
    print(f"=== {label} → {url} ===")
    try:
        payload = _post(url, api_key, body)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1

    _print_report(payload)
    print()
    if not args.commit:
        print("Dry run only — re-run with --commit to actually write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
