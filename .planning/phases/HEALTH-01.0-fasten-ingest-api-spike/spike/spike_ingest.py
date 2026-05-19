#!/usr/bin/env python3
"""
spike_ingest.py — Phase 1.0 Fasten ingest-API spike harness (THROWAWAY/reference).

Empirically confirms the now-known Fasten OnPrem programmatic FHIR Bundle ingest
contract (RESEARCH.md Patterns 1+2). The durable deliverable is docs/fasten-admin.md;
this script is throwaway.

Flow (RESEARCH.md Architecture Patterns 1+2):
  A. POST /api/auth/signin                -> 1h session JWT       (success envelope)
  B. POST /api/secure/access/token        -> long-lived access JWT (expiration:0 => 2099)
  C. Build + validate a 1-Observation FHIR collection Bundle via fhir.resources
     (preflight gate; falls back to the static sample_bundle.json if the lib is absent)
  D. POST /api/secure/source/manual       -> multipart form field `file` (200 or 500 only)
  E. GET  /api/secure/resource/fhir       -> assert ZZZ-PII-CANARY-0001 is retrievable
  F. (--twice) re-POST + re-GET, print resource-count delta (non-idempotency probe, A3)
  G. (--pii-grep) print the docker-logs PII audit command for INFO and WARN

Exit codes:
  0  = steps A–E asserted clean (ROADMAP success criterion 1 empirically TRUE)
  >0 = a specific assertion failed; the failing success criterion is printed
       (drives the success-criterion-5 escalation note in docs/fasten-admin.md)

GPL-3.0 firewall (COMPL-06): HTTP-only. No Fasten source is patched/forked/vendored.
PII Tier 1 (CLAUDE.md): the ONLY PII-shaped value anywhere is the synthetic sentinel
ZZZ-PII-CANARY-0001. Admin creds below are THROWAWAY — never the production secret.

Spike-local install (no production manifest change):
    python -m pip install "httpx>=0.27" "fhir.resources>=8.0.0"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

try:
    import httpx
except ImportError:  # pragma: no cover - spike-local guard
    sys.exit(
        "FATAL: httpx not installed. Run: "
        'python -m pip install "httpx>=0.27" "fhir.resources>=8.0.0"'
    )

# --- Configuration (env-overridable; THROWAWAY defaults — never production secrets) ---
# Host 8080/18080 were occupied at spike time, so compose maps host 18081 -> container 8080.
BASE = os.environ.get("SPIKE_BASE", "http://localhost:18081")
ADMIN_USER = os.environ.get("SPIKE_ADMIN_USER", "spikeadmin")
ADMIN_PASS = os.environ.get("SPIKE_ADMIN_PASS", "spike-throwaway-pass-not-prod")
CANARY = "ZZZ-PII-CANARY-0001"
SAMPLE_BUNDLE = pathlib.Path(__file__).with_name("sample_bundle.json")
TIMEOUT = httpx.Timeout(30.0)


def fail(criterion: str, message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] ROADMAP success criterion {criterion}: {message}", file=sys.stderr)
    sys.exit(1)


def build_bundle_bytes() -> bytes:
    """Build + validate a minimal collection Bundle (preflight gate).

    Primary path: fhir.resources pydantic models (RESEARCH.md V5 Input Validation,
    Gate 1). Fallback: validate the static sample_bundle.json with json.load so the
    spike still runs if fhir.resources is unavailable (OQ1 Bundle-shape iterations
    are then done by editing sample_bundle.json directly).
    """
    try:
        from fhir.resources.bundle import Bundle  # type: ignore

        raw = json.loads(SAMPLE_BUNDLE.read_text(encoding="utf-8"))
        bundle = Bundle.model_validate(raw)  # pydantic v2 / fhir.resources >=8
        assert bundle.type == "collection", f"unexpected Bundle.type {bundle.type!r}"
        serialized = bundle.model_dump_json(exclude_none=True)
        assert CANARY in serialized, "canary lost during fhir.resources round-trip"
        print(f"  [C] Bundle validated via fhir.resources (type={bundle.type})")
        return serialized.encode("utf-8")
    except ImportError:
        raw = json.loads(SAMPLE_BUNDLE.read_text(encoding="utf-8"))
        assert raw.get("resourceType") == "Bundle", "sample is not a Bundle"
        assert raw.get("type") == "collection", "sample Bundle.type != collection"
        body = json.dumps(raw)
        assert CANARY in body, "canary missing from sample_bundle.json"
        print("  [C] Bundle validated via json fallback (fhir.resources absent)")
        return body.encode("utf-8")


def signin(client: httpx.Client) -> str:
    """Provision admin (first signup => admin) then sign in.

    OQ resolved empirically: the pinned :main digest serves the REST API at base
    path /api (NOT /web/api — that was a STANDBY-mode SPA artifact), HTTP only
    (config.spike.yaml disables the self-signed HTTPS), and only AFTER the
    database encryption key leaves STANDBY mode. The first /api/auth/signup
    creates the user; on reruns signup 4xx/409s harmlessly and signin is used.
    Both return the success envelope {"success":true,"data":"<session JWT>"}.
    """
    su = client.post(
        f"{BASE}/api/auth/signup",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    print(f"  [A0] POST /api/auth/signup -> {su.status_code} (first user => admin)")
    if su.status_code == 200:
        body = su.json()
        if body.get("success") and body.get("data"):
            return body["data"]
    # User already exists (rerun) or signup not needed -> sign in.
    r = client.post(
        f"{BASE}/api/auth/signin",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    print(f"  [A] POST /api/auth/signin -> {r.status_code}")
    if r.status_code != 200:
        fail("1", f"/api/auth/signin returned {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success") or not body.get("data"):
        fail("1", f"signin envelope not success: {body}")
    return body["data"]


def mint_access_token(client: httpx.Client, session_jwt: str) -> str:
    r = client.post(
        f"{BASE}/api/secure/access/token",
        headers={"Authorization": f"Bearer {session_jwt}"},
        json={"name": "etl-spike", "expiration": 0},  # 0 => exp 2099-12-31
    )
    print(f"  [B] POST /api/secure/access/token -> {r.status_code}")
    if r.status_code != 200:
        fail("1", f"/api/secure/access/token returned {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success") or not body.get("data"):
        fail("1", f"access-token envelope not success: {body}")
    return body["data"]


def post_manual(client: httpx.Client, access_jwt: str, bundle_bytes: bytes) -> dict:
    r = client.post(
        f"{BASE}/api/secure/source/manual",
        headers={"Authorization": f"Bearer {access_jwt}"},
        files={"file": ("bundle.json", bundle_bytes, "application/json")},
    )
    print(f"  [D] POST /api/secure/source/manual -> {r.status_code}")
    if r.status_code == 500:
        # RESEARCH.md OQ1/A2: 500 echoes the parse failure — surface it so a 30-min
        # Bundle-shape iteration (edit sample_bundle.json) can resolve it. Same endpoint.
        print(f"      500 error body (echoed parse failure): {r.text[:600]}")
        fail(
            "1",
            "manual-source POST returned 500 — read the echoed error above and adjust "
            "sample_bundle.json Bundle shape per RESEARCH.md OQ1/A2, then re-run "
            "(same endpoint, not a fallback).",
        )
    if r.status_code != 200:
        fail("1", f"manual-source POST unexpected status {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success"):
        fail("1", f"manual-source envelope not success: {body}")
    print("      200 envelope keys: " + ", ".join(sorted(body.keys())))
    return body


def verify_canary(client: httpx.Client, access_jwt: str) -> int:
    r = client.get(
        f"{BASE}/api/secure/resource/fhir",
        headers={"Authorization": f"Bearer {access_jwt}"},
    )
    print(f"  [E] GET /api/secure/resource/fhir -> {r.status_code}")
    if r.status_code != 200:
        fail("1", f"resource/fhir returned {r.status_code}: {r.text[:300]}")
    text = r.text
    if CANARY not in text:
        fail(
            "1",
            f"sentinel {CANARY!r} NOT retrievable in GET /api/secure/resource/fhir "
            "response — ingest did not surface the resource.",
        )
    print(f"      sentinel {CANARY!r} retrievable — success criterion 1 MET")
    # Best-effort resource count for the non-idempotency delta.
    try:
        payload = r.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return len(payload["data"])
        if isinstance(payload, list):
            return len(payload)
    except (ValueError, TypeError):
        pass
    return text.count(CANARY)


def run(twice: bool) -> int:
    print(f"Spike target: {BASE}")
    bundle_bytes = build_bundle_bytes()
    with httpx.Client(timeout=TIMEOUT) as client:
        session_jwt = signin(client)
        access_jwt = mint_access_token(client, session_jwt)
        post_manual(client, access_jwt, bundle_bytes)
        count1 = verify_canary(client, access_jwt)
        print(f"      resource-count after first ingest: {count1}")
        if twice:
            print("  [F] --twice: re-POST identical Bundle (non-idempotency probe, A3)")
            post_manual(client, access_jwt, bundle_bytes)
            count2 = verify_canary(client, access_jwt)
            delta = count2 - count1
            print(
                f"      resource-count after second ingest: {count2} "
                f"(delta={delta:+d}) — RESEARCH.md Pitfall 4 / DATA-09 input. "
                "Not an assertion; recorded for Phase 1.4 dedup design."
            )
    print("\n[PASS] steps A-E asserted clean — ROADMAP success criterion 1 empirically TRUE")
    return 0


def print_pii_grep() -> None:
    print(
        "PII-log audit (DATA-02 paired deliverable) — run on the host:\n"
        '  docker logs health-fasten-spike 2>&1 | Select-String "ZZZ-PII-CANARY"\n'
        "Repeat at FASTEN_LOG_LEVEL=INFO then FASTEN_LOG_LEVEL=WARN. Record whether the\n"
        "sentinel surfaces at each level + chosen mitigation in docs/fasten-admin.md.\n"
        "Any captured excerpt must contain ONLY the synthetic sentinel (CLAUDE.md PII Tier 1)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fasten ingest spike harness (throwaway)")
    parser.add_argument(
        "--twice", action="store_true",
        help="re-POST the identical Bundle and print the resource-count delta (A3)",
    )
    parser.add_argument(
        "--pii-grep", action="store_true",
        help="print the docker-logs PII audit command (INFO + WARN) and exit",
    )
    args = parser.parse_args()
    if args.pii_grep:
        print_pii_grep()
        return 0
    return run(args.twice)


if __name__ == "__main__":
    raise SystemExit(main())
