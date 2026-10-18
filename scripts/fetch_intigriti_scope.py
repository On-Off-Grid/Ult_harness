#!/usr/bin/env python3
"""Fetch an Intigriti program's scope from the Researcher API and write a
Bugcrowd-shaped scope file for `main.py init --format bugcrowd_json`.

Intigriti is the one platform with an API (no manual browser copy-paste
needed). The Researcher API is BETA — see
https://intigriti-researcher-api.readme.io/reference for the full reference.
Probe-verified 2026-10-17 (read-only):

  GET  https://api.intigriti.com/external/researcher/v1/programs
       -> {maxCount, records: [{id, handle, name, status{value}, type{value},
                                minBounty, maxBounty, confidentialityLevel}] }
  GET  .../v1/programs/{programId}
       -> {id, handle, name, domains: {id, createdAt, content:
            [{type{value}, tier{value}, endpoint, description}]},
           rulesOfEngagement: {content: {description, testingRequirements}}}

Auth: `Authorization: Bearer <INTIGRITI_API_KEY>` (key in gitignored `.env`).
Rate limit: 600 GETs / 5 min (403 Forbidden when exceeded).

Domain type -> match_type mapping (this script's editorial call, per
docs/hunt_cheatsheet.md §2):
  URL / Wildcard / API / Web   -> wildcard if `*.` prefix, else exact
  Subnet / IP                  -> cidr
  Custom / Regex               -> regex
  Mobile (iOS/Android/…)       -> dropped from the scope file (mobile apps
                                   are not egress-able through mitmproxy;
                                   they are listed in the export's comment
                                   block for manual testing)
Tier "No Bounty" (Intigriti's out-of-scope equivalent) -> in_scope: false.

Usage:
  python3 scripts/fetch_intigriti_scope.py list
  python3 scripts/fetch_intigriti_scope.py <handle> -o scope.json
  python3 scripts/fetch_intigriti_scope.py <handle> --search <text>   # find the handle
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover — requests is NOT a control-plane dep
    sys.exit("requests is not installed — run: "
             "pip install requests   (or .venv/bin/pip install requests)")

BASE = "https://api.intigriti.com/external/researcher"


def _load_key() -> str:
    """INTIGRITI_API_KEY from the environment, else from `.env` at repo root."""
    key = os.getenv("INTIGRITI_API_KEY", "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("INTIGRITI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                if key:
                    return key
    sys.exit("INTIGRITI_API_KEY not set (env or .env) — see .env.example")


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _get(key: str, path: str) -> dict:
    r = requests.get(BASE + path, headers=_headers(key), timeout=20)
    if r.status_code == 403:
        sys.exit("403 — either the rate limit (600 GETs/5min) is hit, or the "
                 "program's terms of engagement were changed and must be "
                 "re-accepted in the Intigriti UI first.")
    r.raise_for_status()
    return r.json()


def _match_type(dtype: str, endpoint: str) -> str | None:
    d = (dtype or "").lower()
    if d in ("subnet", "ip", "ip range"):
        return "cidr"
    if d in ("regex", "custom"):
        return "regex"
    if d.startswith("mobile") or d in ("ios", "android", "mobile app", "app"):
        return None  # not egress-able
    if endpoint.startswith("*.") or d in ("wildcard", "url", "web", "api"):
        return "wildcard" if endpoint.startswith("*.") else "exact"
    return "exact"


def _list_all(key: str) -> list:
    """Page through GET /v1/programs (server default page = 50, max 500/page).

    Without this, accounts with >50 programs only ever see the first page —
    the rest are invisible to both `list` and handle resolution.
    """
    records, offset = [], 0
    while True:
        data = _get(key, f"/v1/programs?limit=500&offset={offset}")
        batch = data.get("records", [])
        records.extend(batch)
        if len(records) >= data.get("maxCount", len(records)) or not batch:
            return records
        offset += len(batch)


def cmd_list(key: str, search: str | None, limit: int) -> int:
    records = _list_all(key)
    total = len(records)
    if search:
        s = search.lower()
        records = [p for p in records
                   if s in p.get("handle", "").lower()
                   or s in p.get("name", "").lower()]
    for p in records[:limit]:
        status = (p.get("status") or {}).get("value", "?")
        ptype = (p.get("type") or {}).get("value", "?")
        print(f"{p.get('handle'):<28} {status:<8} {ptype:<14} "
              f"{p.get('name', '')[:50]}  (id={p.get('id')})")
    print(f"\n{min(len(records), limit)} of {total} program(s)"
          + (f" matching {search!r}" if search else ""))
    return 0


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                   re.IGNORECASE)


def _resolve_id(key: str, ident: str) -> str:
    """Accept a program handle or a program GUID; return the GUID."""
    if _UUID.match(ident):
        return ident
    for p in _list_all(key):
        if p.get("handle", "").lower() == ident.lower():
            return p["id"]
    sys.exit(f"program {ident!r} not found — run `list --search {ident}` "
             f"to discover handles")


def fetch_program(key: str, handle: str) -> dict:
    """GET /v1/programs/{id} for a handle or GUID.

    The importable fetch used by `main.py hunt` (the script CLI is unchanged).
    """
    return _get(key, f"/v1/programs/{_resolve_id(key, handle)}")


def build_scope_payload(data: dict, handle: str) -> dict:
    """Map a raw program GET response to the Bugcrowd-shaped scope file.

    Pure function (no I/O) so both the script CLI and `main.py hunt` share
    one mapping — the tier/match_type editorial calls live only here.
    """
    domains = (data.get("domains") or {}).get("content") or []

    targets, mobile = [], []
    for d in domains:
        endpoint = (d.get("endpoint") or "").strip()
        if not endpoint:
            continue
        tier = ((d.get("tier") or {}).get("value") or "")
        in_scope = tier.lower() != "no bounty"
        match = _match_type((d.get("type") or {}).get("value", ""), endpoint)
        if match is None:
            mobile.append(d)
            continue
        targets.append({
            "name": endpoint,
            "category": (d.get("description") or match.upper()).strip(),
            "in_scope": in_scope,
        })

    n_in = sum(1 for t in targets if t["in_scope"])
    n_out = len(targets) - n_in
    payload = {
        "_comment": [
            f"Generated by scripts/fetch_intigriti_scope.py on program "
            f"{handle!r} ({data.get('name', '')}) from the Intigriti "
            f"Researcher API (beta). Domains version: "
            f"{(data.get('domains') or {}).get('id', '?')}",
            f"In-scope: {n_in} / Out-of-scope (No Bounty tier): {n_out} / "
            f"Mobile (dropped, manual-only): {len(mobile)}",
            "Review against the program page before init — the tier mapping "
            "(No Bounty -> out-of-scope) is editorial, not authoritative.",
        ],
        "targets": targets,
    }
    if mobile:
        payload["_mobile_apps_manual_only"] = [
            {"app": (m.get("endpoint") or ""),
             "description": (m.get("description") or "")[:120],
             "in_scope": ((m.get("tier") or {}).get("value") or "")
                          .lower() != "no bounty"}
            for m in mobile
        ]

    return payload


def cmd_fetch(key: str, handle: str, out: str) -> int:
    data = fetch_program(key, handle)
    payload = build_scope_payload(data, handle)

    n_in = sum(1 for t in payload["targets"] if t["in_scope"])
    n_out = len(payload["targets"]) - n_in
    roe = ((data.get("rulesOfEngagement") or {}).get("content") or {})

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"[ok] program        : {handle} — {data.get('name', '')}")
    print(f"[ok] in-scope rules : {n_in}")
    print(f"[ok] out-of-scope   : {n_out} (tier 'No Bounty')")
    print(f"[ok] mobile (skip)  : {len(mobile)} (manual testing only — not "
          f"egress-able)")
    if roe.get("description"):
        print("[ok] RoE present    : yes — read it. The script does not "
              "enforce RoE text; YOU do.")
    print(f"[ok] wrote          : {out}")
    print("\nNext:  .venv/bin/python main.py init --platform intigriti "
          f"--program {handle} --scope-file {out} "
          "--format bugcrowd_json --workspace ./workspace")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("handle", nargs="?", help="program handle (from `list`)")
    ap.add_argument("-o", "--out", default="scope.json",
                    help="output scope file (Bugcrowd-shaped JSON)")
    ap.add_argument("--search", help="filter `list` by handle/name substring")
    ap.add_argument("--limit", type=int, default=40, help="max rows in list")
    args = ap.parse_args()

    key = _load_key()
    if args.handle is None:
        return cmd_list(key, args.search, args.limit)
    if args.handle.lower() == "list":
        return cmd_list(key, args.search, args.limit)
    return cmd_fetch(key, args.handle, args.out)


if __name__ == "__main__":
    sys.exit(main())
