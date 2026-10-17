# Scope templates — how to build a scope file

Templates for the four scope shapes `main.py init` understands, plus the
canonical file the egress gate actually enforces. Which one you start from
depends on your platform:

| Platform | Start from | Feed `--format` | Notes |
|---|---|---|---|
| HackerOne | `hackerone_scope.template.csv` | `hackerone_csv` (auto for `.csv`) | Copy the program-scope CSV columns straight through |
| Bugcrowd | `bugcrowd_scope.template.json` | `bugcrowd_json` (auto for `.json`) | Program's targets table → `targets` |
| YesWeHack | `bugcrowd_scope.template.json` | `bugcrowd_json` | **No API** — manual browser copy (cheatsheet §2) |
| Intigriti | (no template needed) | — | **API path**: `scripts/fetch_intigriti_scope.py <handle>` generates the Bugcrowd-shaped file for you |
| IP ranges / regex in scope | `scope.template.canonical.json` | (post-`init` hand-edit) | Importers only auto-assign exact/wildcard |

## Field mapping (Bugcrowd-shaped feed → `ScopeRule`)

`compliance/scope_importer.py` does this per row of `targets`:

| Feed field | Becomes | Rule |
|---|---|---|
| `name` | `pattern` | starts with `*.` → `match_type: wildcard`, else `exact` |
| `category` | `description` | informational only (shows in `scope.json`) |
| `in_scope: true` | → `in_scope` list | the egress gate **allows** these |
| `in_scope: false` | → `out_of_scope` list | the egress gate **blocks** these (403 + logged) |

HackerOne CSV maps `asset_identifier` → pattern, `asset_type` → description,
`eligible_for_bounty` → the list routing (`true`/`false`, case-insensitive).

Extra keys in the JSON (like the `_comment` block in the templates) are
ignored by the importer.

## Building a file from scratch (step by step)

1. **Copy the right template** next to where you work:
   `cp docs/scope_templates/bugcrowd_scope.template.json scope.json`
2. **Delete the `_comment` block** (optional — it's ignored, but keeps the
   file clean) and replace the example `targets` with the program's real
   scope, one entry per asset.
3. **Transcribe out-of-scope assets too** (`"in_scope": false`). The egress
   gate blocks on them, and a blocked request lands in
   `workspace/<p>/logs/egress_proxy.jsonl` with a reason — that log is your
   proof of discipline.
4. **Run `init`** with the platform tag that matches the program (this sets
   the attribution header, nothing else):

       .venv/bin/python main.py init --platform yeswehack \
           --program <handle> --scope-file scope.json \
           --format bugcrowd_json --researcher <you> --workspace ./workspace

5. **Verify the counts against the program page.** `init` prints
   `in-scope: N / out-of-scope: M` — if they disagree with what the program
   page says, stop and fix the file before trusting anything downstream.
6. **Check on disk:** `workspace/<p>/scope.json` (the enforced rules),
   `headers.txt` (attribution), `platform_profile.json`.
7. **Rehearse** with the dry-run recipe (OPERATIONS §3.2) before the live run.

## When the scope has CIDRs, IP ranges, or regex

The importers only ever assign `exact` or `wildcard`. If the program's scope
includes an IP range or a pattern, the Bugcrowd-shaped feed is the wrong
shape for it (a `/24` would become a single `exact` string the gate can't
range-match). Two options:

- **Post-`init` hand-edit** (usual): after `init`, edit
  `workspace/<p>/scope.json` and change/add rules with `"match_type":
  "cidr"` or `"match_type": "regex"` — see
  `scope.template.canonical.json` for all four match types and the
  `rate_limit_rps` / `max_concurrent` pacing knobs (defaults 10.0 / 5).
- **Canonical file by hand**: build the whole `scope.json` from
  `scope.template.canonical.json`, create `workspace/<p>/{logs,reports,
  evidence}/`, and skip `init` (you'll also be without `headers.txt` /
  `platform_profile.json` — fine unless you need the attribution export).

## The validation ritual (before every live run)

1. `init` counts == program page counts (in AND out of scope).
2. `scope.json` re-read by `main.py run` uses exactly these keys:
   `program_handle`, `platform`, `in_scope[]`, `out_of_scope[]`
   (optional: `rate_limit_rps`, `max_concurrent`) — each rule needs
   `pattern` + `match_type` (`description` optional).
3. Wildcards carry the exact `*.` prefix (a stray space breaks the
   wildcard test).
4. Dry-run first (OPERATIONS §3.2): zero packets, zero cost, report lands.
