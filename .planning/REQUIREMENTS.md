# Requirements: Health

**Defined:** 2026-05-10
**Core Value:** Vsetky moje zdravotne data na jednom mieste, vyhladatelne a vlastne ovladane. Self-hosted aggregator nad open-source Fasten OnPrem (GPL-3.0, FHIR-based) s multi-tenant readiness od dna 1, pripraveny na SaaS pivot pre EU/SK trh.

**Sources:** PROJECT.md, BOOTSTRAP.md, `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS,SUMMARY}.md`

## v1 (M1) Requirements

Requirements pre uvodny release MVP. Kazdy sa mapuje na fazu v ROADMAP.md. Zaciatok faz: 1.0 (spike), 1.1 az 1.11. Faza 1.0 odblokuje 1.4+ (Fasten ingest API surface).

### INFRA — Container, encryption, secrets, networking

- [ ] **INFRA-01**: Docker Compose v2 stack v `projects/health/` (compose.yaml, .env.example, .gitignore strict)
- [ ] **INFRA-02**: LUKS (Linux prod) / BitLocker (Win dev) full-disk encryption na host volume; vsetky `data/`, `output/`, named volumes na FDE volume (PII Tier 1 baseline)
- [ ] **INFRA-03**: `.env`-driven config — DB URLs, Fasten paths, Cloudflare tunnel token placeholder; `.env` vo `.gitignore`, `.env.example` len placeholdery
- [ ] **INFRA-04**: Read-only bind mounts pre `data/imports/` (Apple Health zip drop) a `data/dicom/` (M2) cez `:ro` flag
- [ ] **INFRA-05**: Vaultwarden `bw` CLI sidecar init container — populates env vars at container startup; NIKDY bake secrets do images
- [ ] **INFRA-06**: Image pinning by digest — Fasten `:main@sha256:<digest>` (NIE `v1.1.3` ani `:latest`), Postgres `16.13-bookworm`, Traefik `v3.7.0`, Vaultwarden `1.36.0`
- [ ] **INFRA-07**: Container HEALTHCHECK directive per service + `restart: unless-stopped`
- [ ] **INFRA-08**: Internal Docker networks segregated — `health-edge` (Traefik + cloudflared), `health-app` (Fasten, Next.js, Postgres), `health-etl` (workers + Postgres). Network policy: `health-app` a `health-etl` NESMU byt reachable z `health-edge` okrem Traefik routes
- [ ] **INFRA-09**: 8-week re-pin cadence runbook pre Fasten `:main` digest — kto ho updatuje, rollback procedure, kompatibilita check
- [ ] **INFRA-10**: Cross-host parity check (Win dev → Linux prod) pred declaring M1 done — line endings (LF in containers), case-sensitive paths, file mode preservation

### DATA — Postgres analytics, Fasten SQLite, schema, RLS

- [ ] **DATA-01**: Postgres 16.13-bookworm container s `analytics` DB + extensions `pgcrypto`, `uuid-ossp`, `citext`
- [ ] **DATA-02**: Fasten OnPrem digest-pinned, SQLite-only (upstream Postgres support BROKEN per `config.yaml` 2026-05); SQLite file na encrypted host volume
- [ ] **DATA-03**: Drizzle 0.45.2 schema — tabulky `tenants`, `observations` (mirror Fasten resources), `etl_runs`, `etl_failures` (DLQ), `audit_log` (append-only), `consent_log`, `code_mappings`; M2 pridat `tags`, `notes`, `dna_findings`, `dicom_metadata`
- [ ] **DATA-04**: Vsetky multi-tenant tabulky maju `tenant_id UUID NOT NULL` constraint (NULL by bypass-ol RLS comparison `tenant_id = current_setting(...)`, fail-closed pattern)
- [ ] **DATA-05**: RLS active v M1 single-tenant — `pgPolicy` per multi-tenant tabulku, default tenant `andrej` provisioned pri init, default policy denies (`USING (false)`) ked tenant context unset
- [ ] **DATA-06**: pgcrypto column-level encryption pre `observations.provider_name`, `observations.freetext_notes`, `dna_findings.text` (M2) — `pgp_sym_encrypt` (authenticated, NIE plain `aes_encrypt`)
- [ ] **DATA-07**: Cross-DB linking cez `fasten_resource_id` column na `observations` — Fasten REST API + ID lookup, NIE JOIN cez DB hranicu (Fasten SQLite a Postgres analytics nemozu cross-DB join)
- [ ] **DATA-08**: ETL state v Postgres tabulkach `etl_runs` (`last_successful_observed_at` watermark) a `etl_failures` (DLQ s retry counter) — NIE files na disku (transactional konzistencia s data)
- [ ] **DATA-09**: Idempotent FHIR resource hash — `meta.tag.code = sha256(canonical_payload)` pri kazdom POST, dedup detection na Fasten side
- [ ] **DATA-10**: Time storage = UTC v Postgres `TIMESTAMPTZ` (vrátane FHIR `effectiveDateTime` s offset); render v user TZ az v UI display layer

### AUTH — Authentication & authorization

- [ ] **AUTH-01**: Fasten built-in single-user auth provisioned pri init (admin user, password z Vaultwarden bw fetch)
- [ ] **AUTH-02**: Next.js analytics layer Auth.js v5 (alebo v4.24.14 conservative — plan-phase decision) + Postgres adapter; login flow blocks vsetky non-public routes
- [ ] **AUTH-03**: `withTenant(tenantId, fn)` mandatory wrapper pre kazdu DB query — transaction-scoped `SET LOCAL app.current_tenant` (NIE `SET` bez `LOCAL` — leaks na pooled connection)
- [ ] **AUTH-04**: ESLint custom rule blocks `db.{select,insert,update,delete}` mimo `withTenant()` lexical scope; CI fail
- [ ] **AUTH-05**: Connection acquire/release hook reset-uje `app.current_tenant` na release (defense-in-depth proti `SET` bez `LOCAL` typo)

### ETL — Apple Health, Oura, Lab PDF OCR

- [ ] **ETL-01**: Python 3.13-slim ETL container — dependencies `apple-health-parser`, `fhir.resources`, `oura-ring` (OAuth2), `pdfplumber`, `pytesseract`, `psycopg[binary] 3.2.x`, `apscheduler`
- [ ] **ETL-02**: Apple Health zip upload → stream parse cez `lxml.etree.iterparse` (mandatory pre 30-200 MB exporty) → FHIR Bundle mapping → POST do Fasten ingest API
- [ ] **ETL-03**: Apple Health iPhone+Watch dedup — `device + start + class` dedup key, prioritizacia Watch > iPhone > 3rd-party app pre aggregate metrics (steps, HRV)
- [ ] **ETL-04**: Apple Health timezone handling — store UTC v Postgres, preserve original TZ v FHIR `effectiveDateTime` offset alebo extension
- [ ] **ETL-05**: Oura API v2 OAuth2 flow + refresh token rotation (PAT deprecated 2025); secrets z Vaultwarden bw fetch
- [ ] **ETL-06**: Oura daily cron 06:00 + `flock` lock + idempotent re-run (test: re-run produkuje zero new rows)
- [ ] **ETL-07**: Oura backfill 6-month historical pull pri first connect (180 req v ramci 5000 req/day rate limit, log back-pressure)
- [ ] **ETL-08**: Lab PDF OCR pipeline — Tesseract 5 s `tesseract-ocr-slk+eng` jazykmi + lokalny Ollama `qwen2.5:7b` (fallback only, NIKDY cloud OCR pred DPIA M3); per-vendor template parser PRIMARY (Unilabs SK template prvy)
- [ ] **ETL-09**: Manual review queue UI pre Lab OCR — extracted fields side-by-side s PDF, user MUSI confirm/reject pred persist do Fasten (NIE auto-confirm, OCR ~85% accuracy ceiling, wrong CRP/glucose môže mislead clinical decisions)
- [ ] **ETL-10**: Three-pass extraction s disagreement flagging (Tesseract result / Ollama result / regex-based result), unit normalization (mmol/L vs mg/dL → UCUM canonical), decimal-comma SK locale handling

### ANALYTICS — Next.js custom layer

- [ ] **ANALYTICS-01**: Next.js 15.2.4 (or 16.2.6 — plan-phase decision) App Router shell s Drizzle 0.45 + postgres@3.4.9 connection
- [ ] **ANALYTICS-02**: Dashboard route s cross-source timeline view (T8 table-stake + first slice of D4 differentiator)
- [ ] **ANALYTICS-03**: Unified search across Fasten resources + Postgres analytics (search bar + source filter); search-only nezasifrovane subset (encounter date, source, type), encrypted payloads via app-layer dec
- [ ] **ANALYTICS-04**: Trend charts per LOINC code (recharts alebo visx — plan-phase decision); reference range NIE auto-flag "abnormal" bez lab's own context
- [ ] **ANALYTICS-05**: Settings page so per-source connector status (Apple Health upload UI, Oura token entry s OAuth status, Lab PDF upload area, last sync timestamps)
- [ ] **ANALYTICS-06**: User profile + tenant context display (M4 prep — tenant name visible v header, M1 = "andrej")
- [ ] **ANALYTICS-07**: Backup status panel — last backup ts, next scheduled, last restore drill ts (transparency = trust)
- [ ] **ANALYTICS-08**: Tenant-aware routing — `tenant_id` resolved zo session, propagated do vsetkych DB queries cez `withTenant()`

### SEC — Security, secrets, network, logging

- [ ] **SEC-01**: 3-layer encryption compose — LUKS/BitLocker (host volume) + pgcrypto column-level (defense-in-depth) + age (backups, off-site)
- [ ] **SEC-02**: pino logger so PII redaction **allowlist** (NIE denylist — fail-closed) + `tests/logger-redaction.test.ts` ako CI gate
- [ ] **SEC-03**: ESLint rule blocks non-allowlisted top-level log keys (e.g. `logger.info({ patient: ... })` fails CI)
- [ ] **SEC-04**: Sentry/error tracking off by default (`SENTRY_ENABLED=false`); ked on, redact before send + scrub `req.body` na `/api/health/*` routes
- [ ] **SEC-05**: Network segmentation enforcement — `health-app`/`health-etl` networks reachable iba z Traefik routes na `health-edge`; bez Traefik = no path
- [ ] **SEC-06**: Secret access tenant-namespaced key (M4 prep) — `bw get tenant/<id>/<secret>` pattern, M1 = `bw get default/<secret>`
- [ ] **SEC-07**: Cloudflare Tunnel TLS termination na CF edge (Phase 1.11+); origin Traefik = HTTP plain (documented accepted risk — CF Tunnel mTLS pre origin->CF, CF->Traefik = encrypted only via tunnel)
- [ ] **SEC-08**: Pre-commit hooks `gitleaks` + `detect-secrets` + license hash check pre Fasten image (no untrusted swap)

### OPS — Backup, restore, monitoring

- [ ] **OPS-01**: Nightly backup pipeline — `pg_dump | age` + `sqlite3 .backup | age`, **pipe-only encryption** (no plaintext intermediate, `/tmp` ako tmpfs, NIKDY persist na disk pred encryption)
- [ ] **OPS-02**: Off-site backup target = Backblaze B2 EU region OR Hetzner Storage Box (NIE US-region S3 — GDPR cross-border transfer trap); rclone push s versioning
- [ ] **OPS-03**: Backup retention 30 daily + 12 monthly; encrypted at rest u providera (B2 default + age encryption layer)
- [ ] **OPS-04**: age private key v 3 nezavislych custody locations — USB v fire safe (paper printout `AGE-SECRET-KEY-1...`) + paper QR v safe + second physical machine NIE backed up by this pipeline. **NIKDY v Vaultwarden** (chicken-and-egg)
- [ ] **OPS-05**: Quarterly restore drill (BLOCKING checklist item) — `tests/restore-smoke.test.ts` automated + manualny scratch container restore + checksum match
- [ ] **OPS-06**: NTP/time drift monitoring — alert ak container clock skew > 1s (signed cookies, JWT expiration, FHIR timestamps su sensitive)
- [ ] **OPS-07**: Docker logs rotation — `logging:` section per service v compose.yaml (`max-size: 10m`, `max-file: 3`)
- [ ] **OPS-08**: `docs/runbooks/disaster-recovery.md` documented (M1 deliverable) — restore procedure, RTO/RPO targets, communication plan

### TEST — Verification gates

- [ ] **TEST-01**: `tests/rls.test.ts` CI-gating — dvaja test users v dvoch tenantoch, asserts cross-tenant SELECT/INSERT/UPDATE/DELETE returns zero rows; vrátane raw SQL via Drizzle client; pool reuse test (request 1 tenant A → request 2 tenant B na rovnakom pooled connection nesmie videl A's data)
- [ ] **TEST-02**: `tests/fhir-subject-coherence.test.ts` — kazdy Observation ma `subject = Patient/<tenant_id>` matching session tenant; coherence check pre Bundle uploads
- [ ] **TEST-03**: `tests/logger-redaction.test.ts` — log lines obsahujuce PII keys (FHIR resource, patient identifier) su redacted, allowlist verified
- [ ] **TEST-04**: `tests/restore-smoke.test.ts` — backup → age decrypt → scratch Postgres restore → `pg_dump` checksums match original (Phase 1.10 acceptance)
- [ ] **TEST-05**: `research/lab-pdf-ocr-bench.md` — 5+ Slovak Unilabs PDFs OCR accuracy ≥80% LOINC mapping (Phase 1.8 acceptance gate); pri zlyhani plan na manualny review queue 100% confirm

### UI — User-facing surfaces

- [ ] **UI-01**: Manual review queue UI pre Lab PDF OCR (mandatory pred persist do Fasten — Phase 1.8); side-by-side PDF + extracted FHIR fields, edit-and-confirm flow
- [ ] **UI-02**: Apple Health upload UI — drop zip area, parse progress, idempotency message ("0 new observations imported, 1234 already exist")
- [ ] **UI-03**: Oura token entry UI — OAuth flow trigger, refresh token status, last sync ts, manual sync button

### COMPL — GDPR, regulatory, license

- [ ] **COMPL-01**: GDPR Art. 9 explicit consent model — `consent_log` table per tenant per data category boolean + evidence (timestamp, IP placeholder for SaaS, version hash); M1 = single tenant `andrej` self-consent baseline
- [ ] **COMPL-02**: Slovak language consent UI scaffold (M4 prep — `next-intl` integration v M3, consent strings v `sk` locale)
- [ ] **COMPL-03**: Right to data portability (Art. 20) — FHIR Bundle export endpoint per tenant + checksum verification; testable v M1 single-tenant
- [ ] **COMPL-04**: Right to erasure (Art. 17) — true delete (NIE soft-delete s flag), audit_log retention rules (audit metadata only, no PII), 30-day timeline runbook
- [ ] **COMPL-05**: Audit log captures all reads/writes per tenant per resource (immutable append-only `audit_log` table) — required by Art. 32 technical measures evidence
- [ ] **COMPL-06**: GPL-3.0 architectural firewall — Fasten v separate process s SQLite DB, custom code (Next.js + ETL Python) komunikuje cez HTTP (Fasten REST API) ONLY; NIKDY patches do Fasten source, NIKDY shared library linkage
- [ ] **COMPL-07**: DPIA per EDPB template authored pred tenant 1 onboarding (M4 deliverable; consultation closes 2026-06-09, finalna template Q4 2026); M1 = self-DPIA self-onboarding
- [ ] **COMPL-08**: Art. 28 DPA boilerplate signed s vsetkymi third-party processors (Hetzner pri M4 cloud move, Cloudflare, Backblaze) pred SaaS launch

## Traceability — REQ to Phase Mapping (1-to-1, authoritative)

Every M1 requirement maps to exactly one phase in `ROADMAP.md`. Coverage: 75/75 REQs, no orphans, no double-mappings. Status updated as phases complete via `/gsd-transition`.

| REQ | Phase | Status |
|-----|-------|--------|
| INFRA-01 | 1.1 | Pending |
| INFRA-02 | 1.1 | Pending |
| INFRA-03 | 1.1 | Pending |
| INFRA-04 | 1.1 | Pending |
| INFRA-05 | 1.1 | Pending |
| INFRA-06 | 1.0 | Pending |
| INFRA-07 | 1.1 | Pending |
| INFRA-08 | 1.3 | Pending |
| INFRA-09 | 1.11 | Pending |
| INFRA-10 | 1.11 | Pending |
| DATA-01 | 1.2 | Pending |
| DATA-02 | 1.4 | Pending |
| DATA-03 | 1.2 | Pending |
| DATA-04 | 1.2 | Pending |
| DATA-05 | 1.2 | Pending |
| DATA-06 | 1.2 | Pending |
| DATA-07 | 1.4 | Pending |
| DATA-08 | 1.2 | Pending |
| DATA-09 | 1.4 | Pending |
| DATA-10 | 1.7 | Pending |
| AUTH-01 | 1.4 | Pending |
| AUTH-02 | 1.5 | Pending |
| AUTH-03 | 1.2 | Pending |
| AUTH-04 | 1.2 | Pending |
| AUTH-05 | 1.2 | Pending |
| ETL-01 | 1.6 | Pending |
| ETL-02 | 1.7 | Pending |
| ETL-03 | 1.7 | Pending |
| ETL-04 | 1.7 | Pending |
| ETL-05 | 1.6 | Pending |
| ETL-06 | 1.6 | Pending |
| ETL-07 | 1.6 | Pending |
| ETL-08 | 1.8 | Pending |
| ETL-09 | 1.8 | Pending |
| ETL-10 | 1.8 | Pending |
| ANALYTICS-01 | 1.5 | Pending |
| ANALYTICS-02 | 1.9 | Pending |
| ANALYTICS-03 | 1.9 | Pending |
| ANALYTICS-04 | 1.9 | Pending |
| ANALYTICS-05 | 1.9 | Pending |
| ANALYTICS-06 | 1.9 | Pending |
| ANALYTICS-07 | 1.9 | Pending |
| ANALYTICS-08 | 1.9 | Pending |
| SEC-01 | 1.1 | Pending |
| SEC-02 | 1.5 | Pending |
| SEC-03 | 1.5 | Pending |
| SEC-04 | 1.5 | Pending |
| SEC-05 | 1.3 | Pending |
| SEC-06 | 1.1 | Pending |
| SEC-07 | 1.11 | Pending |
| SEC-08 | 1.1 | Pending |
| OPS-01 | 1.10 | Pending |
| OPS-02 | 1.10 | Pending |
| OPS-03 | 1.10 | Pending |
| OPS-04 | 1.10 | Pending |
| OPS-05 | 1.10 | Pending |
| OPS-06 | 1.10 | Pending |
| OPS-07 | 1.10 | Pending |
| OPS-08 | 1.10 | Pending |
| TEST-01 | 1.2 | Pending |
| TEST-02 | 1.7 | Pending |
| TEST-03 | 1.5 | Pending |
| TEST-04 | 1.10 | Pending |
| TEST-05 | 1.8 | Pending |
| UI-01 | 1.8 | Pending |
| UI-02 | 1.9 | Pending |
| UI-03 | 1.9 | Pending |
| COMPL-01 | 1.11 | Pending |
| COMPL-02 | 1.11 | Pending |
| COMPL-03 | 1.10 | Pending |
| COMPL-04 | 1.10 | Pending |
| COMPL-05 | 1.11 | Pending |
| COMPL-06 | 1.4 | Pending |
| COMPL-07 | 1.11 | Pending |
| COMPL-08 | 1.11 | Pending |

### Phase to REQ summary

| Phase | Title | REQs (count) |
|-------|-------|--------------|
| 1.0 | Fasten Ingest API Spike | INFRA-06 (1) |
| 1.1 | Compose Skeleton + FDE + Vaultwarden Glue | INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-07, SEC-01, SEC-06, SEC-08 (9) |
| 1.2 | Postgres + RLS + Tests + ESLint Rule (HARD GATE) | DATA-01, DATA-03, DATA-04, DATA-05, DATA-06, DATA-08, AUTH-03, AUTH-04, AUTH-05, TEST-01 (10) |
| 1.3 | Traefik + Internal Network Routing | INFRA-08, SEC-05 (2) |
| 1.4 | Fasten Container + Smoke Test + Patient Resolver | DATA-02, DATA-07, DATA-09, AUTH-01, COMPL-06 (5) |
| 1.5 | Next.js Analytics + Auth.js + Logger Redaction | ANALYTICS-01, AUTH-02, SEC-02, SEC-03, SEC-04, TEST-03 (6) |
| 1.6 | Oura ETL | ETL-01, ETL-05, ETL-06, ETL-07 (4) |
| 1.7 | Apple Health XML ETL + Dedup + Timezone | ETL-02, ETL-03, ETL-04, DATA-10, TEST-02 (5) |
| 1.8 | Lab PDF OCR + Manual Review Queue (HARD GATE) | ETL-08, ETL-09, ETL-10, UI-01, TEST-05 (5) |
| 1.9 | Custom Analytics Dashboards + Settings UI | ANALYTICS-02, ANALYTICS-03, ANALYTICS-04, ANALYTICS-05, ANALYTICS-06, ANALYTICS-07, ANALYTICS-08, UI-02, UI-03 (9) |
| 1.10 | Backup + age + First Restore Drill (HARD GATE) | OPS-01, OPS-02, OPS-03, OPS-04, OPS-05, OPS-06, OPS-07, OPS-08, TEST-04, COMPL-03, COMPL-04 (11) |
| 1.11 | Cloudflare Tunnel + M1 Verification Gates | INFRA-09, INFRA-10, SEC-07, COMPL-01, COMPL-02, COMPL-05, COMPL-07, COMPL-08 (8) |

**Total: 75/75 M1 REQs mapped, no orphans, no double-mappings.**

## Out of M1 Scope (deferred to M2+)

Tieto requirements existuju ako placeholder pre buduce milestones; NIE su sucastou M1 done definition.

### M2 — Hardening, DICOM, DNA, expanded labs
- DICOM viewer integration (OHIF + Orthanc), `data/dicom/` pipeline
- DNA raw upload (23andMe / MyHeritage XML) + lokalny GWAS lookup (SNPedia + ClinVar — NIE cloud)
- Expanded lab template library — Synlab, Alpha medical, ProCare, 1-2 CZ/DE labs
- Vaultwarden bw sidecar replaces manual `.env` for production secrets
- Tags + notes + dashboards customization (`tags`, `notes`, `dashboards` tabulky)
- Full-text search via `pg_trgm` na nezasifrovany subset
- Observability stack — Loki+Grafana alebo Better Stack EU (M2 decision)

### M3 — i18n, cross-source correlation depth
- `next-intl` SK/CZ/DE/EN i18n
- D4 cross-source correlation full (Oura HRV + Apple sleep + lab cortisol na jednom charte, advanced trends)
- Move to Hetzner CX22 ak PC reliability painful

### M4 — SaaS pivot prep
- Per-tenant Fasten Docker container orchestration (Traefik subdomain routing, `compose.tenant.template.yaml`, provisioning automation, M4 benchmark of tenants/CX22)
- Authentik SSO front of vsetkych subdomains (`health.ardan.sk` → Authentik → Fasten/analytics) s per-tenant realm
- DPIA finalization per EDPB template (COMPL-07)
- Two-tier consent UI (Tier 1 service Art. 6(1)(b), Tier 2 explicit Art. 9(2)(a))
- Art. 28 DPA signed (COMPL-08)
- Custom code license decision (AGPL-3.0 recommended pre custom analytics layer)
- GPL-3.0 lawyer review (COMPL-06 firewall validation)

### M5 — First paying tenants + scaling
- Stripe / invoice billing
- Support runbooks
- pgbackrest pre PITR
- CX22 → CX32 ak RAM ceiling reached

### Permanent OOS (NIKDY, mimo scope tohto projektu)
- AI/LLM diagnostic suggestions (EU AI Act high-risk + MDR Class IIa+)
- Drug interaction alerts (regulacny)
- Imaging AI auto-flag (MDR Class III)
- Coaching recommendations (regulacny)
- Doctor portal / clinic-side workflow (iny trh)
- Insurance billing automation (mimo scope)
- Real-time wearable streaming (daily sync staci)
- Family member sub-accounts v jednej instance (M4 = per-person container)
- Native mobile app (PWA covers)
- EHR-direct Smart-on-FHIR (defer to MyHealth@EU 2029, ked EU API existuje)
- Cloud-by-default deploy pred DPIA (M4 with DPIA gates this)

## Validation Gates

Pre M1 completion (PITFALLS.md M1 Verification Gates summary):

1. `tests/rls.test.ts` passes (TEST-01)
2. `tests/fhir-subject-coherence.test.ts` passes (TEST-02)
3. `tests/logger-redaction.test.ts` passes (TEST-03)
4. `tests/restore-smoke.test.ts` passes + first manualny restore drill executed (TEST-04, OPS-05)
5. `research/lab-pdf-ocr-bench.md` checked in s ≥80% accuracy ON 5 Unilabs SK PDFs (TEST-05)
6. `pg_tables` query asserting RLS na vsetkych multi-tenant tables returns 0 rows (CI gate)
7. ESLint custom rules pass (`withTenant()` enforcement, log key allowlist)
8. age private key v 3 custody locations dokumentovane (OPS-04)
9. `docs/runbooks/disaster-recovery.md` complete (OPS-08)
10. `health.ardan.sk` reachable via CF Tunnel (INFRA-09, SEC-07)
11. Apple Health re-import test = 0 new observations (ETL-03 dedup verified)
12. Oura idempotent re-run = 0 new rows
13. Lab PDF manual review queue 100% confirm before persist (ETL-09)
14. Encryption layered verification — LUKS volume + sample pgcrypto column + age backup roundtrip
15. Vaultwarden bw fetch produces correct secrets at container startup (INFRA-05)
16. Cross-host parity test passes (Win dev → Linux prod) (INFRA-10)
17. `consent_log` schema in place + andrej self-consent recorded (COMPL-01)
18. `audit_log` immutable append-only verified (COMPL-05)
19. Backup pipeline produces deterministic age-encrypted output (OPS-01..03)
20. `withTenant()` ESLint rule blocks bypass attempt in CI (AUTH-04)

## Evolution

Tento dokument sa upravuje pri:

- **Phase transition** (`/gsd-transition`) — REQs splnene v phase oznacit `[x]`, pridat phase reference v komentari
- **New milestone** (`/gsd-new-milestone`) — pridat M2+ REQs zo "Out of M1 Scope" sekcie do M2/M3 Active sekcie
- **Milestone complete** (`/gsd-complete-milestone`) — audit `[x]` count vs total, zaznamenat odchylky v MILESTONE-SUMMARY.md
- **New decision** zachytena v PROJECT.md — pridat REQs zo SUMMARY.md research items
- **External ADR/PRD ingestion** (`/gsd-ingest-docs`) — overit konflikty s existujucimi REQs

---
*Last updated: 2026-05-10 after roadmap creation — traceability table is now authoritative 1-to-1 REQ-to-Phase mapping (resolves prior overlapping mappings).*
