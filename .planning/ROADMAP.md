# Roadmap: Health — M1 (Personal Health Data Aggregator, Single-User Self-Hosted)

## Overview

M1 ships a single-user self-hosted health data aggregator on local PC docker desktop, built on Fasten OnPrem (FHIR system of record, GPL-3.0, SQLite-only) plus a custom Next.js + Postgres 16 analytics layer with **multi-tenant readiness from day one** (`tenant_id` + RLS active, single tenant `andrej` provisioned). The build is **infra-first**: encryption-at-rest, Postgres + RLS scaffolding, and a passing `tests/rls.test.ts` gate land before any application code. ETLs follow easiest-first (Oura → Apple Health → Lab PDF OCR), each writing to Fasten as system of record then mirrored to Postgres. Phase 1.0 is a 2-day spike on Fasten's undocumented ingest API (plan-lock blocked until spike resolves). Phase 1.10 first restore drill is a BLOCKING gate before Phase 1.11 public access via Cloudflare Tunnel.

**M1 done = CEO can import last 5 years of his own data, search and chart it, with all 20 verification gates passing.**

## Phases

**Phase Numbering:**
- Integer phase 1 (M1 milestone — 12 sub-phases: 1.0 spike + 1.1 through 1.11)
- Decimal phases (e.g., 1.2.1) reserved for urgent insertions (none yet)

Phases execute in numeric order: 1.0 → 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10 → 1.11

- [ ] **Phase 1.0: Fasten Ingest API Spike** — 2-day timeboxed spike validates Fasten's undocumented FHIR Bundle POST endpoint + log redaction baseline; chooses Fasten `:main` digest; outputs `docs/fasten-admin.md`. Plan-lock for downstream phases blocked until spike resolves.
- [ ] **Phase 1.1: Compose Skeleton + FDE + Vaultwarden Glue** — Docker Compose v2 scaffold, full-disk encryption (LUKS/BitLocker) on host volumes, `.env`-driven config, Vaultwarden bw lookup pattern, pre-commit hooks (gitleaks + detect-secrets + license hash check).
- [ ] **Phase 1.2: Postgres + RLS + Tests + ESLint Rule (HARD GATE)** — Postgres 16.13 with `analytics` DB + extensions, Drizzle 0.45.2 schema (tenants, observations, etl_runs, etl_failures, audit_log, consent_log, code_mappings) with `tenant_id NOT NULL` + RLS policies on every multi-tenant table, `withTenant()` wrapper, ESLint rule, pgcrypto column encryption setup, `tests/rls.test.ts` passing in CI. **BLOCKS Phase 1.5+ application code.**
- [ ] **Phase 1.3: Traefik + Internal Network Routing** — Traefik v3.7 reverse proxy with label-driven discovery, dashboard on `127.0.0.1:8080` localhost-only, network segmentation (`health-edge` / `health-app` / `health-etl`), no public exposure.
- [ ] **Phase 1.4: Fasten Container + Smoke Test + Patient Resolver** — Fasten OnPrem digest-pinned via Traefik at `/fasten/*`, single-user admin login (password from Vaultwarden), FHIR Bundle upload UI smoke-tested, programmatic POST integrated in `fhir_client.py`, tenant-to-Patient resolver with `fasten_patient_id` column, idempotent FHIR resource hash pattern, GPL-3.0 architectural firewall validated.
- [ ] **Phase 1.5: Next.js Analytics Skeleton + Auth.js + Logger Redaction** — Next.js 15.2.4 (conservative) App Router shell with Drizzle wired up, Auth.js v4.24.14 single-user login blocking non-public routes, pino logger with allowlist PII redaction, `tests/logger-redaction.test.ts` passing, ESLint rule on log keys, `SENTRY_ENABLED=false` default.
- [ ] **Phase 1.6: Oura ETL (Easiest Pipeline — Validates Framework)** — Python 3.13 ETL container with OAuth2 v2 + refresh token rotation, daily cron 06:00 with flock + idempotent re-run, 6-month historical backfill, etl_runs watermark + DLQ patterns established for downstream ETLs.
- [ ] **Phase 1.7: Apple Health XML ETL + Dedup + Timezone** — Streaming `lxml.etree.iterparse` parser for 30-200 MB exports, FHIR Bundle mapper for top HKQuantityType to LOINC + UCUM, source-aware dedup (Watch > iPhone > 3rd-party), DST-week timezone test, `tests/fhir-subject-coherence.test.ts` passing.
- [ ] **Phase 1.8: Lab PDF OCR + Manual Review Queue (HARD GATE)** — Tesseract 5 + Slovak language pack, Unilabs SK template parser as PRIMARY (deterministic), Ollama qwen2.5:7b as FALLBACK, three-pass extraction with disagreement flagging, decimal-comma SK locale, mandatory manual review UI before persist (no auto-ingest of lab values). **Acceptance: â‰¥80% LOINC accuracy on 5 SK lab PDFs OR mandatory review queue 100% confirm before write.**
- [ ] **Phase 1.9: Custom Analytics Dashboards + Settings UI** — Cross-source timeline view (D4 differentiator first slice), unified search across Fasten + Postgres, LOINC-grouped trend charts with reference ranges, Settings page with per-source connector status (Apple Health upload, Oura token entry, Lab PDF upload), backup status panel, tenant-aware routing.
- [ ] **Phase 1.10: Backup Pipeline + age + First Restore Drill (HARD GATE)** — Nightly `pg_dump | age` + `sqlite3 .backup | age` (pipe-only, tmpfs `/tmp`, no plaintext intermediate), rclone push to Backblaze B2 EU / Hetzner Storage Box, age private key in 3 independent custody locations, `tests/restore-smoke.test.ts` + `docs/runbooks/disaster-recovery.md`, Right-to-portability/erasure endpoints. **Acceptance: first quarterly restore drill executed end-to-end. BLOCKS Phase 1.11.**
- [ ] **Phase 1.11: Cloudflare Tunnel + M1 Verification Gates** — cloudflared sidecar enabled, `health.ardan.sk` reachable with TLS terminated at CF edge, 8-week re-pin runbook, cross-host parity check (Win dev → Linux prod), audit_log immutable append-only verified, andrej self-consent recorded, M4 prep scaffolds (next-intl SK strings, self-DPIA, Art. 28 DPA boilerplate). **All 20 M1 verification gates pass.**

## Phase Details

### Phase 1.0: Fasten Ingest API Spike
**Goal**: Resolve the highest-risk MEDIUM-confidence assumption (Fasten's undocumented FHIR Bundle POST endpoint) before plan-lock; produce a working programmatic ingest path or a documented fallback (volume-mount JSON drop / direct SQLite write / UI scrape). Audit Fasten stdout logs for PII leakage as a paired deliverable.
**Depends on**: Nothing (first phase, blocks 1.4+ ETL plan-lock)
**Requirements**: INFRA-06, DATA-02
**Success Criteria** (what must be TRUE):
  1. A Python script POSTs a 1-resource FHIR Bundle to a running Fasten container and the resource appears in the Fasten UI within seconds (or, if no programmatic API exists, a documented fallback path is captured with concrete commands).
  2. Fasten's stdout logs reviewed against PII Tier 1 baseline; PII findings (if any) noted with mitigation (LOG_LEVEL adjustment, redaction sidecar, or restricted log mount).
  3. Chosen Fasten image digest (`ghcr.io/fastenhealth/fasten-onprem:main@sha256:<digest>`) recorded in `docs/fasten-admin.md` together with the ingest endpoint, auth pattern, and response semantics.
  4. `docs/fasten-admin.md` checked into the repo as the source of truth for downstream ETL phases.
  5. Spike completes within 2 working days; if blocked, escalation note documents the blocker and the chosen fallback (no silent overrun).
**Plans**: TBD
**UI hint**: no

### Phase 1.1: Compose Skeleton + FDE + Vaultwarden Glue
**Goal**: Establish encrypted, version-pinned Docker Compose v2 stack scaffold with strict secret hygiene before any service runs. Encryption cannot be retrofitted for PII Tier 1 — it ships first.
**Depends on**: Phase 1.0
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, INFRA-07, INFRA-08, SEC-01, SEC-06, SEC-08
**Success Criteria** (what must be TRUE):
  1. `compose.yaml` exists in `projects/health/` with version-pinned image stubs (Fasten digest from Phase 1.0, Postgres 16.13-bookworm, Traefik v3.7.0, Vaultwarden 1.36.0); `docker compose config` validates without errors.
  2. Host volumes for `data/`, `output/`, named Docker volumes all sit on a full-disk-encrypted partition (LUKS on Linux prod, BitLocker on Windows dev); a verification document records the encryption status of each mount point.
  3. `.env` is in `.gitignore`, `.env.example` contains only placeholders (no real tokens), and a `git diff` against an empty `.env` shows no secret leakage; pre-commit hooks (`gitleaks`, `detect-secrets`, license hash check for Fasten image) block secret commits in a CI dry-run.
  4. `bw get default/<secret>` pattern documented (M1 manual fetch) with M4 prep target `bw get tenant/<id>/<secret>` noted; init-container sidecar template prepared for M2+ but not yet wired.
  5. `data/imports/` and `data/dicom/` bind-mounts use `:ro` flag in `compose.yaml`; every service declares HEALTHCHECK and `restart: unless-stopped`; layered encryption verification (LUKS volume + sample pgcrypto column round-trip planned for 1.2 + age backup planned for 1.10) recorded as a living checklist.
**Plans**: TBD
**UI hint**: no

### Phase 1.2: Postgres + RLS + Tests + ESLint Rule (HARD GATE)
**Goal**: Ship the multi-tenant data foundation that every later phase depends on: Postgres 16 with `analytics` DB, RLS-enforced schema with `tenant_id NOT NULL` everywhere, transactional `withTenant()` wrapper, ESLint guardrail, and a passing `tests/rls.test.ts` proving cross-tenant isolation. **This is the project's most important gate — the SaaS pivot survival depends on it never breaking.**
**Depends on**: Phase 1.1
**Requirements**: DATA-01, DATA-03, DATA-04, DATA-05, DATA-06, DATA-08, AUTH-03, AUTH-04, AUTH-05, TEST-01
**Success Criteria** (what must be TRUE):
  1. `tests/rls.test.ts` passes in CI with two test users in two tenants asserting cross-tenant SELECT/INSERT/UPDATE/DELETE return zero rows (including raw SQL via Drizzle client and pool-reuse scenario where request 1 for tenant A followed by request 2 for tenant B on the same pooled connection cannot read A's data).
  2. `pg_tables` query asserting every multi-tenant table has `rowsecurity = true` returns 0 violating rows (CI gate); every multi-tenant table has `tenant_id UUID NOT NULL` constraint verified by schema introspection.
  3. ESLint custom rule blocks any `db.{select,insert,update,delete}` call outside a lexical `withTenant()` scope and fails CI on bypass attempt; connection acquire/release hook resets `app.current_tenant` (defense-in-depth verified by integration test).
  4. Drizzle 0.45.2 schema migration creates `tenants`, `observations`, `etl_runs`, `etl_failures`, `audit_log`, `consent_log`, `code_mappings` with `pgPolicy` definitions; default tenant `andrej` provisioned at init; default-deny policy (`USING (false)`) verified to block queries when tenant context is unset.
  5. pgcrypto column-level encryption round-trip works for `observations.provider_name` and `observations.freetext_notes` using `pgp_sym_encrypt` (authenticated); ETL state lives only in `etl_runs` (`last_successful_observed_at` watermark) and `etl_failures` (DLQ) Postgres tables — no on-disk state files.
**Plans**: TBD
**UI hint**: no

### Phase 1.3: Traefik + Internal Network Routing
**Goal**: Edge layer in place before any service that needs routing; network segmentation enforced so `health-app`/`health-etl` are unreachable except via Traefik routes on `health-edge`.
**Depends on**: Phase 1.2
**Requirements**: INFRA-08, SEC-05
**Success Criteria** (what must be TRUE):
  1. Traefik v3.7.0 runs with label-driven Docker discovery, dashboard available on `127.0.0.1:8080` (localhost-only, never public), and basic LAN-only HTTP entrypoint on `:80`.
  2. Three Docker networks (`health-edge`, `health-app`, `health-etl`) exist; an enforcement test attempting to reach a `health-app` service from a container outside Traefik routes fails (no network path).
  3. Traefik routing rule template for Fasten path-prefix `/fasten/*` is defined but not yet wired to a backend service (Phase 1.4 will attach Fasten); rules validate via `docker compose config`.
  4. Cloudflare Tunnel sidecar is present in compose but commented out / disabled (M1 LAN-only); a runbook note records the activation step deferred to Phase 1.11.
**Plans**: TBD
**UI hint**: no

### Phase 1.4: Fasten Container + Smoke Test + Patient Resolver
**Goal**: Stand up Fasten OnPrem as the FHIR system of record, smoke-test programmatic ingest, lock in the tenant-to-Patient resolver pattern (preventing FHIR subject reference drift), and document the GPL-3.0 architectural firewall.
**Depends on**: Phase 1.3
**Requirements**: DATA-02, DATA-07, DATA-09, AUTH-01, COMPL-06
**Success Criteria** (what must be TRUE):
  1. Fasten OnPrem container starts cleanly with the digest pinned in Phase 1.0, single-user admin account provisioned with password fetched from Vaultwarden via `bw get`, login via Traefik at `/fasten/*` reaches the dashboard.
  2. A FHIR Bundle uploaded both via UI and via the programmatic POST path identified in Phase 1.0 lands as a queryable Observation in Fasten; the same Bundle re-POSTed produces zero new resources (idempotent FHIR resource hash via `meta.tag.code = sha256(canonical_payload)` working).
  3. `tenants.fasten_patient_id` column populated for the default tenant `andrej`; cross-DB linking happens via `observations.fasten_resource_id` column + Fasten REST API lookup (no direct cross-DB JOIN attempted, no shared Fasten<->Postgres library linkage).
  4. `docs/architecture/gpl-firewall.md` documents the GPL-3.0 architectural firewall: Fasten runs in a separate process with its own SQLite DB, custom code (Next.js + Python ETL) communicates only via HTTP to Fasten REST, no patches into Fasten source, no shared library linkage. M4 lawyer-review checkpoint flagged.
**Plans**: TBD
**UI hint**: no

### Phase 1.5: Next.js Analytics Skeleton + Auth.js + Logger Redaction
**Goal**: Stand up the custom analytics layer with logger-first ordering — `tests/logger-redaction.test.ts` lands before any code that might log a FHIR resource. Auth.js single-user login blocks all non-public routes; multi-tenant `withTenant()` wrapper proven end-to-end.
**Depends on**: Phase 1.2 (RLS gate must pass), Phase 1.4 (Fasten reachable)
**Requirements**: ANALYTICS-01, AUTH-02, SEC-02, SEC-03, SEC-04, TEST-03
**Success Criteria** (what must be TRUE):
  1. Next.js 15.2.4 App Router shell builds and serves `/login` and a placeholder `/dashboard`; Drizzle 0.45 + postgres@3.4.9 connection works against Phase 1.2 Postgres; unauthenticated requests to `/dashboard` redirect to `/login`.
  2. Auth.js v4.24.14 with Postgres adapter completes a login flow for the default tenant `andrej`; session-resolved `tenant_id` propagates into a `withTenant()` call that returns rows from `observations` for that tenant only (verified end-to-end against the RLS gate).
  3. `tests/logger-redaction.test.ts` passes: log lines containing PII keys (FHIR resource, patient identifier, free-text notes) are redacted via pino allowlist (`paths: ['*']`, censor returns `[REDACTED]` except explicit `safeOp` envelope); ESLint rule rejects non-allowlisted top-level log keys (e.g. `logger.info({ patient: ... })` fails CI).
  4. Sentry/error tracking is off by default (`SENTRY_ENABLED=false` env baseline); when enabled in test config, redaction-before-send + `req.body` scrub on `/api/health/*` routes verified.
**Plans**: TBD
**UI hint**: yes

### Phase 1.6: Oura ETL (Easiest Pipeline — Validates Framework)
**Goal**: Establish the ETL framework (etl_runs watermark, idempotent FHIR Bundle POST, DLQ, OAuth2 token refresh) using Oura as the easiest pipeline — well-documented JSON API, no OCR. Patterns set here are reused by Apple Health (1.7) and Lab PDF (1.8).
**Depends on**: Phase 1.4, Phase 1.5
**Requirements**: ETL-01, ETL-05, ETL-06, ETL-07, DATA-08, DATA-09
**Success Criteria** (what must be TRUE):
  1. Python 3.13-slim ETL container starts with the dependency baseline (`apple-health-parser`, `fhir.resources`, `oura-ring`, `pdfplumber`, `pytesseract`, `psycopg[binary] 3.2.x`, `apscheduler`) verified in `pip list` output.
  2. Oura API v2 OAuth2 flow completes end-to-end with refresh token rotation working; tokens stored via Vaultwarden `bw get`; daily cron at 06:00 with `flock` lock fires successfully and writes to `etl_runs.last_successful_observed_at` watermark.
  3. Re-running the daily Oura ETL produces zero new observations (idempotent re-run verified via FHIR resource hash dedup); a deliberate API-error injection writes a row to `etl_failures` DLQ with retry counter incremented on next run.
  4. Initial 6-month Oura backfill completes (180 requests within 5000/day rate limit), back-pressure logged; resulting Observations visible both in Fasten UI and in Postgres `observations` mirror table for tenant `andrej`.
**Plans**: TBD
**UI hint**: no

### Phase 1.7: Apple Health XML ETL + Dedup + Timezone
**Goal**: Layer bulk ingest, source-aware deduplication, and DST-correct timezone handling onto the ETL framework from Phase 1.6. Ship `tests/fhir-subject-coherence.test.ts` to lock in the Patient resolver invariant.
**Depends on**: Phase 1.6
**Requirements**: ETL-02, ETL-03, ETL-04, DATA-10, TEST-02
**Success Criteria** (what must be TRUE):
  1. A 30-200 MB Apple Health export.zip uploaded to `data/imports/` is stream-parsed via `lxml.etree.iterparse` (memory stable under 500 MB), mapped to FHIR Bundle, POSTed to Fasten, mirrored to Postgres; a re-import of the same zip produces zero new observations (dedup verified end-to-end).
  2. Source-aware dedup using `device + start + class` key prioritises Apple Watch > iPhone > 3rd-party app for aggregate metrics (steps, HRV); a test sample with overlapping Watch + iPhone HRV reads stores only the Watch reading.
  3. Timezone correctness: Postgres stores `TIMESTAMPTZ` in UTC; FHIR `effectiveDateTime` preserves original TZ offset; a DST-week test sample (spring-forward + fall-back) round-trips without time drift; UI render layer (Phase 1.9) will surface user TZ.
  4. `tests/fhir-subject-coherence.test.ts` passes: every Observation in Fasten for tenant `andrej` has `subject = Patient/<resolved_id>` matching the session tenant; Bundle uploads with mismatched subjects are rejected at preflight (no partial POST).
**Plans**: TBD
**UI hint**: no

### Phase 1.8: Lab PDF OCR + Manual Review Queue (HARD GATE)
**Goal**: Deliver the highest-risk ETL — Slovak Unilabs lab PDF parsing with mandatory human review before persist. Per-template parser is PRIMARY; Tesseract+Ollama is FALLBACK. **No auto-ingest of medical values; OCR ~85% ceiling means wrong CRP/glucose can mislead clinical decisions.**
**Depends on**: Phase 1.7
**Requirements**: ETL-08, ETL-09, ETL-10, UI-01, TEST-05
**Success Criteria** (what must be TRUE):
  1. The Unilabs SK template parser (deterministic column-region heuristic) extracts patient, date, and lab fields from a sample PDF with structured output mapped to FHIR Observation + LOINC code via `code_mappings`; decimal-comma SK locale and unit normalization (mmol/L vs mg/dL → UCUM canonical) verified on test samples.
  2. Three-pass extraction (Tesseract result / Ollama qwen2.5:7b result / regex-based result) flags disagreements; failed extractions land in DLQ with original PDF retained for manual reprocessing.
  3. **Acceptance gate met**: `research/lab-pdf-ocr-bench.md` checked in showing â‰¥80% LOINC mapping accuracy on 5 real Slovak Unilabs PDFs **OR** the manual review queue enforces 100% confirm-before-persist (no auto-ingest of any lab value into Fasten).
  4. Manual review UI shows the original PDF side-by-side with extracted FHIR fields; user MUST click confirm or reject for each extraction before any value is persisted to Fasten; rejected items return to a queue for re-extraction or manual entry.
  5. Cloud OCR is not used in M1 (Tier 1 PII stays local); a TODO note for M3 DPIA captures the decision-revisit point.
**Plans**: TBD
**UI hint**: yes

### Phase 1.9: Custom Analytics Dashboards + Settings UI
**Goal**: Deliver the user-visible analytics surface — cross-source timeline view (D4 differentiator first slice), unified search, LOINC trend charts, settings page with per-source connector status. Closes the M1 user value loop: data ingested in 1.6/1.7/1.8 becomes observable here.
**Depends on**: Phase 1.5, Phase 1.6, Phase 1.7, Phase 1.8
**Requirements**: ANALYTICS-02, ANALYTICS-03, ANALYTICS-04, ANALYTICS-05, ANALYTICS-06, ANALYTICS-07, ANALYTICS-08, UI-02, UI-03
**Success Criteria** (what must be TRUE):
  1. Dashboard route shows a cross-source timeline with Oura readings, Apple Health metrics, and lab observations on one chart for the last 6 months; clicking any point opens its source detail.
  2. Unified search bar with source filter returns matching results across Fasten resources and Postgres `observations`; encrypted columns are decrypted in the app layer only after `withTenant()` resolves the session tenant; non-matching tenants return zero rows (RLS gate proven via UI test).
  3. Trend charts render per-LOINC-code time series using recharts with reference range bands sourced from the lab's own context (no app-derived "abnormal" flagging); user can change date range and download the underlying data.
  4. Settings page shows: Apple Health zip upload UI with parse progress + idempotency message ("0 new observations imported, 1234 already exist"); Oura token entry with OAuth status, refresh token health, last sync ts, manual sync button; Lab PDF upload area routing to the Phase 1.8 review queue.
  5. Header shows the current tenant context (`andrej` in M1; M4 prep visible); backup status panel surfaces last backup ts, next scheduled run, last restore drill ts (the value reflects Phase 1.10 work; defaults to "never" until 1.10 ships).
**Plans**: TBD
**UI hint**: yes

### Phase 1.10: Backup Pipeline + age + First Restore Drill (HARD GATE)
**Goal**: Ship encrypted off-site backups with pipe-only encryption (no plaintext intermediate), age private key in 3 independent custody locations, and **execute the first quarterly restore drill end-to-end**. This phase BLOCKS public access in Phase 1.11 — backups must work before the system goes online.
**Depends on**: Phase 1.9 (data exists to back up)
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04, OPS-05, OPS-06, OPS-07, OPS-08, TEST-04, COMPL-03, COMPL-04
**Success Criteria** (what must be TRUE):
  1. Nightly backup pipeline produces `pg_dump | age` and `sqlite3 .backup | age` artifacts with **pipe-only encryption** (no plaintext intermediate, `/tmp` is tmpfs, age recipient public key in repo, private key NEVER in Vaultwarden); deterministic age-encrypted output verified by hash comparison across two consecutive runs of identical input.
  2. age private key documented in 3 independent custody locations: USB stick in fire safe (paper printout `AGE-SECRET-KEY-1...` belt-and-suspenders), paper QR in safe, second physical machine NOT backed up by this pipeline; `docs/runbooks/disaster-recovery.md` records exact location of each copy and the bus-factor emergency contact.
  3. Off-site target = Backblaze B2 EU region OR Hetzner Storage Box (NOT US-region S3); rclone push with versioning works, retention policy `30 daily + 12 monthly` configured at provider; encrypted-at-rest layered (provider default + age).
  4. **First quarterly restore drill executed end-to-end**: pull a backup from B2/Storage Box, decrypt with age private key from USB, restore Postgres + Fasten SQLite to a scratch container, run `tests/restore-smoke.test.ts` (pg_dump checksums match original, observation count matches snapshot). Drill outcome and duration logged in `docs/runbooks/disaster-recovery.md`.
  5. Right-to-portability (Art. 20) FHIR Bundle export endpoint returns a checksum-verified Bundle for tenant `andrej`; Right-to-erasure (Art. 17) endpoint executes a true delete (not soft-delete) with audit_log retention rules verified (audit metadata only, no PII); 30-day timeline runbook checked in.
  6. Docker logs rotation (`max-size: 10m`, `max-file: 3`) configured per service in compose.yaml; NTP/time drift monitoring alerts when container clock skew >1s.
**Plans**: TBD
**UI hint**: no

### Phase 1.11: Cloudflare Tunnel + M1 Verification Gates
**Goal**: Open public access via Cloudflare Tunnel only after backups + restore drill (Phase 1.10) pass, then run the full 20-item M1 verification checklist. Land M4-prep scaffolds (next-intl SK strings, self-DPIA, Art. 28 DPA boilerplate) so the SaaS pivot is scaffold-ready, not a rewrite.
**Depends on**: Phase 1.10 (restore drill must pass before public access)
**Requirements**: INFRA-09, INFRA-10, SEC-07, COMPL-01, COMPL-02, COMPL-05, COMPL-07, COMPL-08
**Success Criteria** (what must be TRUE):
  1. Cloudflare Tunnel sidecar enabled, `health.ardan.sk` reachable from outside the LAN with TLS terminated at Cloudflare edge (origin Traefik = HTTP plain, documented as accepted risk in `docs/architecture/network-tls.md`); CF Tunnel mTLS for origin-to-CF documented.
  2. 8-week re-pin cadence runbook for Fasten `:main` digest checked in: who runs the re-pin, rollback procedure, kompatibility check; cross-host parity test (Win dev → Linux prod) passes for line endings (LF in containers), case-sensitive paths, and file mode preservation.
  3. `consent_log` schema in place with andrej self-consent baseline recorded (timestamp, version hash, per-data-category boolean: wearable/lab/manual); `audit_log` immutable append-only verified by an attempted UPDATE failing at the table-grant level; every read/write produces an audit row.
  4. M4 prep scaffolds present: `next-intl` integration stub with `sk` locale strings for consent UI text, self-DPIA document at `docs/compliance/dpia-self.md` (M1 baseline, EDPB template flagged for re-author when consultation closes 2026-06-09), Art. 28 DPA boilerplate template at `docs/compliance/dpa-template.md` (Hetzner/Cloudflare/Backblaze placeholders).
  5. **All 20 M1 verification gates pass** (per REQUIREMENTS.md Validation Gates): RLS test, FHIR subject coherence, logger redaction, restore smoke + first drill executed, OCR â‰¥80% accuracy or review-queue gate, `pg_tables` RLS query 0 rows, ESLint custom rules, age key custody, disaster-recovery runbook, CF Tunnel reachability, Apple Health re-import dedup, Oura idempotent re-run, lab PDF review-queue 100% confirm, layered encryption verification, Vaultwarden bw fetch, cross-host parity, consent_log + andrej baseline, audit_log immutability, deterministic backup output, withTenant() ESLint enforcement.
**Plans**: TBD
**UI hint**: no

## Progress

**Execution Order:**
Phases execute in numeric order: 1.0 → 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10 → 1.11

**HARD GATES** (block downstream phases if not passing):
- Phase 1.2 `tests/rls.test.ts` BLOCKS Phase 1.5+ application code
- Phase 1.8 â‰¥80% LOINC accuracy on 5 SK lab PDFs OR mandatory review queue 100% confirm-before-persist
- Phase 1.10 first quarterly restore drill executed end-to-end BLOCKS Phase 1.11 public access

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1.0 Fasten Ingest API Spike | 0/TBD | Not started | - |
| 1.1 Compose Skeleton + FDE + Vaultwarden Glue | 0/TBD | Not started | - |
| 1.2 Postgres + RLS + Tests + ESLint Rule | 0/TBD | Not started | - |
| 1.3 Traefik + Internal Network Routing | 0/TBD | Not started | - |
| 1.4 Fasten Container + Smoke Test + Patient Resolver | 0/TBD | Not started | - |
| 1.5 Next.js Analytics Skeleton + Auth.js + Logger | 0/TBD | Not started | - |
| 1.6 Oura ETL | 0/TBD | Not started | - |
| 1.7 Apple Health XML ETL + Dedup + Timezone | 0/TBD | Not started | - |
| 1.8 Lab PDF OCR + Manual Review Queue | 0/TBD | Not started | - |
| 1.9 Custom Analytics Dashboards + Settings UI | 0/TBD | Not started | - |
| 1.10 Backup Pipeline + age + First Restore Drill | 0/TBD | Not started | - |
| 1.11 Cloudflare Tunnel + M1 Verification Gates | 0/TBD | Not started | - |

## REQ Coverage Map

**v1 (M1) requirement coverage:** 75/75 mapped to phases (75 distinct REQ-IDs across INFRA/DATA/AUTH/ETL/ANALYTICS/SEC/OPS/TEST/UI/COMPL).

| Phase | Requirements |
|-------|--------------|
| 1.0 | INFRA-06, DATA-02 (2) |
| 1.1 | INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, INFRA-07, INFRA-08, SEC-01, SEC-06, SEC-08 (11) |
| 1.2 | DATA-01, DATA-03, DATA-04, DATA-05, DATA-06, DATA-08, AUTH-03, AUTH-04, AUTH-05, TEST-01 (10) |
| 1.3 | INFRA-08, SEC-05 (2 — INFRA-08 shared with 1.1) |
| 1.4 | DATA-02, DATA-07, DATA-09, AUTH-01, COMPL-06 (5 — DATA-02 shared with 1.0) |
| 1.5 | ANALYTICS-01, AUTH-02, SEC-02, SEC-03, SEC-04, TEST-03 (6) |
| 1.6 | ETL-01, ETL-05, ETL-06, ETL-07, DATA-08, DATA-09 (6 — DATA-08 shared with 1.2, DATA-09 shared with 1.4) |
| 1.7 | ETL-02, ETL-03, ETL-04, DATA-10, TEST-02 (5) |
| 1.8 | ETL-08, ETL-09, ETL-10, UI-01, TEST-05 (5) |
| 1.9 | ANALYTICS-02..08, UI-02, UI-03 (9) |
| 1.10 | OPS-01..08, TEST-04, COMPL-03, COMPL-04 (11) |
| 1.11 | INFRA-09, INFRA-10, SEC-07, COMPL-01, COMPL-02, COMPL-05, COMPL-07, COMPL-08 (8) |

**Coverage validation per section:**

- **INFRA (10):** 01-08 → 1.1 | 06 → 1.0+1.1 | 08 → 1.1+1.3 | 09,10 → 1.11 ✓
- **DATA (10):** 01,03,04,05,06,08 → 1.2 | 02 → 1.0+1.4 | 07 → 1.4 | 09 → 1.4+1.6 | 10 → 1.7 ✓
- **AUTH (5):** 01 → 1.4 | 02 → 1.5 | 03,04,05 → 1.2 ✓
- **ETL (10):** 01,05,06,07 → 1.6 | 02,03,04 → 1.7 | 08,09,10 → 1.8 ✓
- **ANALYTICS (8):** 01 → 1.5 | 02-08 → 1.9 ✓
- **SEC (8):** 01,08 → 1.1 | 02,03,04 → 1.5 | 05 → 1.3 | 06 → 1.1 | 07 → 1.11 ✓
- **OPS (8):** 01-08 → 1.10 ✓
- **TEST (5):** 01 → 1.2 | 02 → 1.7 | 03 → 1.5 | 04 → 1.10 | 05 → 1.8 ✓
- **UI (3):** 01 → 1.8 | 02,03 → 1.9 ✓
- **COMPL (8):** 01,05 → 1.11 | 03,04 → 1.10 | 06 → 1.4 | 02 (Slovak consent UI scaffold), 07 (DPIA), 08 (Art. 28 DPA) → 1.11 as M3/M4 prep scaffolds (per REQUIREMENTS.md these are explicitly M3/M4 deliverables; M1 lands placeholder/template-only versions in 1.11) ✓

**Mapping deviations from REQUIREMENTS.md REQ→Phase mapping table:**

1. **DATA-07** (cross-DB linking via `fasten_resource_id` column + Fasten REST API ID lookup) — not explicitly in mapping table. Resolved: mapped to **Phase 1.4** because the cross-DB lookup contract lands when `fhir_client.py` does Fasten REST round-trip. No GAP.
2. **SEC-06** (secret access tenant-namespaced key — `bw get tenant/<id>/<secret>` pattern, M1 = `bw get default/<secret>`) — not in mapping table. Resolved: mapped to **Phase 1.1** because Vaultwarden bw glue establishes the M1 default pattern; M4 prep tenant-namespacing as forward reference. No GAP.
3. **COMPL-02 / COMPL-07 / COMPL-08** — REQUIREMENTS.md "Out of M1 Scope" defers Slovak consent UI to M3 and DPIA + Art. 28 DPA to M4. Resolved: M1 Phase 1.11 lands **scaffolds only** (next-intl `sk` strings stub, self-DPIA baseline doc, Art. 28 DPA boilerplate template) so SaaS pivot is scaffold-ready. Full implementations defer to M3/M4 milestones. No GAP for M1 (scaffold deliverable).

**M1 GAP count: 0** — all 75 v1 REQ-IDs mapped to at least one phase.

## Cross-Phase Dependencies

```
1.0 (spike) ──────────────────┐
                              ▼
1.1 (compose+FDE) ──► 1.2 (★ HARD GATE: RLS) ──► 1.3 (Traefik)
                              │                       │
                              ▼                       ▼
                              │                  1.4 (Fasten + Patient resolver) ◄── consumes 1.0 spike output
                              │                       │
                              ▼                       ▼
                         1.5 (Next.js + Auth.js + logger redaction)
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
      1.6 (Oura ETL) ──► 1.7 (Apple Health) ──► 1.8 (Lab OCR + manual review)
                              │
                              ▼
                         1.9 (Custom analytics dashboards)
                              │
                              ▼
                         1.10 (Backup + age + first restore drill — HARD GATE)
                              │
                              ▼
                         1.11 (CF Tunnel + M1 sign-off)
```

**Critical paths:**
- 1.0 → 1.4 (spike output unblocks Fasten ingest API design)
- 1.2 (★ HARD GATE) → 1.5/1.6/1.7/1.8/1.9 (RLS active before any DB write code)
- 1.4 → 1.6/1.7/1.8 (`fhir_client.py` library used by all 3 ETLs)
- 1.6 → 1.7 → 1.8 (ETL framework patterns reused easiest-to-hardest)
- 1.5 → 1.9 (Next.js shell needed for UI surfaces)
- 1.10 (HARD GATE: first restore drill) → 1.11 (public exposure must have working backup + restore)

**No backward dependencies.** No phase depends on a later-numbered phase.

## M1 → M2 → M4 Forward References

Per REQUIREMENTS.md "Out of M1 Scope" section:

**M2 — Hardening, DICOM, DNA, expanded labs:**
- DICOM viewer integration (OHIF + Orthanc), `data/dicom/` pipeline
- DNA raw upload + lokálny GWAS lookup (SNPedia + ClinVar — NIE cloud)
- Expanded lab template library (Synlab, Alpha medical, ProCare, 1-2 CZ/DE labs)
- Vaultwarden bw sidecar replaces manual `.env` for production secrets
- Tags + notes + dashboards customization
- Full-text search via `pg_trgm`
- Observability stack (Loki+Grafana / Better Stack EU)

**M3 — i18n + cross-source correlation depth:**
- `next-intl` SK/CZ/DE/EN i18n + COMPL-02 Slovak consent UI scaffold full implementation
- D4 cross-source correlation full (Oura HRV + Apple sleep + lab cortisol on jednom charte)
- Move to Hetzner CX22 ak PC reliability painful

**M4 — SaaS pivot prep:**
- Per-tenant Fasten Docker container orchestration (Traefik subdomain routing, `compose.tenant.template.yaml`, provisioning automation, M4 benchmark of tenants/CX22)
- Authentik SSO front of všetkých subdomains s per-tenant realm
- DPIA finalization per EDPB template (COMPL-07 — consultation closes 2026-06-09, finálna template Q4 2026)
- Two-tier consent UI (Tier 1 Art. 6(1)(b), Tier 2 Art. 9(2)(a))
- Art. 28 DPA signed s Hetzner + Cloudflare + Backblaze (COMPL-08)
- Custom code license decision (AGPL-3.0 odporúčané pre custom analytics layer)
- GPL-3.0 lawyer review (COMPL-06 firewall validation)

**M5 — First paying tenants + scaling:**
- Stripe / invoice billing
- pgbackrest pre PITR
- CX22 → CX32 ak RAM ceiling

**Multi-tenant orchestration design choices in M1 (per ARCHITECTURE.md A3 + A4):**
- `tenant_id` columns + RLS active in M1 single-tenant (Phase 1.2) → M4 SaaS = swap auth provider + clone Fasten container per tenant + iterate cron, NOT a rebuild
- `withTenant()` wrapper mandatory in M1 (Phase 1.2 + 1.5 ESLint enforced) → M4 multi-tenant = no code refactor, just provisioning
- Tenant header badge in dashboard M1 (Phase 1.9) = "andrej" → M4 = tenant resolved from JWT/subdomain

---

*Created: 2026-05-10. Source: REQUIREMENTS.md REQ→Phase mapping (authoritative) + research/{SUMMARY,STACK,FEATURES,ARCHITECTURE,PITFALLS}.md. Granularity: fine (12 sub-phases, 5-10 plans each TBD).*
