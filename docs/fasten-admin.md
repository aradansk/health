# Fasten OnPrem — Programmatic FHIR Ingest Contract (Source of Truth)

> **Status:** ✅ PRIMARY PATH CONFIRMED — empirically verified 2026-05-19 (Phase 1.0 spike).
> **Audience:** downstream ETL phases 1.4 / 1.6 / 1.7 / 1.8 (this file is the contract; the
> `spike/` artifacts are throwaway/reference).
> **Scope:** spike-scoped. Production container wiring (Traefik, Vaultwarden-sourced
> secrets, healthcheck, log rotation) is Phase 1.4 — NOT in 1.0.
> **PII Tier 1 (CLAUDE.md):** the only PII-shaped value anywhere in this doc is the
> synthetic sentinel `ZZZ-PII-CANARY-0001`. No real or plausible-real health data.

---

## 0. TL;DR for Phase 1.4

The ETL writes to Fasten over HTTP only (GPL-3.0 firewall, COMPL-06) via three calls:

1. `POST /api/auth/signin {username,password}` → 1h **session JWT** (`{"success":true,"data":"<jwt>"}`)
2. `POST /api/secure/access/token` (Bearer session JWT) `{"name":"etl","expiration":0}` → long-lived **access JWT** (`exp` = 2099-12-31, `token_type:"access"`)
3. `POST /api/secure/source/manual` (Bearer access JWT), `multipart/form-data` single field `file` = FHIR Bundle JSON → `200 {"success":true,"data":<summary>,"source":<credential>}`

Verify with `GET /api/secure/resource/fhir` (Bearer access JWT).

**Non-obvious gotchas this spike resolved (read these before Phase 1.4):**

- The pinned `:main` digest **does NOT honour `FASTEN_<SECTION>_<KEY>` env-vars** for
  nested config keys. Use a **bind-mounted `config.yaml`** (OQ2 resolved).
- The shipped default config has `database.encryption.enabled: true` **with no key** →
  Fasten boots in **STANDBY mode** and the REST API is **not served** (only the
  first-run wizard SPA + `/api/health`). A `database.encryption.key` MUST be set.
- The default config has `web.https.enabled: true` → self-signed HTTPS. The spike
  disables it; Phase 1.4 should terminate TLS at Traefik and keep Fasten HTTP-internal.
- The pinned index digest `sha256:3f0192ac…` **drifted** vs the live `:main` index — see §2.

---

## 1. Ingest Endpoint Contract (success criteria 1, 3)

### 1.1 Auth flow (two-step — RESEARCH.md Pattern 1, empirically confirmed)

**Step A — provision admin / sign in**

```
POST /api/auth/signup    {"username":"<user>","password":"<pass>"}      (first user; once)
  → 200 {"success":true,"data":"<session JWT>"}
POST /api/auth/signin    {"username":"<user>","password":"<pass>"}
  → 200 {"success":true,"data":"<session JWT, 1h expiry>"}
```

Empirical note: on this pinned build the first signed-up user received role `user`
(JWT `"role":"user"`), **not** `admin`, yet `/api/secure/*` ingest + read worked
fully with it. The RESEARCH.md "first signup → admin" claim (from `auth.go` source)
did not hold for this digest; ingest does not require the `admin` role. Phase 1.4
should not depend on the role claim — depend only on a valid `access` token.

**Step B — mint the long-lived ETL access token**

```
POST /api/secure/access/token   Authorization: Bearer <session JWT>
     body {"name":"etl-spike","expiration":0}        (0 ⇒ exp = 2099-12-31)
  → 200 {"success":true,"data":"<access JWT>"}
```

Decoded access-JWT payload (synthetic spike token, throwaway):

```json
{ "role":"user", "iss":"docker-fastenhealth", "sub":"spikeadmin",
  "exp":4102444799, "iat":1779192818,
  "jti":"<uuid>", "token_type":"access" }
```

`exp 4102444799` = `2099-12-31T23:59:59Z`. `token_type:"access"` distinguishes it
from the 1h session JWT. This is the token the ETL stores in Vaultwarden (§3).

### 1.2 Ingest (primary path — RESEARCH.md Pattern 2, empirically confirmed)

```
POST /api/secure/source/manual   Authorization: Bearer <access JWT>
     Content-Type: multipart/form-data
     single form field   file = ("bundle.json", <bytes>, "application/json")
```

**Response envelope (only 200 or 500 — no 4xx for body errors):**

- `200 {"success":true, "data":<sync summary dict>, "source":<manualSourceCredential dict>}`
  - `data` = sync summary (resource processing result, dict)
  - `source` = a full `manualSourceCredential` row. Observed keys:
    `id, user_id, source_type/platform_type, patient, created_at, updated_at,
    endpoint_id, brand_id, portal_id, …` (plus OAuth-shaped null fields unused for
    manual sources: `access_token, refresh_token, id_token, client_id, …`).
- `500 {"success":false, "error":"<err.Error() — echoes the parse failure>"}`

Container access log on success (note: HTTP metadata only, no payload — see §4):
`POST /api/secure/source/manual" 200 … python-httpx/…`
`"Completed document processing: 2 resources"`.

### 1.3 Verify path

```
GET /api/secure/resource/fhir   Authorization: Bearer <access JWT>
  → 200, ingested resource(s) present (sentinel ZZZ-PII-CANARY-0001 retrievable
    within seconds of the POST — success criterion 1 empirically TRUE)
```

### 1.4 OQ1 resolved — Bundle profile tolerance

A minimal **`Bundle{ "type":"collection", "entry":[ Patient, Observation ] }`**
built + validated via `fhir.resources` (pydantic v2, `fhir.resources>=8.0.0`,
`Bundle.model_validate`) was **accepted as-is** — no Fasten-export profiling
required, no 500. `SyncAllBundle` ingested both resources; the verify GET returned
a resource count of **2**. Phase 1.4 may build arbitrary FHIR R4 collection Bundles
with `fhir.resources` and POST them directly (preflight-validate before POST — V5).

### 1.5 OQ2 resolved — config delivery form

`FASTEN_JWT_ISSUER_KEY` / `FASTEN_LOG_LEVEL` env-vars are **NOT honoured** by the
pinned `:main` digest for these nested config keys (boot logs showed the published
defaults still active). The working form is a **bind-mounted `config.yaml`** at
`/opt/fasten/config/config.yaml` (see `spike/config.spike.yaml`). Phase 1.4 MUST
deliver `jwt.issuer.key`, `database.encryption.key`, `log.level`, and
`web.https.enabled` via a mounted config file (Vaultwarden-templated), not env-vars.

**STANDBY mode (new, not in RESEARCH.md):** the shipped default config has
`database.encryption.enabled: true` with the `key:` line commented out. With no key,
Fasten logs `"Encryption key is missing. Starting in STANDBY mode"` and serves ONLY
the first-run wizard SPA + `GET /api/health` (`{"standby_mode":true}`). All
`/api/...` REST routes return the SPA HTML until a key is supplied. Supplying
`database.encryption.key` flips `standby_mode:false` (`"Encryption key found.
Initializing database."`) and the REST API becomes reachable. This is a **hard
prerequisite for any programmatic ingest** — Phase 1.4 acceptance must assert
`GET /api/health → standby_mode:false` before attempting auth.

---

## 2. Pinned Image Digest (success criterion 3 — INFRA-06)

**Pin the multi-arch OCI INDEX digest, NEVER the per-arch manifest digest** (Win-dev
amd64 + Linux-prod amd64/arm64 must resolve from one pin — INFRA-06 cross-host parity).

| Role | Digest |
|------|--------|
| **Pinned in `spike/compose.spike.yaml` (PLAN/RESEARCH)** | `ghcr.io/fastenhealth/fasten-onprem:main@sha256:3f0192ac77dda7fd0e25175f7383a426f6d5ee11be7981b8753c10f6b7447d91` |
| **LIVE `:main` OCI INDEX digest (2026-05-19, this spike)** | `sha256:d208351137e8ba6a06aacede0d87f459a8bb9fc2ed705e62f4a9ca3f693bd7ca` |

### 2.1 ⚠️ DIGEST DRIFT DETECTED — DO NOT silently re-pin

`docker buildx imagetools inspect ghcr.io/fastenhealth/fasten-onprem:main`
(2026-05-19) returned:

```
Name:      ghcr.io/fastenhealth/fasten-onprem:main
MediaType: application/vnd.oci.image.index.v1+json
Digest:    sha256:d208351137e8ba6a06aacede0d87f459a8bb9fc2ed705e62f4a9ca3f693bd7ca   ← LIVE INDEX
Manifests:
  linux/amd64  sha256:3f0192ac77dda7fd0e25175f7383a426f6d5ee11be7981b8753c10f6b7447d91   ← was pinned as "index"
  linux/arm64  sha256:9d152a0e0253497451e2e848945ac419cf41063ace481925d6738e0c9f765040
  (+ attestation manifests)
```

**Finding:** The digest pinned by RESEARCH.md (`sha256:3f0192ac…`) is now the
**per-arch `linux/amd64` manifest** inside a *new* index (`sha256:d208351137…`),
not the index itself. The floating `:main` tag was rebuilt between RESEARCH.md
capture and the spike run. The spike still succeeded because Docker resolved
`@sha256:3f0192ac…` as a valid amd64 manifest on this amd64 host.

This is precisely the **Pitfall 3 floating-tag drift** the digest pin exists to
catch — a positive validation of the INFRA-06 rationale. Per the no-silent-re-pin
rule, BOTH digests are recorded here. **Phase 1.4 must consciously choose the pin:**

- If amd64-only is acceptable short-term: pinning `@sha256:3f0192ac…` (per-arch) is
  reproducible and is the exact image this contract was verified against.
- For cross-host parity (INFRA-06 intent): re-pin to the **current INDEX**
  `@sha256:d208351137…` **and re-verify §1 + §4** against it before relying on it
  (the contract above was verified against the `3f0192ac…` amd64 build only).

Phase 1.11 owns the 8-week re-pin cadence (INFRA-09); Phase 1.1 SEC-08 owns the
license/image-hash pre-commit gate. Image layers are retained on the host as
intentional warm cache for Phase 1.1/1.4 (no real PII ever ingested — only the
synthetic sentinel, in a volume destroyed at spike end).

---

## 3. Security Note — `jwt.issuer.key` (RESEARCH.md Pitfall 1)

Fasten's `jwt.issuer.key` defaults to the **published constant**
`thisismysupersecuressessionsecretlength` (confirmed present verbatim in the
shipped `config.yaml` of the pinned digest, with the in-file comment "you should
ABSOLUTELY change this value before deploying Fasten"). With it unchanged, **anyone
can forge a valid JWT** and read/write all FHIR data. Fasten emits **no startup
warning** when the default is used — absence of error is NOT safety.

**MANDATORY for Phase 1.1 / 1.4:**

- `jwt.issuer.key` MUST be a Vaultwarden-sourced secret, delivered via the mounted
  `config.yaml` (env-var override does not work — §1.5). `bw get default/<fasten-jwt-issuer-key>`.
- `database.encryption.key` is likewise MANDATORY (without it Fasten is in STANDBY
  and serves nothing — §1.5) and MUST be Vaultwarden-sourced. **Losing this key
  makes the SQLCipher DB unrecoverable** — back it up with the DB (encrypted, per
  CLAUDE.md). Boot log confirms SQLCipher: `_cipher=sqlcipher … _key=<key>`.
- The long-lived `access` token MUST be stored via `bw get`, **never** committed to
  the repo, baked into an image, or left env-inspectable. Rotate it on the 8-week
  re-pin runbook (INFRA-09 / threat T-1.0-04).
- The spike used only THROWAWAY values (`spike-throwaway-key-not-prod`,
  `spike-throwaway-32byte-encryption-key-not-prod`, throwaway admin password) —
  never the production Vaultwarden secret (CLAUDE.md PII Tier 1).

---

## 4. LOG_LEVEL Decision + Idempotency (success criterion 2 — paired PII deliverable)

### 4.1 PII-log audit (DATA-02 paired — the core security finding)

Method: ingest the synthetic sentinel Bundle, then
`docker logs health-fasten-spike 2>&1 | Select-String "ZZZ-PII-CANARY"` at each level.

| `log.level` | Canary occurrences in `docker logs` | Verdict |
|-------------|--------------------------------------|---------|
| `INFO` (default) | **0** | sentinel does NOT surface |
| `warn` | **0** | sentinel does NOT surface |

**Result: at neither INFO nor WARN did bundle-derived content (the
`ZZZ-PII-CANARY-0001` sentinel) leak into `docker logs`.** This is a strong positive
security finding for this pinned build / this ingest path.

**Important nuance — gin access log is not gated by `log.level`:** even with
`log.level: warn`, Fasten's gin HTTP access logger keeps emitting `level=info`
lines (request method/path/status/latency/clientIP/user-agent). These contain
**HTTP metadata only — no request/response body, no FHIR payload, no canary**.
Example (synthetic, safe): `"POST /api/secure/source/manual" 200 748 "" "python-httpx/0.28.1"`.
So `log.level: warn` does not silence access logs, but the audit shows those logs
are PII-clean for the ingest path regardless.

**Chosen mitigation (defence-in-depth, for Phase 1.4 — even though clean here):**

1. `log.level: warn` in the mounted `config.yaml` (env-var form does not work — §1.5).
2. Docker `local` logging driver with rotation — OPS-07: `max-size: 10m`, `max-file: 3`.
3. Restricted host log mount + ≤30-day retention (V7).
4. Redaction sidecar (vector / fluent-bit) **only if** a future Fasten build is
   observed leaking payload at WARN — not required by this audit, kept as contingency.
5. Phase 1.4 must re-run this exact canary audit if the pinned digest is bumped
   (PII-leak behaviour is build-specific — RESEARCH.md confidence MEDIUM on this).

### 4.2 Idempotency probe (RESEARCH.md Pitfall 4 / A3 → Phase 1.4 DATA-09)

`spike_ingest.py --twice` (re-POST the identical Bundle, re-count via
`GET /api/secure/resource/fhir`):

- resource count after 1st ingest: **2**
- resource count after 2nd ingest: **2** — **delta = +0**

**Finding (nuances RESEARCH.md Pitfall 4):** re-POSTing the identical Bundle did
**NOT** multiply FHIR *resources* (count stayed at 2). RESEARCH.md hypothesised
duplicate resources; empirically Fasten upserts resources by stable id within
equivalent content, so the resource view stayed clean. **However**, each
`POST /api/secure/source/manual` still creates a **new `manualSourceCredential`
row** (a fresh `source.id` was returned on each call) — i.e. the endpoint is
non-idempotent at the *source* layer but resource-deduplicating at the *FHIR* layer
for identical content.

**Phase 1.4 DATA-09 implication:** resource-level dedup is partially handled by
Fasten for byte-identical Bundles, but the ETL MUST still enforce idempotency to
(a) avoid manual-source row proliferation and (b) handle near-identical (not
byte-identical) re-syncs. Keep the planned `meta.tag.code = sha256(canonical_payload)`
dedup + a content-hash guard before POST so unchanged sources are not re-sent.

---

## 5. Fallback Path Ranking (success criterion 1 contingency)

Primary path (rank 0) is **empirically confirmed**; ranks 1–4 are pre-analysed
contingencies only, for a future upstream breaking change.

| Rank | Fallback | Robustness | Mechanism | Verdict |
|------|----------|------------|-----------|---------|
| **0 (PRIMARY)** | `POST /api/secure/source/manual` + `access` token | **High** — authenticated, validated, Fasten-conformant, mobile-grade long-lived token | §1 of this doc | **USE THIS — confirmed** |
| 1 | `POST /api/secure/resource/composition` / `resource/related` | Medium — per-resource, not bundle; more round-trips | Same auth; documented routes | Only if manual-source proves unusable for bundles |
| 2 | Volume-mount JSON drop watched by Fasten | Low–Medium — no such folder-watcher exists in Fasten; would need a sidecar that itself calls the API → degenerate | sidecar `inotify`→API | Not a real independent fallback; demote |
| 3 | Direct SQLite write into Fasten schema | Low — bypasses validation+auth, **DB is SQLCipher-encrypted** (boot log: `_cipher=sqlcipher`), single-writer contention, breaks HTTP-only posture | `sqlite3`+cipher into `fasten.db` | Last resort; harder than RESEARCH.md assumed (encryption) |
| 4 | Headless-browser UI scrape of the upload form | Very Low — brittle, breaks on any frontend change | Playwright vs `/web` | Reject; documented for completeness only |

---

## 6. Escalation / Blocked Outcome (success criterion 5 — no silent overrun)

### ✅ PRIMARY PATH CONFIRMED

The spike completed **well inside the 2-working-day timebox** (single session,
2026-05-19). `spike_ingest.py` **exited 0** against the live throwaway
`health-fasten-spike` container:

```
[A] POST /api/auth/signin                -> 200
[B] POST /api/secure/access/token        -> 200  (access JWT, exp 2099)
[D] POST /api/secure/source/manual       -> 200  (envelope keys: data, source, success)
[E] GET  /api/secure/resource/fhir       -> 200  sentinel ZZZ-PII-CANARY-0001 retrievable
[PASS] ROADMAP success criterion 1 empirically TRUE   EXIT=0
```

**No blocker — this is a successful primary-path completion.** The contract in §1
is the verified source of truth for Phase 1.4+.

### Documented deviations from RESEARCH.md (resolved in-line, NOT blockers)

These were resolved via the 30-min in-line iterations the spike anticipated; they
are recorded so Phase 1.4 inherits the correct facts, not the RESEARCH.md
assumptions:

1. **STANDBY mode / encryption key** (new) — pinned digest ships
   `database.encryption.enabled:true` with no key ⇒ REST API not served until a
   `database.encryption.key` is set. RESOLVED via bind-mounted config (§1.5, §3).
2. **Env-vars not honoured** — `FASTEN_<SECTION>_<KEY>` did not override nested
   config on this digest; bind-mounted `config.yaml` is the working form (§1.5).
3. **HTTPS by default** — shipped config has `web.https.enabled:true` (self-signed);
   spike disabled it for plain-HTTP testing; Phase 1.4 terminates TLS at Traefik (§0).
4. **Digest drift** — pinned `sha256:3f0192ac…` is now the per-arch amd64 manifest,
   not the live `:main` index `sha256:d208351137…`. Recorded, NOT silently re-pinned;
   Phase 1.4 must consciously choose + re-verify (§2.1).
5. **Role claim** — first signup got `role:user` not `admin`; ingest works without
   `admin`; Phase 1.4 must not depend on the role claim (§1.1).
6. **Host port** — host 8080 and 18080 were occupied at spike time; the spike
   mapped host **18081 → container 8080**. Phase 1.4 chooses its own host port
   behind Traefik (irrelevant to the contract).

### If a future re-run IS blocked

If Phase 1.4 (or a re-pin re-verification) hits a hard blocker — image pull
fails / network egress blocked / the contract in §1 no longer holds against a new
digest / STANDBY cannot be exited — do **not** silently overrun. Capture: the exact
blocker, the failing assertion from `spike_ingest.py`, the chosen **fallback rank**
from §5 (rank 1 `resource/composition` is the most likely next step), and the
concrete next-step commands, by appending to this section. A documented blocker +
chosen fallback is itself a valid phase completion.

---

## Appendix — Reproduce (throwaway, reference only)

```bash
# from repo root (spike artifacts are throwaway; this doc is the durable deliverable)
docker compose -f .planning/phases/HEALTH-01.0-fasten-ingest-api-spike/spike/compose.spike.yaml up -d
python  .planning/phases/HEALTH-01.0-fasten-ingest-api-spike/spike/spike_ingest.py            # exit 0 = criterion 1
python  .planning/phases/HEALTH-01.0-fasten-ingest-api-spike/spike/spike_ingest.py --twice    # idempotency probe
docker buildx imagetools inspect ghcr.io/fastenhealth/fasten-onprem:main                      # digest check
docker logs health-fasten-spike 2>&1 | Select-String "ZZZ-PII-CANARY"                         # PII audit
docker compose -f .planning/phases/HEALTH-01.0-fasten-ingest-api-spike/spike/compose.spike.yaml down -v   # destroy synthetic-only volume
```

Spike harness: host Python 3.12 + `pip install "httpx>=0.27" "fhir.resources>=8.0.0"`
(spike-local, no production manifest change). GPL-3.0 firewall (COMPL-06): HTTP-only,
no Fasten source patched/forked/vendored. PII Tier 1: only `ZZZ-PII-CANARY-0001`.

_Last verified: 2026-05-19 (Phase 1.0 ingest-API spike)._
