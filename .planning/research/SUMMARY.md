# Project Research Summary

**Project:** Health — Personal Health Data Aggregator (Fasten + ETL + SaaS pivot path)
**Domain:** Self-hosted personal health record (PHR) aggregator with EU/SK multi-tenant SaaS pivot path
**Researched:** 2026-05-09
**Confidence:** HIGH on stack / infra / architecture; MEDIUM on Fasten ingest API (UNDOCUMENTED — needs Phase 1.0 spike) and EU lab OCR accuracy (no public benchmark — needs M1 acceptance gate)

> **Read this first.** Two corrections to PROJECT.md / BOOTSTRAP.md surfaced from Stack research:
>
> 1. **Fasten license = GPL-3.0** (not MIT). Verified via `gh api`. SaaS-pivot implications are real but manageable (architectural firewall + custom code AGPL-3.0 — see Pitfall 12).
> 2. **Fasten Postgres backend is BROKEN upstream** (verbatim from `config.yaml`). Plan: Fasten = SQLite-only on encrypted volume; Postgres 16.13 = analytics-only. Re-evaluate every Fasten release.

---

## Executive Summary

This project builds a self-hosted personal health record (PHR) on top of **Fasten OnPrem** (open-source FHIR aggregator, GPL-3.0) with a **custom Next.js + Drizzle 0.45 + Postgres 16 analytics layer** that adds cross-source correlation, multi-tenant readiness, and Slovak/Czech/German lab-PDF parsing. M1 ships single-user on a local PC running Docker Compose, with all multi-tenant + RLS plumbing **active from day one** so the M4 SaaS pivot becomes "swap auth provider + clone Fasten container per tenant" rather than a rebuild. Fasten covers ~12/18 table-stakes features OOTB (FHIR resource browse, Bundle upload, encounters, conditions, meds, immunizations, allergies); the custom layer must fill T5 Apple Health ETL, T6 Oura sync, T8 time-series viz, T10 backup, T11 encryption-at-rest, and the EU/SK differentiators (D1 lab PDF templates, D4 cross-source correlation, D11 per-tenant Fasten orchestration).

**The recommended approach is opinionated and infra-first:** encryption (LUKS/BitLocker) + Postgres + RLS + a passing `tests/rls.test.ts` gate **before any application code lands**. ETLs follow easiest-first (Oura → Apple Health → Lab PDF OCR), each writing to **Fasten as system of record** then mirrored to Postgres for analytics — single FHIR write path, single audit trail. Phase 1.0 is a 2-day **spike on Fasten's undocumented ingest API** (the README says "manual entry only" but the UI clearly POSTs FHIR Bundles internally — we need to identify the endpoint or fall back to volume-mount JSON drop). The EU healthcare reality is sober: no programmatic citizen-side data access until **MyHealth@EU citizen portal in 2029**, so manual export PDF → OCR → FHIR Observation is the only viable v1 path. **Slovak Unilabs covers ~70%+ of the SK lab market post-2026 Synlab acquisition** — that single template is the highest-leverage M1 ETL deliverable.

**Top risks and mitigations:** (1) **RLS multi-tenant theater** — `tenant_id` columns without enforced policies — mitigated by activating RLS in M1 single-tenant mode + a CI-gating `tests/rls.test.ts` that proves cross-tenant isolation before any feature code. (2) **Lost age private key** = unrecoverable backups — mitigated by 3 independent custody locations (USB in fire safe + paper QR + second device), NEVER in Vaultwarden, plus quarterly restore drill. (3) **OCR + LLM hallucination on lab values** — mitigated by mandatory human-review queue (no auto-ingest of medical values in M1) + per-template deterministic parsers as primary path with Tesseract+Ollama as fallback only. (4) **GDPR Art. 9 health data without explicit consent flow** — mitigated by `consent_log` schema in M1 + DPIA + two-tier consent UI before first paying tenant in M4. (5) **GPL-3.0 + per-tenant SaaS** — mitigated by architectural firewall (custom code in separate processes, never patched into Fasten) + AGPL-3.0 for custom layer + lawyer review before M4 launch.

---

## Key Findings

### Recommended Stack

Single Docker Compose stack on local PC (M1) → portable to Hetzner CX22 (M4). **Fasten OnPrem `:main@sha256:<digest>` (GPL-3.0, SQLite-only)** as FHIR system of record; **Postgres 16.13-bookworm** as analytics DB (NOT alpine — ICU collation issues); **Next.js 15.2.4 (conservative) or 16.x + Drizzle ORM 0.45.2 + drizzle-kit 0.31.10 + postgres@3.4.9 + Auth.js v4.24.14 (conservative) or v5 beta** for the analytics layer with first-class `pgPolicy`/`crudPolicy` RLS support; **Traefik v3.7.0** for label-driven routing behind **Cloudflare Tunnel** (TLS terminated at CF edge, no Let's Encrypt at Traefik). ETLs run in a **Python 3.13-slim** container using `apple-health-parser` (PyPI 2026-03), `oura-ring` (OAuth2 only — PAT deprecated), `pdfplumber + Tesseract 5 (with tesseract-ocr-slk) + Ollama qwen2.5:7b` for lab PDFs, `psycopg[binary] 3.2.x`, `fhir.resources` for FHIR R4 validation, `apscheduler` (M1) → BullMQ+Redis if scaling. Backups via **`age` (FiloSottile)** — pipe-only encryption, never plaintext intermediate. Encryption-at-rest = **LUKS (Linux prod) / BitLocker (Win dev)** on host volume; **pgcrypto** column-level for `provider_name`, `freetext_notes`, `dna_findings.text` as defense-in-depth.

**Core technologies:**
- Fasten OnPrem v1.1.3 (`:main@sha256:<digest>`): FHIR aggregator, system of record — only fully OSS PHR with active 2026 releases
- Postgres 16.13-bookworm: analytics DB, RLS engine, ETL state — first-class RLS + Drizzle integration
- Next.js 15.2.4 + Drizzle 0.45.2: custom analytics layer — Drizzle wins over Prisma for first-class RLS support
- Traefik v3.7.0 + cloudflared sidecar: edge routing — label-driven per-tenant orchestration in M4
- Python 3.13-slim ETL container: Apple Health / Oura / Lab PDF — mature OSS libraries cover most parsing needs
- Tesseract 5 + Ollama qwen2.5:7b: local OCR for lab PDFs — keeps Tier 1 PII off cloud OCR pre-DPIA
- age + restic: backup encryption — modern, simple, vetted; gpg keyring complexity avoided
- LUKS / BitLocker: host volume encryption — the floor under everything else

### Multi-tenant Fasten Verdict

**HIGH confidence: PER-TENANT FASTEN CONTAINER + Traefik subdomain routing + SHARED POSTGRES with `tenant_id` + RLS.** Native Fasten Multi-User mode is "work in progress" per upstream README — DO NOT rely on it. SQLite + multi-writer = wrong fit for shared instance. Per-tenant Fasten container costs ~150 MB RAM idle; estimate 30–50 tenants/CX22 (4 GB) idle / 5–10 active concurrent (FEATURES.md back-of-envelope; needs M4 benchmark). M4 SaaS = clone compose fragment per tenant + Traefik label-driven discovery + per-tenant volume + provisioning automation. **Phase 1.0 spike must validate Fasten ingest API surface** (POST FHIR Bundle, identify endpoint/auth) before Phase 1.4 lock — fall-back if no programmatic API: volume-mount JSON drop, OR direct SQLite write skipping validation, OR UI scraping (brittle).

### EU Market Reality

**No programmatic citizen-side EU EHR access until 2029** (MyHealth@EU citizen portal target per EHDS regulation in force March 2025). Until then, **manual export PDF → OCR → FHIR Observation is the only viable v1 path** for SK/CZ/DE/AT healthcare records. **Slovak Unilabs covers ~70%+ of SK lab volume** post-Synlab acquisition Feb 2026 — single template = biggest leverage in M1. ELGA AT, Czech eRecept, Germany Gematik all support PDF download → workable but later milestones. Apple Health export.zip + Oura API + Slovak Unilabs PDF cover **>80% of CEO's actual data sources today**. EHR-direct OAuth/Smart-on-FHIR (Fasten Connect commercial pattern) is permanently OOS for EU until MyHealth@EU 2029.

### Expected Features

**Must have (M1 table stakes):** T1 dashboard, T2 FHIR Bundle import, T3 manual record entry, T4 PDF attachment per encounter (OOTB Fasten); T5 Apple Health import, T6 Oura daily sync (custom Python ETL); T7 search (OOTB, flagged unstable v1.0.0); T8 time-series viz (custom recharts); T9 auth (OOTB single-user); T10 backup, T11 encryption-at-rest, T12 HTTPS (custom infra); T13–T17 FHIR resources (Encounters, Conditions, Medications, Immunizations, Allergies — OOTB v1.0.0); T18 lab results (OOTB display + custom LOINC-grouped trends).

**Should have (M2–M4 differentiators):** D1 Slovak/Czech/German lab PDF templates (the moat); D3 Apple Health deep ETL; **D4 cross-source correlation views (the keystone — depends on T5/T6/D1 ETLs landing first)**; D6 tagging + notes; D7 OCR-assisted inbox; D9 DICOM viewer (Orthanc + OHIF); D8 self-hostable AND SaaS-able from same codebase (architectural — `tenant_id` + RLS from M1); D2 multi-language UI SK/CZ/DE/EN (M3); D5 GDPR-first artifacts (DPIA, Art. 9 consent, Art. 32 evidence) (M4); D10 DNA upload + local GWAS; D11 per-tenant Fasten container (M4); D12 encrypted off-site backup.

**Defer / NEVER (anti-features A1–A12):** A1 AI/LLM diagnostic suggestions, A4 drug interaction alerts, A11 imaging AI auto-flag, A12 coaching recommendations (all = EU AI Act + MDR Class IIa+ catastrophic exposure — NEVER); A2 doctor messaging, A3 insurance billing, A5 real-time streaming, A6 mood tracking + AI insight (NEVER); A7 family member sub-accounts in single instance (use per-person container); A8 native mobile app (PWA covers); A9 EHR-direct Smart-on-FHIR (defer to MyHealth@EU 2029); A10 cloud-by-default (defer to M4 with DPIA).

### Architecture Approach

Eight architectural decisions (A1–A8): **A1 Fasten SQLite = system of record, Postgres = derived analytics mirror** (single FHIR write path, single audit trail). **A2 ETLs POST FHIR Bundle to Fasten first**, mirror process picks up to Postgres (MEDIUM-HIGH confidence — needs Phase 1.0 spike). **A3 Multi-tenant: per-tenant Fasten + shared Postgres + RLS**. **A4 RLS active in M1 single-tenant** (no multi-tenant theater — column without enforcement is worse than nothing). **A5 Build order = infra-first** (Postgres + RLS + Traefik before app code). **A6 Three encryption layers compose:** LUKS (mandatory) + pgcrypto column-level (defense-in-depth) + age for backups (mandatory off-site, key NEVER in Vaultwarden). **A7 Logging = pino allowlist redaction** (NOT denylist) + Sentry off by default. **A8 ETL state in `etl_runs`/`etl_failures` Postgres tables** (not files on disk).

**Major components:**
1. Fasten OnPrem (SQLite, per-tenant in M4) → FHIR resource CRUD
2. Postgres 16.13 analytics DB (shared, RLS-isolated) → cross-source query plane + ETL state + audit log
3. Next.js analytics layer → custom dashboards + T8 viz + D4 correlation
4. Python 3.13 ETL workers (Apple Health / Oura / Lab PDF / Patient resolver / FHIR R4 validation / idempotent watermark resume)
5. Traefik v3.7 → Docker label routing
6. cloudflared sidecar (Phase 1.9+) → public tunnel
7. Backup pipeline → age-encrypted nightly to B2 / Hetzner Storage Box

### Critical Pitfalls (Top 7 BLOCKERs from 38 total / 12 BLOCKERs)

1. **Multi-tenant theater (no RLS enforcement)** — Prevention: RLS active in M1 + `tests/rls.test.ts` CI gate + `pg_tables` query asserts every multi-tenant table has `rowsecurity=true` + ESLint blocking DB queries outside `withTenant()` wrapper. Recovery if missed: CATASTROPHIC (4% revenue / €20M GDPR fine).
2. **Lost age private key** — Prevention: 3 independent custody (USB in fire safe + paper QR + second device), NEVER in Vaultwarden, quarterly BLOCKING restore drill. Recovery: CATASTROPHIC permanent data loss.
3. **OCR + LLM hallucination on lab values** — Prevention: mandatory human-review queue (no auto-ingest medical values in M1) + per-template deterministic parser as PRIMARY path + Tesseract+Ollama as FALLBACK only + three-pass extraction with disagreement flagging.
4. **FHIR subject reference drift** — Prevention: tenant→Patient resolver runs first, single `Patient/<id>` per tenant in `tenants.fasten_patient_id` column, every ETL Observation populates `subject = Patient/<resolved_id>`, `tests/fhir-subject-coherence.test.ts`.
5. **Logger denylist leaks PII** — Prevention: pino allowlist (`paths: ['*']`, censor returns `[REDACTED]` except explicit `safeOp` envelope); HMAC tenant_id with rotating salt; ESLint rule on `logger.{info,warn,error}` keys; Sentry `SENTRY_ENABLED=false` default.
6. **Apple Health timezone + double-source duplicates** — Prevention: Postgres `TIMESTAMPTZ` everywhere; Python `dateutil.parser` always; FHIR `effectiveDateTime` with offset; source-aware dedup (Watch > iPhone > 3rd-party for aggregates); DST-week test sample.
7. **GDPR Art. 9 health data without explicit consent (M4 SaaS BLOCKER)** — Prevention: M1 = `consent_log` table + per-category consent boolean; M4 = two-tier consent UI (Tier 1 service Art. 6(1)(b) per data category; Tier 2 explicit Art. 9(2)(a) opt-in), DPIA before first paying tenant (EDPB template, consultation through 2026-06-09), Art. 28 DPA Hetzner + Cloudflare.

**Other BLOCKERs:** Pitfall 2 (connection pool reuses tenant context); Pitfall 7 (ETL state on disk); Pitfall 10 (wrong terminology code — NEVER RxNorm in EU); Pitfall 11 (unit conversion mmol/L vs mg/dL — always emit UCUM); Pitfall 12 (GPL-3.0 + per-tenant SaaS unclear copyleft); Pitfall 15 (Fasten ingest API undocumented — Phase 1.0 spike).

---

## Implications for Roadmap

**Total M1 estimate: 5–7 weeks** (PROJECT.md said "~1 mesiac"; spike + RLS gate + OCR accuracy bar realistically push to 5–7 weeks).

### Phase 1: Fasten Ingest API Spike

**Rationale:** Fasten README says "manual entry only" but UI clearly POSTs FHIR Bundles internally. If spike fails, ETL plan changes (volume-mount JSON drop / direct SQLite / UI scrape). Allocate 2 days; escalate if blocked.
**Delivers:** Working Python script that POSTs 1-resource FHIR Bundle and confirms in Fasten UI. Audit Fasten's stdout logs for PII (Pitfall 32). Documented in `docs/fasten-admin.md`.
**Avoids:** Pitfalls 15, 32. Architectural rebuild later.

### Phase 2: Compose Skeleton + Encryption-at-Rest

**Rationale:** Encryption cannot be added later for PII Tier 1.
**Delivers:** `compose.yaml` with empty stubs, LUKS/BitLocker volume mounted, `.gitignore` strict, `.env.example` placeholders, Fasten image pinned to `:main@sha256:<digest>`.
**Addresses:** T11, Pitfalls 13, 32.

### Phase 3: Postgres + RLS Scaffolding (★ HARD GATE)

**Rationale:** The RLS test is the gate. If RLS doesn't work, every later phase rebuilds.
**Delivers:** Postgres 16.13, `analytics` DB, extensions (pgcrypto, uuid-ossp, citext), Drizzle schema (`tenants`, `observations`, `etl_runs`, `etl_failures`, `audit_log`, `consent_log`, `code_mappings`), RLS policies via `pgPolicy` on every multi-tenant table, `app_authenticated` role + `withTenant()` wrapper, default-deny policy (fail-closed), `tests/rls.test.ts` CI-gating, `tenant_id NOT NULL` everywhere, default tenant `andrej` provisioned, pre-commit hooks (gitleaks + detect-secrets + license hash check).
**Addresses:** Pitfalls 1, 2, 5, 10, 16, 29.

### Phase 4: Traefik + Internal Routing

**Rationale:** Edge in place before any service that needs routing. CF Tunnel deferred to last phase.
**Delivers:** Traefik v3.7.0, dashboard on `127.0.0.1:8080` localhost only, label-driven discovery, no public exposure.
**Addresses:** T12.

### Phase 5: Fasten Container + Smoke Test

**Rationale:** Resolves A2 confidence gap (Fasten ingest API). Without this, ETL phases blocked.
**Delivers:** Fasten OnPrem digest-pinned via Traefik at `/fasten/*`, single-user admin login, FHIR Bundle upload UI smoke-tested, POST endpoint integrated in `fhir_client.py`.
**Addresses:** T1, T2, T3, T4, T9, T13–T17, Pitfalls 13, 14.

### Phase 6: Next.js Analytics Skeleton + Auth.js + Logger

**Rationale:** Logger ships among the FIRST files (per A7) so `tests/logger-redaction.test.ts` lands before any code that might log a FHIR resource.
**Delivers:** Next.js 15.2.4 (or 16), Drizzle 0.45.2 connected, Auth.js v4.24.14 (or v5 beta) login, `withTenant()` wrapper proven, `APP_TENANT_DEFAULT=andrej`, **pino allowlist redaction** + `tests/logger-redaction.test.ts`, ESLint rule blocks non-allowlisted top-level log keys, `SENTRY_ENABLED=false` default.
**Addresses:** Pitfalls 6, 23, 31, 33.

### Phase 7: Oura ETL (Easiest Pipeline — Validates Framework)

**Rationale:** Easiest ETL — well-documented OAuth2 v2 API, JSON in / FHIR out, no OCR. Establishes patterns (etl_runs, watermarks, DLQ, idempotent upserts).
**Delivers:** Python 3.13-slim ETL, OAuth2 flow with refresh token, daily cron 06:00, Bundle POST to Fasten, mirror process to Postgres `observations`, watermark resume, idempotent FHIR resource hash (`meta.tag.code = sha256(...)`).
**Addresses:** T6, Pitfalls 4, 7, 24.

### Phase 8: Apple Health XML ETL

**Rationale:** Reuses Phase 7 infrastructure. Adds bulk + dedup + DST. Stream parse mandatory for 30–200MB+ exports.
**Delivers:** `apple-health-parser` integrated, polling drop folder via mtime, atomic staging, FHIR mapper top 10 HKQuantityType → LOINC + UCUM canonical units, `Observation.device` for source dedup (Watch > iPhone > 3rd-party for aggregates), `lxml.etree.iterparse()` streaming, tests for timezone (DST week) / dedup / unit conversion.
**Addresses:** T5, Pitfalls 8, 11, 20, 35.

### Phase 9: Lab PDF OCR Pipeline (Single Template — Hardest ETL)

**Rationale:** Hardest ETL — defer until easier ones prove framework. Per-template parser PRIMARY; Tesseract+Ollama FALLBACK. Mandatory human-review queue.
**Delivers:** pdfplumber + pdf2image + Tesseract 5 with `-l slk+eng`, Ollama qwen2.5:7b on-demand sidecar, **Unilabs SK template parser as primary** (deterministic column-region heuristic), three-pass extraction (Tesseract / Ollama / regex with disagreement flagging), locale decimal-comma normalization, LOINC mapping via `code_mappings`, dead-letter queue, **manual review UI** (side-by-side PDF + extracted fields, confirm/reject before write to Fasten). M1 acceptance: **>80% LOINC accuracy on 5 sample SK lab PDFs** OR mandatory review queue (no auto-ingest).
**Addresses:** D1 first slice, T18, Pitfalls 9, 21, 26.

### Phase 10: Backup Pipeline + Quarterly Restore Drill + CF Tunnel + Public Access (LAST)

**Rationale:** LAST. Public exposure is the final step. Backup before public access (in case leak triggers wipe-and-restore).
**Delivers:** age-encrypted nightly `pg_dump | age` + `sqlite3 .backup | age`, **pipe-only encryption** (no plaintext intermediate, `/tmp` as tmpfs), rclone push to B2 / Hetzner Storage Box (90-day retention), age private key in **3 independent custody** (USB fire safe + paper QR + second device — NEVER Vaultwarden), `tests/restore-smoke.test.ts`, **first restore drill executed** (BLOCKING), `docs/runbooks/disaster-recovery.md` complete, cloudflared sidecar enabled, `health.ardan.sk` reachable.
**Addresses:** T10, Pitfalls 3, 17, 19.

### Suggested Milestones M1–M5

| Milestone | Focus | Key Phases / Features | Avoids Pitfalls |
|-----------|-------|------------------------|-----------------|
| **M1** | Single-user self-hosted MVP | Phases 1–10 (above). Apple Health + Oura + Lab PDF (Unilabs SK) + custom analytics on local PC. CEO imports last 5 years, searches, charts. | All 12 BLOCKERs gated by 20-item M1 Verification Gates (PITFALLS.md) |
| **M2** | Hardening + DICOM/DNA + Off-site backup | D1 expanded (Medirex, 1–2 CZ/DE labs), D3 Apple Health deep ETL, D6 tagging, D7 OCR-assisted inbox, **D9 DICOM viewer (Orthanc + OHIF)** with `pydicom` Anonymizer, D10 DNA local GWAS (SNPedia + ClinVar, never cloud), D12 encrypted off-site (restic to B2), Vaultwarden `bw` sidecar replaces manual `.env`, pgcrypto for free-text, full-text search via `pg_trgm` | 21 (PDF drift), 25 (HMAC tenant_id rotation), 28 (DICOM PHI) |
| **M3** | Multi-language UI + Cross-source correlation depth | D2 SK/CZ/DE/EN i18n via `next-intl`, **D4 cross-source correlation fully fleshed** (Oura HRV + Apple sleep + lab cortisol on one chart), advanced trends. Move to Hetzner CX22 if PC reliability painful | 24 (Hetzner solves cron drift) |
| **M4** | SaaS pivot prep — multi-tenant orchestration + GDPR | **D11 per-tenant Fasten orchestration** (Traefik subdomain routing, `compose.tenant.template.yaml`, provisioning automation), **D5 GDPR artifacts** (DPIA per EDPB template, two-tier Art. 9 consent UI, Art. 28 DPA signed, Art. 32 evidence pack, audit_log infrastructure, Art. 17 hard erasure), **Authentik SSO** with per-tenant realm, M4 benchmark of tenants/CX22 capacity, license review (custom code AGPL-3.0) | 5, 12, 18, 19, 22, 27, 30 |
| **M5** | First paying tenants + scaling | DPIA finalization, Stripe / invoice billing, Art. 20 portability FHIR Bundle export, support runbooks. CX22 → CX32 if RAM ceiling. pgbackrest for PITR | 31 (cross-tenant aggregation audit) |

### Phase Ordering Rationale

- **Infra-first (Phases 1–4):** PII Tier 1 means encryption + RLS + Traefik must exist BEFORE app code. Refactoring crypto into a running app = retroactive risk.
- **Spike-before-lock (Phase 1):** Fasten ingest API undocumented per upstream README. 2-day spike eliminates highest-risk MEDIUM-confidence assumption (A2) before plan locks.
- **RLS test as gate (Phases 3 → 6):** `tests/rls.test.ts` BLOCKS Phase 6 app code. SaaS pivot survival depends on this never breaking.
- **Easiest ETL first (Phase 7 Oura) → hardest last (Phase 9 Lab OCR):** Oura validates FHIR write path / etl_runs / Patient resolver. Apple Health adds bulk + dedup + DST. Lab OCR adds OCR + LLM + human-review queue.
- **Backups + public exposure LAST (Phase 10):** Data + recovery must exist before exposure. CF Tunnel public + first restore drill co-gated.
- **Multi-tenant readiness M1, orchestration M4:** D8 + D11 design choices in M1 (tenant_id + RLS active, withTenant() everywhere) cost ~tenant_id columns + 1 wrapper now. M4 = swap auth + clone Fasten + iterate cron, NOT a rewrite.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 1 (Fasten ingest API spike)** — UNDOCUMENTED upstream. Spike IS the research. Without this, Phases 5–9 blocked.
- **Phase 9 (Lab PDF OCR)** — MEDIUM confidence on accuracy. No public Slovak Unilabs OCR benchmark. Need 5 real SK lab PDFs + accuracy bar before plan.
- **M4 prep** — Authentik per-tenant realm config, EDPB DPIA template (final later 2026), SNOMED CT Slovak national license, M4 tenant capacity benchmark, Art. 28 DPA boilerplate, GPL-3.0 lawyer review.

**Phases with standard patterns (skip deeper research):**
- Phase 2 (Compose + LUKS/BitLocker), Phase 3 (Postgres + RLS — Drizzle docs + Neon/Supabase guides), Phase 4 (Traefik), Phase 7 (Oura ETL — `oura-ring` library), Phase 10 (age + cloudflared).

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | HIGH | STACK.md verified versions on npm/PyPI/GitHub releases 2026-05-07/09; license verified via `gh api`; Postgres BROKEN warning verbatim from Fasten config.yaml. Sonnet researcher. |
| **Features** | MEDIUM-HIGH | FEATURES.md verified Fasten OOTB via README + v1.0.0 release notes; EU healthcare via EHDSI/HL7 EU sources; multi-user verdict MEDIUM (upstream "work in progress" — defer to per-tenant). Opus researcher. |
| **Architecture** | HIGH on M1 layout / MEDIUM on Fasten ingest API | ARCHITECTURE.md verified against Drizzle RLS docs, Traefik v3 docs, Fasten upstream README. **A2 ingest API has MEDIUM-HIGH confidence — programmatic POST exists but is opaque without source-read.** Phase 1 spike resolves. M4 per-tenant scaling estimate (30–50/CX22) needs M4 benchmark. Opus researcher. |
| **Pitfalls** | HIGH on Fasten/FHIR/RLS/encryption/GDPR / MEDIUM on Slovak-OCR-specific patterns and M4 SaaS regulatory pitfalls | PITFALLS.md verified against upstream code, FHIR R4 spec, GDPR text, peer-reviewed clinical-LLM hallucination studies (medRxiv 2025-02). MEDIUM on Slovak-lab OCR (no public benchmark). MEDIUM on M4 forward-looking (regulatory landscape moves; EDPB DPIA template June 2026 not yet final). Opus researcher. |

**Overall confidence: HIGH for M1 scope.** Two MEDIUM-confidence items have phase-aligned mitigation: Fasten ingest API (Phase 1 spike — 2 days before lock) and Slovak Unilabs OCR accuracy (Phase 9 acceptance bar with mandatory review queue + per-template primary parser).

### Gaps to Address

- **Fasten ingest API surface (HIGH urgency, 2-day Phase 1 spike)** — programmatic POST endpoint, auth, response. Documented in `docs/fasten-admin.md` post-spike. Plan-lock blocked until spike done.
- **Fasten stdout log audit (paired with Phase 1 spike)** — does Fasten log PII by default? If yes: `LOG_LEVEL=warn`, redaction sidecar, or restricted log mount.
- **Slovak Unilabs PDF samples for Phase 9 acceptance gate** — need 5 real SK lab PDFs.
- **eZdravie SK PDF download path** — flagged "PDF download not confirmed" in FEATURES.md; M2+ research item.
- **M4 benchmark of actual tenants/CX22** — FEATURES.md 30–50 estimate is back-of-envelope.
- **EDPB DPIA template** — consultation closes 2026-06-09; track and apply when published.
- **SNOMED CT Slovak national license** — free for personal/eval (M1 OK), unclear for SaaS production. Verify before M4. Fall-back: ICD-10/MKCh-10 only.
- **GPL-3.0 lawyer review** — required before M4 SaaS launch. Recommend AGPL-3.0 for custom analytics layer.
- **Custom analytics layer license decision** — TBD by M4 start.
- **Auth.js v5 vs v4.24.14 stable** — Roadmapper picks. Conservative: v4.24.14.
- **Next.js 16 vs 15.2.4 conservative** — Roadmapper picks. Conservative: 15.2.4.

---

## Sources

### Primary (HIGH confidence)
- Fasten OnPrem upstream: README + v1.0.0 release notes (Issue #349) + CONTRIBUTING.md + config.yaml + LICENSE (verified `gh api` → GPL-3.0)
- Drizzle ORM RLS docs (`pgPolicy`, `crudPolicy`, `enableRLS`) + GitHub Discussion #2450
- Neon docs: Simplify RLS with Drizzle + social-network RLS pattern
- Postgres 16 official docs — Row Security Policies
- Traefik v3 Docker provider + multi-tenant K8s architecture
- Cloudflare Tunnel docs (token connector, TLS)
- HL7 FHIR R4 Bundle + HL7 Europe Lab Report v9.1.0 + Austrian Patient Summary R4 v1.0.0
- EHDS Regulation (in force March 2025, MyHealth@EU 2029)
- GDPR Art. 9, Art. 17, Art. 20, Art. 28, Art. 32, Art. 33 official text
- age-encryption.org spec (FiloSottile/age)
- STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md (this project, 2026-05-09)

### Secondary (MEDIUM confidence)
- Multi-Tenant Docker Architecture (oneuptime.com 2026), AWS multi-tenant RLS blog, Permit.io RLS Implementation Guide
- Mend / FOSSA / FSF / Vaultinum — GPL-3.0 vs AGPL SaaS analysis
- TDDA Apple Health analysis, HealthKitOnFhir (Microsoft), Open Wearables (open-source 2026)
- MinerU + Chandra 2 (Datalab 2026-03)
- Slovak labs market consolidation under Unilabs Feb 2026 (investorsinhealthcare.com)
- EDPB DPIA template (consultation through 2026-06-09)
- SQLite WAL docs + concurrency forum + phiresky/oldmoe blogs
- EU AI Act for Medical Devices Compliance (mdxcro.com / EUCROF)

### Tertiary (LOW confidence — needs validation)
- Medical-LLM hallucination studies (medRxiv 2025-02, npj Digital Medicine, MedVH) — Qwen-2.5-72B vs GPT-4o overconfidence
- Tesseract Slovak diacritic Issue #130, #4276 — anecdotal, no public benchmark for Slovak lab PDFs
- Per-tenant CX22 capacity estimate (30–50) — needs M4 benchmark
- eZdravie SK PDF download path — not confirmed; M2 follow-up

---

*Research completed: 2026-05-09*
*Ready for roadmap: yes*
