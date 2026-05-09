# Pitfalls Research

**Domain:** Self-hosted personal health data aggregator (Fasten OnPrem + custom FHIR analytics + Postgres RLS) with EU/SK multi-tenant SaaS pivot path
**Researched:** 2026-05-09
**Confidence:** HIGH on Fasten/FHIR/RLS/encryption pitfalls (verified against upstream code, FHIR R4 spec, GDPR text, Drizzle docs, peer-reviewed clinical-LLM studies); MEDIUM on Slovak-lab-specific OCR failure patterns (no public benchmark — based on Tesseract Issue #130 + diacritic regression reports); MEDIUM on M4 SaaS forward-looking pitfalls (regulatory landscape moves)

> **Read this section first.** The 12 BLOCKER pitfalls below have a kill-the-project potential — either via silent data corruption, regulatory fine, or a multi-week rebuild. Roadmap MUST gate Phase 1 completion on the M1 verification checklist at the bottom of this document.

---

## Severity & Recovery Cost Conventions

| Severity | Concrete Impact | Examples |
|---|---|---|
| **BLOCKER** | Data loss, regulatory fine, silent PII leak, full rebuild required | Forgotten RLS, lost age key, GDPR Art. 9 without consent, FHIR subject reference drift |
| **HIGH** | Data quality degraded, partial rebuild, downtime, audit failure | OCR template drift, Apple Health timezone bugs, Fasten pin-loss |
| **MEDIUM** | Visible bug, cosmetic compliance gap, recoverable with effort | Logging cardinality, search inconsistencies, dev-prod drift |
| **LOW** | Annoying but recoverable in hours | Backup script script-only fixes |

| Recovery Cost | Time | Description |
|---|---|---|
| **CHEAP** | Hours | Code change, no data loss |
| **MODERATE** | Days–1 week | Reprocess data, fix migration, no leakage |
| **EXPENSIVE** | 2–4 weeks | Schema change + reingest from raw, may have leakage exposure |
| **CATASTROPHIC** | Months / unrecoverable | Permanent data loss, regulatory fine, cannot pivot to SaaS |

---

## Critical Pitfalls (BLOCKER — must address in M1)

### Pitfall 1: Multi-tenant theater (RLS column without enforcement)

**Domain:** Multi-tenant RLS

**What goes wrong:** `tenant_id` column exists in every table from M1, but RLS policies are not enforced (only app-layer `WHERE tenant_id = ?` filtering). Developer feels "we are multi-tenant ready" — but a single missed `WHERE` clause in a JOIN, a Server Action that forgets the filter, or a `findMany()` without explicit `tenantId` predicate leaks all tenants to one user. M4 SaaS launch under Art. 32 GDPR = first cross-tenant leak = supervisory fine + reputational kill.

**Why it happens:** Drizzle's `pgPolicy` is opt-in per table. `enableRLS()` must be called explicitly. Developers reason "I always include tenant_id in queries" and forget that Server Actions, RPC, and joined queries make this fragile.

**Prevention:**
1. **CI gate (BLOCKING):** SQL test verifying every table in `analytics` schema has `rowsecurity = true` and at least one policy. Fail the build if any new migration adds a table without RLS:
   ```sql
   SELECT tablename FROM pg_tables t
   LEFT JOIN pg_policies p ON p.tablename = t.tablename
   WHERE t.schemaname = 'public' AND t.rowsecurity = false;
   -- Must return 0 rows; CI fails otherwise.
   ```
2. **Architectural decision A4:** RLS policies active in M1 with single tenant `andrej` already provisioned. Default policy denies (`USING (false)`) until tenant context is set.
3. **`tests/rls.test.ts` as gate before app code (A5):** Two test users in two tenants — assert that read/insert/update/delete cannot see/touch the other tenant's rows, even with raw SQL via the Drizzle client.
4. **`tenant_id NOT NULL` constraint** on every multi-tenant table. Nullable `tenant_id` = NULL bypasses `current_setting('app.current_tenant')::uuid = tenant_id` (NULL ≠ anything in SQL), silent leak.
5. **Service-role bypass audit:** any code path that uses a Postgres role with `BYPASSRLS` (admin scripts, ETL bulk ingest) MUST write to `audit_log` first. CI grep for `BYPASSRLS` outside `audit_log` writer = fail.

**Warning signs (automated):**
- `pg_tables` query above returns any row → fail CI
- `tests/rls.test.ts` fails on cross-tenant read → fail CI
- Drizzle migration without `enableRLS()` → ESLint custom rule flags it
- Code grep finds `db.select(...)` without `withTenant(...)` wrapper in non-admin paths → fail CI

**Severity:** BLOCKER
**Recovery cost (if missed):** CATASTROPHIC at SaaS launch. Cross-tenant leak = GDPR Art. 33 breach (72-hour notification), Art. 83 fine up to 4% of revenue or €20M, plus rebuild trust. CHEAP if caught in M1 (just write `tests/rls.test.ts`).
**Phase to address:** M1 Phase 1.2 (postgres-rls). Verification gate before any application code lands.

---

### Pitfall 2: Connection pool reuses tenant context across requests

**Domain:** Multi-tenant RLS

**What goes wrong:** `SET LOCAL app.current_tenant = '<uuid>'` only persists for the current transaction. If app code uses pooled `postgres` driver and forgets to wrap each request in a transaction, a connection returned to the pool with stale `app.current_tenant` from a previous request handles the next request as that tenant. Or worse: `SET app.current_tenant` (without `LOCAL`) persists for the connection's session — every subsequent query on that pooled connection reads the prior tenant's data.

**Why it happens:** `SET LOCAL` is transaction-scoped, but Drizzle does NOT auto-wrap queries in transactions. Developer writes `await db.select()...` outside a `db.transaction()` → either the prior tenant's setting leaks (session-scope) or `current_setting('app.current_tenant')` errors with "setting does not exist", which Postgres returns as NULL with `?missing_ok=true` → RLS comparison `tenant_id = NULL` → no rows returned (silent), or rows returned (if prior connection set it).

**Prevention:**
1. **Mandatory `withTenant()` wrapper** (per A4 in ARCHITECTURE.md):
   ```typescript
   export async function withTenant<T>(tenantId: string, fn: (tx) => Promise<T>) {
     return db.transaction(async (tx) => {
       await tx.execute(sql`set local app.current_tenant = ${tenantId}`);
       return fn(tx);
     });
   }
   ```
2. **Default deny in policy:** every policy uses `current_setting('app.current_tenant', true)::uuid` (the `true` = `missing_ok`, returns NULL if unset). The policy then evaluates `tenant_id = NULL` = false. Forgetting `withTenant()` returns ZERO rows, NOT another tenant's rows. **Fail-closed, not fail-open.**
3. **ESLint custom rule:** flag any `db.select`, `db.insert`, `db.update`, `db.delete` that is not inside a `withTenant(...)` call lexically (analyze top of function for the wrapper).
4. **Connection acquire/release hook (defense-in-depth):** on connection release, run `RESET app.current_tenant`. Catches any code path that used `SET` without `LOCAL` by mistake.
5. **Test in `tests/rls.test.ts`:** simulate two requests in sequence using the same pool connection — verify request 2 cannot read request 1's tenant data.

**Warning signs:**
- Random "no rows returned" reports from CEO during M1 single-tenant testing → likely transaction-boundary bug
- `pg_stat_activity` shows long-lived `app.current_tenant` settings on idle connections → forgotten `RESET`
- E2E test: parallel requests for tenant A and tenant B return mixed data → pool boundary leak

**Severity:** BLOCKER
**Recovery cost (if missed):** CATASTROPHIC at multi-tenant launch. CHEAP if caught in M1 (the wrapper is a pre-existing pattern from Supabase/Neon docs).
**Phase to address:** M1 Phase 1.2 (postgres-rls) + Phase 1.5 (analytics-app). Wrapper exists before any DB query is written.

---

### Pitfall 3: Lost age private key = unrecoverable backups

**Domain:** Encryption / key management

**What goes wrong:** age uses asymmetric encryption — public key encrypts, private key decrypts. Backups encrypted to recipient `age1ql3z7...` are unrecoverable without the matching `AGE-SECRET-KEY-1...`. If the key is on the same disk that LUKS-encrypts (in `~/.config/age/keys.txt`) and the disk fails, OR if the key was in Vaultwarden which itself is in the encrypted backup, OR if the key is "I'll generate it later when I do first restore" — backups are paperweights.

**Why it happens:**
1. Convenience: `age -p` (passphrase) is rejected as too clunky, asymmetric is "more secure" without thinking through key custody.
2. "Vaultwarden has my key" — but Vaultwarden's DB is in the same LUKS volume that's being backed up.
3. "GitHub has my SSH key, age understands SSH keys" — but the SSH key's private half is on the dying disk.
4. **No restore drill ever performed.** Discovered at incident time → too late.

**Prevention:**
1. **Generate the age key on a separate device** (CEO's offline laptop, USB stick, paper QR code in safe).
2. **Three independent copies of the private key:**
   - Air-gapped USB stick in fire safe (paper printout of `AGE-SECRET-KEY-1...` as belt-and-suspenders)
   - Encrypted volume on second physical machine NOT backed up by this pipeline
   - Paper QR + plaintext printout in physical safe
   - **NOT in Vaultwarden** (Vaultwarden is part of the protected set — chicken-and-egg). Per ARCHITECTURE.md A6.
3. **Quarterly restore drill (BLOCKING checklist item):**
   - Pull a backup from Hetzner Storage Box
   - Decrypt with age private key from USB
   - Restore Postgres + Fasten SQLite to a scratch container
   - Run `tests/restore-smoke.test.ts` — verify analytics queries work, observation count matches snapshot date
   - **If drill fails: BLOCK any deploy until backup pipeline is fixed.**
4. **Document private key custody in `docs/runbooks/disaster-recovery.md`** — physical location of each copy, who knows where (CEO + emergency contact for surviving the bus factor).
5. **Key rotation plan:** annually, generate new keypair, re-encrypt last N backups to both old + new recipient (`age -r OLD -r NEW`). Sunset old key after retention window.

**Warning signs:**
- No restore drill in calendar reminders
- `~/.config/age/keys.txt` exists ONLY on the encrypted volume that's being backed up
- Recovery doc says "see Vaultwarden item X" for the age private key

**Severity:** BLOCKER
**Recovery cost (if missed):** CATASTROPHIC. Permanent data loss across all encrypted backups. No technical recovery — only re-import from raw sources (Apple Health export, lab PDFs, etc.) that you may also have lost.
**Phase to address:** M1 Phase 1.7 (backup-pipeline) — first restore drill is acceptance criterion.

---

### Pitfall 4: FHIR subject reference drift across data sources

**Domain:** FHIR R4 conformance

**What goes wrong:** Apple Health ETL creates `Patient/abc-123`, Oura ETL creates `Patient/def-456`, lab PDF OCR creates `Patient/ghi-789` — all for the same human. Fasten now has 3 distinct Patient resources, each with a fragment of the data attached via `Observation.subject`. Cross-source correlation queries (D4 differentiator — the keystone feature) return empty: no observation says "this Patient" connects to "that Patient." User sees fragmented data in 3 silos = the exact problem the product was supposed to solve.

**Why it happens:** Fasten generates new resource IDs for newly POSTed resources. Each ETL writer is independent — no shared "patient identity" lookup. FHIR `Patient.identifier` is supposed to provide cross-system linkage (e.g., national ID, MRN), but ETLs forget to populate it consistently, OR Fasten doesn't dedupe on `identifier` and creates a new Patient on every POST.

**Prevention:**
1. **Tenant→Patient resolver:** before any ETL run, look up the Patient resource for `tenant_id`. If none exists, create exactly one with `Patient.identifier = [{ system: "https://health.ardan.sk/tenant", value: <tenant_id> }]`. Cache the resolved `Patient/<fasten_id>` for the duration of the ETL run, attach to every `Observation.subject`.
2. **Stored in Postgres `tenants.fasten_patient_id`** column — single source of truth. ETL workers read this column, never invent.
3. **FHIR Bundle preflight check:** `fhir.resources` (Python) zod-validate that every resource in the Bundle has `subject` populated and pointing to the same `Patient/<id>`. Fail the bundle; do NOT POST partial.
4. **Test:** `tests/fhir-subject-coherence.test.ts` — for each tenant, query Fasten for all Observations. Assert all have identical `subject.reference`. Fails if drift detected.
5. **Reference style:** **always relative** `Patient/<id>` (Fasten's local ID), not absolute `https://example.com/Patient/<id>`. Re-imports / migrations break absolute references.

**Warning signs:**
- Cross-source dashboard shows zero correlated rows even though ETLs report success
- Fasten UI shows multiple Patient cards
- `SELECT subject FROM observations GROUP BY subject` returns >1 distinct value per `tenant_id`

**Severity:** BLOCKER
**Recovery cost (if missed):** EXPENSIVE. Must reprocess all FHIR resources to remap `subject.reference`. If Fasten's API doesn't support resource updates cleanly, may require full Fasten DB rebuild. Up to 2 weeks of work + ETL reingest.
**Phase to address:** M1 Phase 1.4 (etl-foundation) — Patient resolver lands before Apple Health or Oura ETL.

---

### Pitfall 5: GDPR Art. 9 health data without explicit consent flow

**Domain:** GDPR / regulatory

**What goes wrong:** SaaS launches with a paying tenant. The signup flow has a generic "I accept Terms" checkbox. Six months later, supervisory authority (Slovak ÚOOÚ or any EU DPA) audits and finds that storing FHIR Observations of paying users does not meet Art. 9(2)(a) "explicit consent" requirement (must be specific, informed, unambiguous, **for each processing purpose**), nor does it fit Art. 9(2)(h) "preventive medicine" (you are NOT a healthcare professional under professional secrecy obligations). Fine up to 4% of revenue or €20M.

**Why it happens:** Founders treat health-data SaaS like a normal SaaS — terms-of-service checkbox covers everything. But health data is a **special category** under Art. 9 with stricter conditions. Most non-EU founders are not aware. EU AI Act + EHDS guidance also requires Art. 9(2) explicit basis to be documented in the DPIA.

**Prevention:**
1. **Two-tier consent UI** (M4 prep):
   - **Tier 1: Service consent** (Art. 6(1)(b) — contract): "to provide you the aggregator, we store your health data in your encrypted volume" — required, granular per data category (wearable / lab / DICOM / DNA).
   - **Tier 2: Optional processing** (Art. 9(2)(a) explicit): "for analytics improvement" / "for cross-source correlation displays" / etc. — opt-in checkboxes, separately revocable, with `consent_log` table audit trail.
2. **Per-category opt-in:** importing DNA data triggers a separate Art. 9 explicit consent screen distinct from importing lab PDFs (DNA = genetic data, even more sensitive subset of Art. 9). Mental health, HIV, addiction — same treatment.
3. **DPIA done before first paying tenant** (Art. 35 mandatory for "large-scale processing of special category data"). Use the EDPB DPIA template (consultation closes 2026-06-09; final later 2026 — track + apply when published). Reference: ARCHITECTURE.md A6 + FEATURES.md D5.
4. **Art. 28 processor agreement** with Hetzner (data center) and Cloudflare (tunnel processor) — both have boilerplate DPAs available; sign before launch.
5. **`consent_log` table in Postgres analytics:** every consent action (granted/withdrawn/modified) recorded with timestamp, IP, exact text version of consent shown. Subject access requests can produce audit trail.

**Warning signs:**
- M4 Phase plans don't include a DPIA milestone
- Signup flow design Figma has only "I agree to Terms" checkbox
- No `consent_log` table in schema
- No DPA agreement signed with Hetzner/CF before launch

**Severity:** BLOCKER (for SaaS) / MEDIUM (for M1 single-user — CEO is data subject + controller, fewer formal obligations)
**Recovery cost (if missed):** CATASTROPHIC at SaaS scale (fine + retrofit consent flow + force-resubmit consent for all existing users + supervisory authority dialogue).
**Phase to address:** M1 — defer the UI but **schema (`consent_log` table + per-category consent boolean on tenant)** lands in M1 with default `granted_at: 'now()'` for the single CEO tenant. M4 — DPIA, two-tier UI, DPA signing.

---

### Pitfall 6: Logger autoredact denylist (instead of allowlist) leaks PII

**Domain:** PII redaction / observability

**What goes wrong:** Default pino config redacts `password`, `token`, `email` paths. Developer logs an FHIR Observation for debugging: `logger.info({ obs })`. The Observation contains `subject.identifier`, `valueQuantity`, `effectiveDateTime`, free-text notes from a lab — none of these are on the denylist. PII Tier 1 data in JSON logs → log shipper (next phase: Loki, Grafana Cloud, etc.) → cross-tenant log search → leak.

**Why it happens:** "Redaction" is intuitively a denylist (block specific known-bad paths). But health data fields are unbounded — any FHIR resource may carry a free-text note with PHI in it. Denylist always lags reality.

**Prevention:**
1. **Allowlist pattern (per A7 ARCHITECTURE.md):**
   ```typescript
   import pino from 'pino';
   export const logger = pino({
     redact: { paths: ['*'], remove: false, censor: '[REDACTED]' },
     // Custom serializers ONLY for explicitly safe envelopes
     serializers: {
       safeOp: (obj) => ({ // ONLY this object passes through
         operation: obj.operation,
         tenant_id_hash: hmacSha256(obj.tenantId, process.env.LOG_HMAC_SALT),
         duration_ms: obj.durationMs,
         status: obj.status,
       }),
     },
   });
   // Usage:
   logger.info({ safeOp: { operation: 'oura-sync', tenantId, durationMs, status: 'ok' } });
   // Never: logger.info({ obs }) — would log [REDACTED] for every nested path.
   ```
2. **HMAC tenant_id, not raw or plain hash:** even hashes of identifiers can be deanonymized at small N. Use HMAC-SHA-256 with a rotating salt (env var, rotated quarterly). Cardinality-bounded, reversible only with the salt.
3. **No raw FHIR payload logging — ever.** Code review rule. ESLint custom rule: any `logger.{info,warn,error,debug}({ <name>: ... })` where `<name>` is not in `{safeOp, error, errorContext}` → fail.
4. **Sentry/error-tracking opt-in only** (`SENTRY_ENABLED=false` default in `.env.example`). When enabled, `beforeSend` hook scrubs `extra` payload; only allowlisted keys pass.
5. **Test:** `tests/logger-redaction.test.ts` — pass a FHIR Bundle to logger, capture stdout, assert no PII fields survive redaction.

**Warning signs:**
- `logger.info({ patient })` or `logger.info({ obs })` patterns in code review
- pino `redact` config has explicit paths instead of `paths: ['*']`
- Sentry SDK initialized without `beforeSend` hook
- Prometheus metrics with high-cardinality labels (`patient_id`, `tenant_id`)

**Severity:** BLOCKER (silent PII leak)
**Recovery cost (if missed):** EXPENSIVE — log retention rotation needed, possible Art. 33 breach notification within 72 hours, possible fine. Plus refactor of every log call site.
**Phase to address:** M1 Phase 1.5 (analytics-app) — logger module is one of the first files written, before any feature code.

---

### Pitfall 7: ETL state on disk loses watermark on container restart

**Domain:** ETL pipeline

**What goes wrong:** Oura sync ETL writes `last_synced_at` to `/srv/output/oura/last_sync.json`. Container restarts (`docker compose down && up`), volume gets wiped because it wasn't declared as a named volume → file gone. Next day's sync fetches everything Oura has back to `2020-01-01` → either rate-limited (Oura API limits), duplicate inserts on Fasten (no idempotency), or "nothing new" if dedupe is hash-based but slow → silent inconsistency. Worse: container with `tmpfs` mount → file gone on every restart.

**Why it happens:** "Files are simpler than DB tables." But files on disk are not transactional with the data they describe. If ETL crashes mid-write, the on-disk state and the DB drift. (Per A8 in ARCHITECTURE.md.)

**Prevention:**
1. **`etl_runs` table in Postgres:** every ETL run inserts a row with `started_at`, `ended_at`, `kind` (`'oura_sync'`, `'apple_health_import'`, `'lab_pdf'`, `'fasten_mirror'`), `status`, `last_observed_at` (high-water mark for idempotent resume), `failure_reason`.
2. **`etl_failures` table (DLQ):** when a single record fails (e.g., one Apple Health Record is malformed), insert into this dead-letter queue with `payload_hash`, `payload_excerpt` (first 500 chars, **redaction-safe**), `error`, `etl_run_id`. Keeps the ETL flowing for the other 99%.
3. **Idempotent ingest:** every FHIR resource POSTed to Fasten carries a stable `meta.tag.system = 'https://health.ardan.sk/etl'` + `meta.tag.code = sha256(source + natural_key + observed_at)`. Re-ingesting the same record produces identical hash → upsert, no duplicate.
4. **At-least-once delivery + idempotency** = effectively-exactly-once. Without idempotency, "at-least-once" = duplicates; "at-most-once" = data loss. **Idempotency is non-negotiable.**
5. **cron drift detection:** ETL job that hasn't run in the last 25 hours triggers an email/Discord alert (use existing personal channel or Mailcow). PC sleep → cron skipped → no alert means a silent gap.

**Warning signs:**
- ETL state files in `output/` dir instead of DB
- Volume declarations missing `last_sync` from `compose.yaml` named volumes
- No retry-with-backoff in Oura/Apple Health ETL code
- Apple Health ingest re-creates Fasten resources (visible as duplicates in Fasten UI)

**Severity:** BLOCKER (data loss + duplication)
**Recovery cost (if missed):** MODERATE — most data can be re-derived from raw sources, but FHIR resource IDs in Fasten will be different on re-ingest. Cross-source links break (see Pitfall 4).
**Phase to address:** M1 Phase 1.4 (etl-foundation) — `etl_runs` schema, idempotency hash, retry wrapper land before first ETL writes.

---

### Pitfall 8: Apple Health timezone confusion (local time stored as UTC)

**Domain:** Custom HealthKit→FHIR mapper

**What goes wrong:** Apple Health export.xml `startDate` and `endDate` are in ISO 8601 with timezone offset (`2024-03-15 06:30:00 +0100`). XML parser treats them as naive datetimes and stores as UTC → all of CEO's data is shifted by 1–2 hours (Slovakia is CET/CEST). Sleep stages display as starting "before yesterday" or wrong day. Worse: DST transitions create duplicate / overlapping observations, off-by-one-day errors.

**Why it happens:** Python `datetime` parsing without `dateutil` strips timezone info if you call `.replace(tzinfo=None)` or naively `strptime` without `%z`. FHIR `effectiveDateTime` requires ISO 8601 with offset; Postgres `timestamp without time zone` (the default) silently strips offset.

**Prevention:**
1. **Postgres column type = `TIMESTAMPTZ`** (with timezone) for every observation timestamp. Drizzle: `timestamp('observed_at', { withTimezone: true })`.
2. **Python parser: always `dateutil.parser.parse()`** (handles +01:00 / +02:00 / Z / unknown formats) → preserve `tzinfo` → convert to UTC for storage but emit FHIR with the original offset.
3. **FHIR `effectiveDateTime`** = ISO 8601 with offset, e.g. `2024-03-15T06:30:00+01:00`. Validate with `fhir.resources` zod-equivalent (`pydantic` model raises on naive datetime).
4. **DST aware:** CEO is in Bratislava (Europe/Bratislava). DST transitions in March + October. Test with a sample export covering DST week — verify no "duplicate hour" or "missing hour" observations.
5. **Display in CEO's local timezone**, not UTC, in analytics UI. Use `Intl.DateTimeFormat('sk-SK', { timeZone: 'Europe/Bratislava' })`.

**Warning signs:**
- Time-series chart shows sleep starting at 23:00 yesterday instead of 22:00 today
- Drizzle schema uses `timestamp` without `withTimezone: true`
- Python ETL has `.strftime('%Y-%m-%dT%H:%M:%S')` (no `%z`)
- No tests with DST-week sample data

**Severity:** BLOCKER (silent data corruption)
**Recovery cost (if missed):** EXPENSIVE — must reparse entire Apple Health export with correct timezone, re-POST to Fasten (creates new resource IDs → see Pitfall 4), update Postgres mirror. ~1 week of work + ETL reprocessing.
**Phase to address:** M1 Phase 1.4 (etl-foundation) — Apple Health mapper has unit tests with multi-timezone, DST-week, and Watch+iPhone-double-source samples before lab/Oura.

---

### Pitfall 9: Lab PDF OCR + LLM hallucination = silent wrong-value ingestion

**Domain:** Lab PDF OCR

**What goes wrong:** Tesseract OCRs Slovak Unilabs lab report. Multi-column layout breaks; "Glykémia" row's value gets paired with "Cholesterol" row's reference range. Ollama Qwen 2.5-VL receives the broken text + image + asks "extract values" — confidently emits structured JSON with mismatched value/reference (Qwen exhibits **higher hallucination rates than GPT-4o** in clinical decision support per medRxiv 2025-02 study). FHIR Observation gets created with `valueQuantity.value = 4.5 mmol/L` (correct glucose) but `referenceRange = { low: 3.5, high: 5.5 }` was actually for HbA1c. Custom analytics later flags "out of range" or "in range" wrong. CEO trusts the dashboard, makes a decision based on wrong data.

**Why it happens:** LLMs in vision+OCR mode have **known overconfidence** — they emit syntactically-valid structured output even when the source is garbled. The output looks identical to a correct extraction. Tesseract's Slovak diacritic recognition is documented as unreliable (tessdata Issue #130). Decimal-comma vs decimal-point mistakes (Slovak: `0,5 - 1,2` vs English: `.5 - 1.2`) confuse the LLM.

**Prevention:**
1. **Mandatory human-review queue** for every lab PDF ingest in M1. UI: side-by-side PDF + extracted FHIR fields. CEO must confirm before write to Fasten. **Auto-ingest is anti-pattern for medical data extraction in M1.**
2. **Three-pass extraction:**
   1. Tesseract extracts raw text + bounding boxes
   2. Ollama Qwen 2.5-VL extracts structured JSON
   3. **Independent regex pass** for value+unit patterns (`\d+[,\.]\d+\s*(mmol/L|mg/dL|...)`) cross-checks the LLM output. **Disagreements between LLM and regex → flag for review, never silently pick one.**
4. **Decimal-normalization step:** before feeding to FHIR, convert `0,5` → `0.5` explicitly. Document the conversion in `docs/fhir-mappings/lab-pdf.md`.
5. **Confidence threshold:** LLM emits a confidence score per field; values <0.85 always go to review queue.
6. **Per-template parser library (D1 differentiator):** for known Unilabs/Synlab/Medirex templates, write a **deterministic parser** (pdfplumber → structured rows by column-region heuristic) that is the **primary** path. Tesseract+LLM is the **fallback** for unknown templates. Per-template is more reliable than per-PDF generic OCR.
7. **Reference range source = lab PDF itself**, never derived. If ref range can't be parsed reliably, leave `referenceRange` unset rather than fabricate.
8. **PDF format-drift detector:** hash key layout regions (header, column headers); when a new lab PDF doesn't match any known template hash, send to manual queue with template-author task.

**Warning signs:**
- Auto-ingest pipeline in M1 architecture diagram (NO — must be review-queue based)
- Tests pass on clean printer-output PDFs but no test with scanned-by-phone PDF
- `referenceRange` populated for >50% of observations without a source PDF link
- CEO reports a value he knows to be wrong but the dashboard says it's right

**Severity:** BLOCKER (wrong medical data → wrong personal decision; SaaS = liability for clinic users)
**Recovery cost (if missed):** EXPENSIVE — must audit every lab observation against original PDF, mark suspect rows in Fasten with custom extension, reprocess. Plus loss of trust in dashboard — CEO may abandon product.
**Phase to address:** M1 Phase 1.6 (lab-ocr) — review-queue UI + per-template parser as **primary** path; LLM is **fallback only**.

---

### Pitfall 10: Wrong terminology code (LOINC/SNOMED/ICD-10/ATC mix-up)

**Domain:** FHIR R4 conformance

**What goes wrong:** Apple Health "blood glucose" maps to LOINC `15074-8` (Glucose [Moles/volume] in Blood) but ETL writer used `2345-7` (Glucose [Mass/volume] in Serum or Plasma) — different specimen, different unit. Cross-source correlation joins on `loinc_code` → glucose readings from Apple Health and lab PDF appear as different metrics, no chart correlation. Worse: SNOMED used for diagnoses but Slovak provider uses ICD-10 (MKCh-10) → "Diabetes Mellitus Type 2" stored as ICD-10 `E11` in one place and SNOMED `44054006` in another → analytics views miss data.

**Why it happens:**
- Creatinine alone has 10+ LOINC codes (serum vs urine; mass/volume vs moles/volume; 24-hr vs 4-hr collection — see [LOINC search results](https://loinc.org/2161-8) vs [LOINC 14683-7](https://loinc.org/14683-7)). One developer hour reading the wrong table makes silent errors.
- LOINC vs SNOMED CT vs ICD-10 vs ATC vs RxNorm — each has overlapping but **non-equivalent** vocabularies. RxNorm is US-only; EU uses ATC for medications.
- SNOMED CT requires per-country license for production use — FREE for personal/eval, but may not be free for SaaS in some EU countries. Already flagged in FEATURES.md.

**Prevention:**
1. **Single mapping table in Postgres** `code_mappings(internal_concept, target_system, target_code, target_display, valid_from, valid_to)`. ETLs ONLY write codes from this table. Reviewable, versionable, testable.
2. **Per-source curated mapping files** (committed to repo): `mappings/apple_health_to_loinc.yaml`, `mappings/oura_to_loinc.yaml`, `mappings/unilabs_to_loinc.yaml`. Code review every entry.
3. **Domain rule (FEATURES.md):** LOINC for observations, SNOMED for diagnoses (eval-license M1, productize in M4), ICD-10/MKCh-10 for billing/diagnoses, ATC for medications. **NEVER RxNorm in EU.**
4. **Unit consistency:** every LOINC code defines an expected unit. Validate at FHIR write time: if `code = 15074-8` then `valueQuantity.unit = mmol/L` else fail. Use UCUM library.
5. **Test:** for each top-50 lab observation, integration test that queries Postgres for cross-source data and asserts exactly one normalized concept.

**Warning signs:**
- ETL code has hardcoded LOINC strings
- No `code_mappings` table or YAML mapping files
- Cross-source dashboard query joins on `display_name` (text) instead of `loinc_code` (code)
- Lab values appear in different units (`mmol/L` and `mg/dL`) for same metric

**Severity:** BLOCKER (silent data quality corruption — analytics views wrong)
**Recovery cost (if missed):** MODERATE — re-derive codes from mappings table, re-mirror Postgres analytics. Fasten resources may need updates.
**Phase to address:** M1 Phase 1.4 (etl-foundation) — `code_mappings` table + YAML files + unit-validation function land before any ETL writes.

---

### Pitfall 11: Unit conversion silently wrong (mmol/L vs mg/dL)

**Domain:** FHIR R4 conformance + custom mapper

**What goes wrong:** Glucose in Slovakia/EU = `mmol/L`; in USA = `mg/dL`. Conversion factor is 18 (1 mmol/L glucose = 18 mg/dL). ETL ingests Apple Health (Apple lets users pick units in Settings) — sometimes mg/dL, sometimes mmol/L. ETL stores `valueQuantity.value` without `valueQuantity.unit` or with wrong unit. Dashboard displays `5.5` for one source (should be 5.5 mmol/L = 99 mg/dL — normal) and `99` for another (should be 99 mg/dL = 5.5 mmol/L — normal, but appears as 99 mmol/L = severely hyperglycemic). User panics or gets falsely reassured. Same for blood pressure (mmHg vs kPa), weight (kg vs lb), temperature (°C vs °F), HRV (ms vs bpm-derived).

**Why it happens:**
- Apple Health stores in user's preferred display unit. Export.xml `unit` attribute is reliable but ETLs sometimes ignore it.
- Lab PDFs vary by lab — most Slovak labs use SI (mmol/L), some old templates US-style.
- FHIR `valueQuantity.unit` is a free-text "human" string; `valueQuantity.code` is UCUM. ETLs forget UCUM.

**Prevention:**
1. **Always emit `valueQuantity.code` (UCUM)** in addition to `valueQuantity.unit` (display). Reference UCUM table.
2. **Normalize-on-ingest, store canonical unit, display in user preference:**
   - Decide the **canonical unit per LOINC** (e.g., glucose → `mmol/L`, blood pressure → `mmHg`, weight → `kg`, temperature → `°C`).
   - Convert at ETL time using `pint` (Python) or hard-coded factors.
   - Store both raw value (`value_raw`, `unit_raw`) and canonical (`value_canonical`, `unit_canonical`) in Postgres mirror — auditability.
3. **Conversion table tested:** `tests/unit-conversion.test.ts` — for each mapped LOINC, test `(input_value, input_unit) → expected_canonical_value`. Catches off-by-factor-of-10 errors that "look reasonable."
4. **UI displays canonical with "convert to" toggle.** Slovak users want mmol/L; US users mg/dL.
5. **Reference ranges matched to canonical unit** — never mix.

**Warning signs:**
- `valueQuantity.code` (UCUM) absent in any FHIR resource
- Same LOINC code has different `unit` strings across observations
- Dashboard shows two values for "glucose" with order-of-magnitude difference

**Severity:** BLOCKER (silent data corruption + clinical decision implications)
**Recovery cost (if missed):** MODERATE — reprocess observations, re-derive canonical values. Auditability of `value_raw` saves the day.
**Phase to address:** M1 Phase 1.4 (etl-foundation) — UCUM + conversion library + canonical units land in Apple Health mapper.

---

### Pitfall 12: GPL-3.0 + per-tenant SaaS = unclear copyleft obligation

**Domain:** SaaS pivot forward-looking

**What goes wrong:** Fasten OnPrem is **GPL-3.0** (verified per STACK.md gh api lookup). Plain GPL-3.0 has the "SaaS loophole" — running modified GPL software for users over a network is **NOT** distribution → no obligation to release modifications. **BUT:** if M4 SaaS includes "modifications" (forks of Fasten with patches, custom plugins compiled in, modified Docker images that aren't pure rebuilds), the legal interpretation gets fuzzy. Worse if Fasten upstream relicenses to AGPL (under their right as copyright holder) — at that point any modification becomes mandatorily-redistributable to network users. SaaS launches → discovers fork or patch can't be kept private → competitor snapshots source on Day 1 → moat dissolves.

**Why it happens:**
- GPL-3.0 vs AGPL-3.0 distinction is poorly understood. "GPL = free if I share = SaaS is fine" oversimplification.
- Fasten v1.1.3 stable is 19+ months old (per STACK.md); pinning to `:main` digest = more recent code, but main may include AGPL contributions or relicense PRs we miss.
- "Per-tenant Fasten container" = upstream Fasten image + our orchestration → orchestration is OK (separate codebase), but if we patch Fasten image (e.g., custom auth, custom branding, custom routes), patches become "modifications."

**Prevention:**
1. **M4 prep: lawyer-grade license review** before first paying tenant. Specifically:
   - Does our deployment ship modified Fasten? (If pure upstream binary in our Docker compose: NO modifications — clean.)
   - Is Fasten still GPL-3.0 at launch time? (Re-verify monthly with `gh api repos/fastenhealth/fasten-onprem` LICENSE.)
   - Are any plugins/forks running in-process with Fasten? (Should be NO — all custom code in separate Next.js / Python ETL containers.)
2. **Architectural firewall:** Custom analytics + ETL = separate processes communicating with Fasten via HTTP only. No shared address space, no compiled-in patches. **Custom code = our license to choose** (we recommend AGPL-3.0 for the custom analytics layer to deter SaaS competitors who'd just lift our code).
3. **Pin to upstream Docker image, never fork.** If a Fasten bug needs fixing, file upstream PR; if blocked, document workaround in custom layer (proxy, header injection at Traefik) rather than forking.
4. **Track upstream license file in CI** — fail build if `LICENSE` text changes from known GPL-3.0 hash.
5. **Custom layer license:** AGPL-3.0 (matches Fasten's spirit + closes ASP loophole for our IP). Or proprietary EULA + commercial license offer (more restrictive). Decide before M4.

**Warning signs:**
- M4 plans include patching Fasten or building custom plugin in same process
- License-of-our-custom-code is "TBD" by M4 start
- No periodic upstream LICENSE check in CI
- M5 launch without lawyer review

**Severity:** BLOCKER for SaaS (legal exposure)
**Recovery cost (if missed):** EXPENSIVE — license audit, possibly forced source release, possibly product re-architecture (extract from Fasten, build own). Worst case: brand damage if FSF/upstream calls foul.
**Phase to address:** M4 Phase prep. Architectural decision in M1 (firewall pattern) prevents the trap from emerging.

---

## High Pitfalls (HIGH severity)

### Pitfall 13: Fasten unpinned `:main` tag silently breaks compose

**Domain:** Fasten-specific

**What goes wrong:** `image: ghcr.io/fastenhealth/fasten-onprem:main` resolves to whatever the latest commit is at pull time. CEO `docker compose pull` 6 months later → new Fasten version with breaking schema migration runs against existing SQLite → DB corrupted or features broken. Or a regression PR shipped to main → silently rolls back functionality. Worse: re-deploy to new machine pulls a different image than dev → "works on my machine" disasters.

**Why it happens:** Floating tags are convenient. Fasten upstream has no proper SemVer release since v1.1.3 (Oct 2024 per STACK.md) — pinning to v1.1.3 means missing 19+ months of fixes. Trade-off ignored.

**Prevention:** **Always pin to digest** `image: ghcr.io/fastenhealth/fasten-onprem:main@sha256:<exact-digest>`. CI test: `compose.yaml` greps for `:main` without `@sha256:` → fail. Quarterly upgrade ritual: pull latest main, run `tests/migration.test.ts` (loads old SQLite + runs Fasten migrate + verifies queries), then update digest if green.

**Phase:** M1 Phase 1.1 (infra-skeleton). Per STACK.md §Recommended Stack.
**Severity:** HIGH (silent breakage)
**Recovery cost:** MODERATE (rollback to known-good digest, possibly DB restore if migration was destructive).

---

### Pitfall 14: SQLite single-writer contention (per-tenant Fasten under concurrent ETL)

**Domain:** Fasten-specific

**What goes wrong:** SQLite WAL allows concurrent reads but **only one writer**. Fasten's writer is its own process. ETL POSTs FHIR Bundle → Fasten ingest writes → blocks. Apple Health import + Oura cron + lab PDF batch all run at 06:00 → first one wins, others get `database is locked` errors with default 5-second timeout → ETL retries → lock contention spiral. Per-tenant containers in M4 each have their own SQLite — same problem per-tenant.

**Why it happens:** SQLite is "good enough" for single-writer workloads. ETLs are designed as parallel cron jobs because that's the easy pattern. WAL mode doesn't save concurrent writes — only readers — see [SQLite WAL docs](https://www.sqlite.org/wal.html). Default `busy_timeout` is too low.

**Prevention:**
1. **Serialize ETL writes per Fasten instance.** cron + flock pattern (already in stack — STACK.md §Compose) ensures only one ETL job runs at a time per tenant. If parallelism needed in M4, queue (BullMQ/Redis) per-tenant FIFO.
2. **Don't try concurrent writes.** Apple Health + Oura + lab PDF stagger by 5 minutes in cron schedule, not 1 second.
3. **Set Fasten SQLite `busy_timeout` to 30s** if Fasten exposes the env var; otherwise document the limitation and stagger.
4. **WAL checkpoint cron** to prevent unbounded WAL growth (per [SQLite WAL renaissance article](https://dev.to/pockit_tools/the-sqlite-renaissance-why-the-worlds-most-deployed-database-is-taking-over-production-in-2026-3jcc)).
5. **M4 scaling:** if a tenant outgrows single-writer SQLite (rare — health data ingest is low-volume per tenant), consider per-tenant Postgres (separate from shared analytics DB) — but this is M5+ concern, not M4 blocker.

**Phase:** M1 Phase 1.4 (etl-foundation). Cron schedule + flock = M1.
**Severity:** HIGH (ETL failures, partial data, retry storms)
**Recovery cost:** CHEAP (cron schedule edit + busy_timeout config).

---

### Pitfall 15: Fasten ingest API undocumented — wrong assumption breaks plan

**Domain:** Fasten-specific + ETL pipeline

**What goes wrong:** ARCHITECTURE.md A2 assumes "ETLs POST FHIR Bundles to Fasten first." Fasten OnPrem README says "**not able to import data from healthcare providers directly. You can only use this application to manually enter data, or upload FHIR Bundles that have been exported through other means**" — implies UI-only upload, no programmatic POST. Plan locks in M1 Phase 1.4 ETL architecture before verifying. Discovered late = ETLs must drop FHIR JSON files into a Fasten-watched volume, OR write directly to Fasten's SQLite (skipping its validation), OR scrape Fasten's UI upload form (brittle).

**Why it happens:** Plan written from FEATURES.md without confirming with a 1-day spike. Fasten has SOME API (its UI uses it) but it's not documented for external consumers; auth / endpoint surface is opaque without reading source.

**Prevention:**
1. **2-day Phase 1.0 spike (BEFORE M1 Phase 1.4):** identify exact Fasten ingest mechanism. Acceptance criteria: a Python script that POSTs a 1-resource FHIR Bundle and sees it appear in Fasten UI. Fall-back: drop JSON in a watched volume directory.
2. **Document spike result in `docs/fasten-admin.md`** — endpoint URL, auth header, expected response. This becomes the contract for ETL writers.
3. **If no programmatic API exists:** plan adjusts — ETL writes raw FHIR JSON to `/srv/fasten-import/` (volume mount), Fasten cron picks it up. OR direct SQLite write (skips Fasten validation but bypasses auth — risky for SaaS multi-tenant).
4. **Already flagged in ARCHITECTURE.md A2 (MEDIUM-HIGH confidence).** Make it Phase 1.0 acceptance criterion.

**Phase:** M1 Phase 1.0 (spike, before plan lock).
**Severity:** HIGH (architecture rebuild if missed)
**Recovery cost:** MODERATE (1-week ETL refactor; CHEAP if spike done early).

---

### Pitfall 16: `pgcrypto` column key in environment variable visible via `docker inspect`

**Domain:** Encryption / key management

**What goes wrong:** `pgcrypto` column-level encryption is added for `freetext_notes`, `provider_name`, `dna_findings.text` (per A6). The `pgp_sym_encrypt(value, key)` calls take a passphrase from environment variable. **`docker inspect health-postgres`** anyone with Docker socket access (or root on host) sees the env var → key compromised → all column-encrypted data plain.

**Why it happens:** Environment variables are the easy pattern for Docker secrets. They're listed in `docker inspect`, `/proc/<pid>/environ`, container restart logs, error messages. Compose `secrets:` block exists but is ignored ("env vars are easier").

**Prevention:**
1. **Use Compose `secrets:` block** — mounts as file in `/run/secrets/`, not env var. Postgres init script reads file, sets passphrase via `SET LOCAL pgcrypto.key = pg_read_file(...)`.
2. **Function-scoped passphrase:** wrap encrypt/decrypt in a Postgres function that takes the key from a session variable set at connection time (similar to RLS pattern — `SET LOCAL app.crypto_key`).
3. **LUKS = primary, pgcrypto = defense-in-depth.** A6 is explicit: pgcrypto for select sensitive columns ONLY, not the whole DB. If LUKS holds, pgcrypto column encryption is belt-and-suspenders.
4. **Vaultwarden manages the pgcrypto passphrase** (M2+ via bw sidecar). Rotation = re-encrypt affected columns + update Vaultwarden item.
5. **Never log the passphrase.** Logger redaction allowlist (Pitfall 6) handles this.

**Phase:** M1 Phase 1.2 (postgres-rls). Defer pgcrypto to M2 if too much for M1 scope.
**Severity:** HIGH (defense-in-depth defeated)
**Recovery cost:** MODERATE (rotate keys, re-encrypt affected columns).

---

### Pitfall 17: Backup pipeline writes plaintext "for convenience"

**Domain:** Encryption / key management

**What goes wrong:** Backup script does `pg_dump > /tmp/dump.sql && age -r ... < /tmp/dump.sql > /backups/...age && rm /tmp/dump.sql`. The plaintext file in `/tmp` is on the same volume as the encrypted backup target, persists during the encryption run, may be picked up by other backup tools (host-level Time Machine, OneDrive, Syncthing) that don't honor `/tmp` exclusions. Worse: ETL "convenience" dumps decrypted FHIR resources to `output/etl/` for "debugging" without redaction → PII Tier 1 in plaintext on disk forever.

**Why it happens:** Streaming pipelines are harder to debug. "I'll just dump it temporarily" → temp becomes permanent.

**Prevention:**
1. **Pipe-only encryption:** `pg_dump | age -r RECIPIENT > /backups/...age`. No intermediate plaintext file ever exists on disk.
2. **`/tmp` mounted as `tmpfs` (RAM-only)** in compose for ETL container — guarantees nothing persists across restarts even if devs make a mistake.
3. **Audit `output/` for unencrypted health data:** CI grep for `*.json` containing FHIR-shaped keys (`resourceType`, `valueQuantity`) outside `tests/fixtures/`.
4. **`.gitignore` strict pattern** (already in CLAUDE.md): `*.pdf`, `*.dcm`, `data/`, `output/`, `secrets/`. Add `*.sql.dump`, `*.json.raw`, `pg_dump_*`.
5. **Restore drill verifies encrypted-only** — if restore from encrypted backup succeeds AND there are no plaintext intermediate files left behind → pass.

**Phase:** M1 Phase 1.7 (backup-pipeline).
**Severity:** HIGH (PII Tier 1 leak path)
**Recovery cost:** MODERATE (file cleanup, audit, possible breach notification depending on access surface).

---

### Pitfall 18: Per-tenant Fasten container resource exhaustion (noisy neighbor)

**Domain:** SaaS pivot forward-looking

**What goes wrong:** Hetzner CX22 (4GB RAM, 2 vCPU) hosts 30 tenant Fasten containers per FEATURES.md estimate. One tenant uploads a giant Apple Health export.zip (200MB → 2GB unzipped → Fasten import process spikes RAM). OOM killer terminates **another tenant's** Fasten process. Other tenants see "service unavailable" — Art. 32 GDPR availability obligation breached.

**Why it happens:** No per-container resource limits set. Estimate of 30-50 tenants/CX22 is FEATURES.md back-of-envelope, not benchmarked. SQLite import on Fasten is unbounded memory.

**Prevention:**
1. **Per-tenant `mem_limit` + `cpus` in compose:**
   ```yaml
   fasten-tenant1:
     mem_limit: 256m
     mem_reservation: 128m
     cpus: 0.5
   ```
2. **Per-tenant import quotas:** chunked Apple Health import (split XML by year) to bound peak RAM.
3. **Monitoring alerts:** Prometheus container metrics + alert if any tenant exceeds 80% mem_limit, OR if total host RAM utilization >85%.
4. **Benchmarked tenant capacity** in M4 dev, not FEATURES.md guess. Real number could be 10/CX22 if usage skews active.
5. **Vertical scale path:** Hetzner CCX23 (16GB RAM) or CCX33 (32GB) is 1-day migration; prepay 12mo for discount. M5 — when paying tenant count justifies €15-30/mo.

**Phase:** M4 Phase prep. Architectural — set the limits even in M1 dev (1 tenant) so the pattern is proven.
**Severity:** HIGH at SaaS scale
**Recovery cost:** MODERATE (config + benchmark + scale up).

---

### Pitfall 19: Data Processor agreement (Art. 28 GDPR) missing for Hetzner / Cloudflare

**Domain:** GDPR / regulatory

**What goes wrong:** SaaS launches with paying tenant. Hetzner is the data center (data processor) — without a signed DPA per Art. 28, the legal basis for storing health data on Hetzner is broken. CF Tunnel is also a processor (sees encrypted traffic + metadata). Auditor flags: "controller (you) has no Art. 28 contract with processors." Fine.

**Why it happens:** "We just rent a VM, what's the contract?" — but Art. 28 mandates a written contract with binding clauses (subject matter, duration, nature/purpose, data category, controller obligations, etc.). Boilerplate exists; not signing it = compliance gap.

**Prevention:**
1. **Hetzner DPA**: download from `hetzner.com/legal/data-processing-agreement`. Sign electronically. Store in `docs/compliance/`.
2. **Cloudflare DPA**: download from CF dashboard. Sign electronically.
3. **Track all processors in `docs/compliance/processors.md`**: name, role, data categories, DPA file path, signed date.
4. **Annual review:** processors list reviewed each January; new processors trigger new DPA.
5. **No US-only processors** for EU tenants without Standard Contractual Clauses (SCCs) post-Schrems II. Hetzner = DE = safe. CF = US-headquartered → must use SCCs (CF provides them in their DPA).

**Phase:** M4 prep — before first paying tenant.
**Severity:** HIGH (regulatory)
**Recovery cost:** CHEAP (sign existing boilerplate); potentially EXPENSIVE if missed for years (back-fines).

---

### Pitfall 20: Apple Health double-source (iPhone + Watch) creates duplicate observations

**Domain:** Custom HealthKit→FHIR mapper

**What goes wrong:** iPhone Health app records steps from both phone + watch + 3rd-party apps. Same step is counted by `<Source>iPhone</Source>` and `<Source>Apple Watch</Source>` and `<Source>Strava</Source>`. ETL ingests all three → daily step total in dashboard shows 3× actual. Or de-dupe is too aggressive → loses Watch's continuous HRV data.

**Why it happens:** HealthKit aggregates by `HKQuantityType` across sources for display, but raw `<Record>` in export.xml is per-source per-sample. Naive ETL maps each record to a separate FHIR Observation.

**Prevention:**
1. **Source-aware deduplication:** preserve `Observation.device` (which device/app produced the reading). For aggregate metrics (steps, distance), pick canonical source per day (priority: Watch > iPhone > 3rd-party). For continuous metrics (HR, HRV, ECG), retain all sources but tag.
2. **Granularity preservation:** per [TDDA Apple Health analysis](https://www.tdda.info/in-defence-of-xml-exporting-and-analysing-apple-health-data), Apple changed sampling style mid-life — pre-2019 = aggregated batches, post-2020 = per-second samples. Test mapper across full export history.
3. **`Observation.effectivePeriod`** for aggregates (start/end), `effectiveDateTime` for samples. Don't conflate.
4. **Test:** `tests/apple-health-dedup.test.ts` — 100 records of mixed sources, assert daily totals = manual hand-calculated truth.

**Phase:** M1 Phase 1.4 (etl-foundation).
**Severity:** HIGH (data quality — 3× wrong steps undermines trust)
**Recovery cost:** MODERATE (re-derive from raw export, re-mirror).

---

### Pitfall 21: PDF format drift — lab updates template, OCR pipeline silently breaks

**Domain:** Lab PDF OCR

**What goes wrong:** Unilabs lab redesigns its PDF template (new logo, columns shifted). Per-template parser (D1) keys off pixel coordinates or column headers in Slovak language → silently produces empty / wrong rows → ETL succeeds (no error) → analytics shows "no new lab data this month" or wrong values. CEO doesn't notice for 3 months.

**Why it happens:** Per-template parsers are brittle by design. No drift detection. No "expected fields" assertion.

**Prevention:**
1. **Template fingerprint hash:** parse PDF → hash key layout regions (header position, column names, footer) → compare against known-template hashes. Mismatch → flag for manual template authoring.
2. **Required-fields assertion:** every parsed lab report must extract ≥3 known LOINCs (e.g., creatinine + glucose + cholesterol). Zero-fields extracted → ETL flags as failed parse, sends to manual review queue.
3. **Drift alert:** weekly cron checks "have we received any lab PDFs in last 7 days from each known lab" — silence is itself a signal.
4. **Health-check observation count:** dashboard widget "labs ingested per month" — visible drop = action.
5. **Template author task:** detected new template → prompt user (CEO in M1, support team in SaaS) with side-by-side new+old PDF for manual annotation → new template added to library.

**Phase:** M1 Phase 1.6 (lab-ocr). Drift detection = M2 hardening.
**Severity:** HIGH (silent data gap)
**Recovery cost:** MODERATE (re-OCR with updated template).

---

### Pitfall 22: Right-to-erasure (Art. 17) incomplete due to soft delete

**Domain:** GDPR / regulatory

**What goes wrong:** Tenant requests deletion. App marks `deleted_at = now()` in `tenants` row + cascades to children. Health data is "hidden" in queries but still on disk. **Art. 17 = erasure, not hiding.** Backups still contain data; per-tenant Fasten container still has SQLite on volume; Postgres rows soft-deleted but pgcrypto-encrypted columns recoverable. Auditor finds plaintext data 2 years post-erasure → fine. Tenant sues (right of action under GDPR).

**Why it happens:** "Soft delete" is an industry pattern for revertible UX. Conflicts with GDPR Art. 17 which mandates **actual erasure** (with limited public-health exceptions per Art. 9(2)(h) — does NOT apply to a private aggregator).

**Prevention:**
1. **Hard erasure pipeline (per-tenant Fasten makes this clean):**
   - Stop tenant's Fasten container → `docker compose stop fasten-tenantN`
   - Securely wipe tenant volume (`age` archive of metadata only for compliance audit, then `shred` + `cryptsetup luksErase` on the volume key)
   - `DELETE FROM observations WHERE tenant_id = X` cascades through analytics tables
   - `DELETE FROM tenants WHERE id = X`
   - Mark backups as containing-erased-tenant; on next backup rotation, old backups age out per retention policy (document retention max in DPIA, e.g., 30 days for incremental, 1 year for monthly)
   - Issue compliance certificate to tenant with timestamp + scope
2. **Backup retention is CRITICAL:** if backup retention is 7 years (banking pattern), erasure can't complete within 7 years → not Art. 17 compliant. Health-data backup retention should be 90 days max for PII Tier 1.
3. **Tenant data export (Art. 20 portability) BEFORE erasure** — give tenant FHIR Bundle ZIP of all their data. Implement before allowing erasure.
4. **`erasure_log` table:** every erasure recorded (tenant_id_hash, timestamp, scope, certificate hash) — auditable but contains no PII.
5. **Test:** `tests/gdpr-erasure.test.ts` — provision tenant, populate data, request erasure, verify zero rows + zero files left.

**Phase:** M4 prep — full erasure pipeline before first paying tenant. M1 — schema with `tenant_id` makes the cascade trivial.
**Severity:** HIGH (regulatory + civil action)
**Recovery cost:** EXPENSIVE (architectural retrofit if soft-delete only).

---

### Pitfall 23: Sentry / error tracker auto-captures payload = leaks PII

**Domain:** PII redaction / observability

**What goes wrong:** Sentry SDK initialized with default config. An ETL exception happens during Apple Health ingest → Sentry auto-captures `local_variables` in the stack trace → captures the entire FHIR Bundle that was being processed → sent to Sentry SaaS → PII Tier 1 leaves machine boundary, hits Sentry US region (default), auditor finds.

**Why it happens:** "We just want errors monitored" → Sentry default is to be helpful + capture context → context = PII.

**Prevention:**
1. **Sentry off by default in M1.** `SENTRY_ENABLED=false` in `.env.example`. Use pino logs + Postgres `etl_failures` table.
2. **If enabled in M2+:**
   - `sendDefaultPii: false`
   - `beforeSend(event)`: scrub `event.exception.values[].stacktrace.frames[].vars` — drop entirely
   - Use **Sentry self-hosted** (in EU region, your own infra) — never Sentry SaaS US.
   - Allowlist-only `extra` data (matches logger pattern Pitfall 6).
3. **ESLint custom rule:** flag `Sentry.captureException(error, { extra: ... })` calls that pass non-allowlisted `extra` keys.
4. **Test:** `tests/sentry-redaction.test.ts` — trigger an exception with PII in stack frame, intercept the Sentry payload, assert no FHIR-shaped data.

**Phase:** M1 — disabled. M2+ if enabled, must follow rules.
**Severity:** HIGH (PII leak vector)
**Recovery cost:** MODERATE (purge Sentry events, re-engineer redaction).

---

### Pitfall 24: Cron drift — PC sleeps, daily sync skipped, no alert

**Domain:** ETL pipeline

**What goes wrong:** M1 host = local PC. PC sleeps overnight. Cron job at 06:00 doesn't run. Next ETL run looks for "since last_observed_at" — gets 2 days of Oura data the next day. If Oura API rate-limits the catchup → partial data → silent gap. CEO sees "this week's HRV chart" as missing 1 day. No alert.

**Why it happens:** Local-PC hosts don't have systemd timers / persistent cron. Windows Task Scheduler + sleep = unreliable. Docker Desktop pauses on host sleep.

**Prevention:**
1. **Heartbeat ETL:** every ETL run inserts `etl_runs` row. Dashboard widget: "minutes since last successful Oura sync" — visible.
2. **Stale-run detection:** Postgres function (or Next.js cron-API) checks every 4 hours: if any ETL hasn't run in 25h × normal interval, send Discord/email alert.
3. **Catch-up logic:** ETL fetches data with `since = max(last_observed_at, now - 7days)` and rate-limit-aware backoff. Don't fetch all-of-history.
4. **Move to Hetzner sooner if reliability matters** (M3+ target if M1 cron pain real).
5. **Alternative: external cron** (Hetzner $5/mo VM running just cron-trigger that POSTs to local PC's Cloudflared tunnel). Keeps M1 local but reliability = cloud.

**Phase:** M1 Phase 1.4 (etl-foundation).
**Severity:** HIGH (silent data gap)
**Recovery cost:** CHEAP (catch-up next run); MODERATE if Oura rolls retention policy.

---

### Pitfall 25: tenant_id hashing in metrics labels deanonymizable

**Domain:** PII redaction / observability

**What goes wrong:** Prometheus metrics need labels for slicing — but `tenant_id=abc-123` is high-cardinality + PII. Developer hashes: `tenant_id_hash = sha256(tenantId)`. With small N (initial 10-50 tenants), rainbow-table the hashes → reverse to tenant UUID → cross-reference with public sign-up timestamps → identify tenant. Same problem in error logs.

**Why it happens:** "Hash = anonymous" common misconception. With known small cardinality, hashes are reversible.

**Prevention:**
1. **HMAC with rotating salt:** `HMAC-SHA-256(tenantId, secret_salt_rotated_quarterly)`. Salt = env var, not in repo, rotated by ops with re-write of historical metrics labels.
2. **Cardinality limits on Prometheus labels:** never `{tenant_id=...}` directly; use `{tenant_tier=basic|pro|enterprise}` or aggregate counters per-instance.
3. **Per-tenant logs in tenant-specific log streams** (M4) — don't mix tenants in one log file at all.
4. **Audit log uses HMAC tenant_id_hash only.**

**Phase:** M2+ (when monitoring is added). Architectural M1.
**Severity:** HIGH at M4+ scale
**Recovery cost:** MODERATE (rotate salt + re-derive historical hashes — possible but tedious).

---

## Medium Pitfalls (MEDIUM severity)

### Pitfall 26: Reference range parsing comma-vs-period decimal confusion

**Domain:** Lab PDF OCR + custom mapper

**What goes wrong:** Slovak labs format reference range as `0,5 - 1,2 mmol/L`. Naive parser treats comma as thousand-separator → reads as `5` and `12`. Or vice versa with English-formatted ranges. Display shows "out of range" for in-range values.

**Prevention:** locale-aware parsing in OCR step (Pitfall 9 prevention #4 already covers). Test: `tests/decimal-comma.test.ts` with both Slovak and English range strings.
**Phase:** M1 Phase 1.6.
**Severity:** MEDIUM
**Recovery cost:** CHEAP.

---

### Pitfall 27: SNOMED CT license trap for SaaS in some EU countries

**Domain:** GDPR / regulatory + FHIR

**What goes wrong:** SNOMED is free for personal/eval use. Production/SaaS use requires a national license — Slovakia status unclear (per FEATURES.md). Launch SaaS without license → cease-and-desist from IHTSDO.

**Prevention:** verify SK national license before M4. If unavailable: stick to ICD-10/MKCh-10 (public) for diagnoses. ICD-10 is sufficient for analytics; SNOMED's richer hierarchy is nice-to-have.
**Phase:** M4 prep.
**Severity:** MEDIUM (license cost or scope cut).
**Recovery cost:** MODERATE (replace SNOMED codes with ICD-10 in mappings).

---

### Pitfall 28: DICOM PHI in headers leaks on share/export

**Domain:** Custom mapper (M2)

**What goes wrong:** DICOM files (RTG, MR) carry **patient name, DOB, MRN, hospital name, doctor name** in metadata headers. Share with another doctor for second opinion → entire study context leaks (more than the image). Worse: SaaS tenant exports "for backup" → headers contain provenance details about another country's hospital.

**Prevention:** dcm anonymization tooling at import (`gdcm` / `pydicom` strip-PHI tags) before storage. Original-PHI version stored in air-gapped offline archive only. SaaS export = anonymized version.
**Phase:** M2 (DICOM viewer).
**Severity:** MEDIUM (PII leak vector when sharing).
**Recovery cost:** CHEAP if pipeline correct; MODERATE if shared and recipient kept copies.

---

### Pitfall 29: Drizzle migration vs `push` in production (lost data)

**Domain:** Multi-tenant RLS + dev-prod

**What goes wrong:** `drizzle-kit push` is dev-only convenience — applies schema directly without migration files. Used in production accidentally → drops columns, recreates tables → data loss. Especially dangerous with RLS policies (drop-recreate may lose policies).

**Prevention:**
1. CI test: production deploy = `drizzle-kit migrate` (not `push`).
2. Migration review: every PR with schema change must include corresponding `drizzle/` SQL file. CI grep for `drizzle-kit push` in non-dev paths.
3. **Always backup before migrate** — wrap deploy in `pg_dump → age → upload → migrate`.
**Phase:** M1 Phase 1.2.
**Severity:** MEDIUM (data loss in dev; HIGH if pushed to prod).
**Recovery cost:** EXPENSIVE if prod data lost; MODERATE with backup.

---

### Pitfall 30: Authentik / Authelia SSO accidentally couples tenants

**Domain:** SaaS pivot forward-looking

**What goes wrong:** SSO layer M4. Tenant A admin logs in → SSO issues JWT with `tenant_id` claim → analytics layer sets `app.current_tenant`. But Authentik admin sees ALL tenants' user accounts, group memberships, audit log, with their email addresses. SSO admin = de facto God account across tenants. Insider risk + breach blast radius = entire platform.

**Prevention:**
1. **Per-tenant Authentik realm** OR Authentik with strict ACL: tenant admins manage own users, never see other tenants. Verify this in M4 setup.
2. **Audit access logs of SSO admin role.**
3. **2FA + hardware key for SSO admin.**
4. Consider per-tenant minimal auth (each Fasten container its own auth) without SSO for first SaaS launches — defer SSO to M5.
**Phase:** M4 prep.
**Severity:** MEDIUM-HIGH (insider/breach blast radius).
**Recovery cost:** MODERATE (rebuild SSO config).

---

### Pitfall 31: Analytics queries bypass RLS via direct DB connection

**Domain:** Multi-tenant RLS

**What goes wrong:** Analytics views need cross-tenant aggregations ("90th percentile cholesterol across all tenants" for a benchmark feature). Developer creates a `BYPASSRLS`-enabled role for the analytics job → connects → runs aggregation. **Logs show no individual tenant access**; per-tenant audit shows no read. Analytics output is anonymized aggregate, but the query path skipped RLS = no audit trail of what was read.

**Prevention:**
1. **No `BYPASSRLS` roles in production.** Every query goes through RLS even for aggregates.
2. **Aggregates via tenant-iteration**: for each tenant, run the aggregation, accumulate. Slower but auditable.
3. **OR materialized view with explicit policy:** `CREATE POLICY agg_view ON benchmarks FOR SELECT TO any_tenant USING (true);` — view is intentionally cross-tenant, read-only, no row-level data.
4. **`audit_log` writes for every analytics aggregation run** — even if RLS bypassed by design (matview), the bypass is logged.
**Phase:** M4 (when cross-tenant analytics arrives).
**Severity:** MEDIUM (audit gap, GDPR Art. 32 evidence weak).
**Recovery cost:** MODERATE.

---

### Pitfall 32: Fasten log output contains PII by default

**Domain:** Fasten-specific + PII redaction

**What goes wrong:** Fasten container logs to stdout. `docker logs health-fasten` may show ingested FHIR resource summaries (resource type, ID, sometimes patient name in error paths). Container log files on host disk persist outside our redaction allowlist.

**Prevention:**
1. **Investigation needed in Phase 1.0 spike** (alongside Pitfall 15): what does Fasten log? If it logs PII, options:
   - Set Fasten `LOG_LEVEL=warn` or `error` (suppress info-level FHIR detail)
   - Pipe stdout through a redaction sidecar (vector / fluent-bit with regex scrub)
   - Use Docker logging driver `local` with rotation + restricted host mount
2. **Audit log retention max 30 days for PII Tier 1** — old logs purged, not archived.
3. **Test:** ingest a known-PII FHIR Bundle → grep `docker logs health-fasten` for PII strings → fail if found.
**Phase:** M1 Phase 1.1 + 1.0 spike.
**Severity:** MEDIUM
**Recovery cost:** MODERATE (log rotation + retention enforcement).

---

### Pitfall 33: Auth.js v5 beta API churn breaks production

**Domain:** Custom analytics

**What goes wrong:** Auth.js v5 is "beta" per STACK.md. Breaking changes between betas → upgrade breaks login → CEO locked out → recovery via DB password reset.

**Prevention:**
1. Pin to exact beta version (`5.0.0-beta.22`). No floating `^5.0.0-beta`.
2. **Stick to v4.24.14 stable for M1** if migration is a nice-to-have only. Auth.js v5 has better App Router DX but isn't blocking M1.
3. Test login flow as part of CI smoke test on every dependency update.
**Phase:** M1 Phase 1.5.
**Severity:** MEDIUM (lockout)
**Recovery cost:** CHEAP (DB-level password reset path documented in runbook).

---

## Low Pitfalls (LOW severity)

### Pitfall 34: Backup script runs but never tested for restore

Already covered as part of Pitfall 3 (mandatory quarterly drill).

### Pitfall 35: HealthKit `source` field dropped (loses provenance)

Drop `<Source>iPhone</Source>` data in mapper → can't re-derive which device produced a reading → can't deduplicate later. Prevention: store `device.identifier` on every Observation. Phase M1.4. LOW (diagnostic info, not user-visible).

### Pitfall 36: Search inconsistency (Fasten search broken per v1.0.0 release notes)

Fasten v1.0.0 release notes flag known search issues. CEO searches for old lab and gets nothing. Prevention: custom analytics layer adds full-text search over `observations.fhir_resource` jsonb (`pg_trgm` extension or `tsvector`). Phase M2. LOW (annoyance, fixable).

### Pitfall 37: Drizzle 1.0 beta tempts upgrade

API churn pre-1.0 GA. Stay on 0.45.x until 1.0 GA. Phase ongoing. LOW (avoidable).

### Pitfall 38: pre-commit hooks bypassable

`gitleaks` + `detect-secrets` in pre-commit, but `git commit --no-verify` skips. Prevention: server-side hook on git remote (if hosted on private GitLab/Gitea), OR rely on pre-push hook + CI scan. Phase M1.1. LOW (relies on developer discipline; CEO is solo).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Skip RLS in M1 ("single user, who cares") | Faster M1 ship | M4 retrofit = 2 weeks + security audit | **NEVER** — A4 mandate |
| Floating Fasten `:main` tag | No upgrade ritual | Silent breakage; M4 SaaS unrepeatable deploys | Never for prod; OK for personal dev throwaway |
| Plaintext `tenant_id` in metric labels | Trivial cardinality | Deanonymizable at small N | Only if `tenant_id` is opaque hash with rotating salt |
| Synchronous OCR in HTTP request | Simple code | Timeouts, no retry, blocks UI | Never — must be background job from day 1 |
| `dotenv` for production secrets | Trivial setup | Vaultwarden integration adds 1 day; pgcrypto key in `.env` is high-risk | M1 only; M2 must move to Vaultwarden lookup |
| Soft-delete tenants | Revertible UX | GDPR Art. 17 violation at SaaS | M1 single-user; M4 must support hard erasure |
| Forking Fasten to add features | Fast feature ship | GPL-3.0 modification triggers source release; harder upstream sync | Never — use HTTP integration in custom layer |
| LLM extraction without human review for medical data | Fast ingest | Silent wrong-data corruption; SaaS clinical liability | Never for medical values; OK for non-medical metadata (lab name, date) |
| Files-on-disk ETL state | Simple iteration | Lost on container restart; not transactional with DB | Never — use `etl_runs` table |
| Generic Tesseract for all lab PDFs | Works on day 1 for any lab | Multi-column Slovak layouts unreliable; D1 differentiator weak | M1 baseline only; M2 must add per-template parsers |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| **Apple Health export** | Naive `xml.etree` strips encoding/timezone | Use `dateutil.parser` + `lxml` with charset detection; preserve `<Source>` for dedup |
| **Oura API v2** | Use legacy Personal Access Token | OAuth2 only — PAT deprecated 2025 (per STACK.md) |
| **Fasten ingest** | Assume RESTful FHIR POST endpoint | Spike first — may need volume-mount JSON drop |
| **Postgres pool + Drizzle** | `db.select()` outside `withTenant()` wrapper | Always wrap; ESLint custom rule enforces |
| **pg `postgres@3.4.9`** | Use prepared statements with `SET LOCAL` | Test that `prepared = false` for tenant-scoped queries (prepared statements cache across tenants) |
| **Cloudflare Tunnel** | Expose Traefik on `0.0.0.0:80` and ALSO public — CF Tunnel makes public path redundant | Bind Traefik to 127.0.0.1:80 only; CF tunnel → Traefik on internal docker network |
| **Vaultwarden `bw` CLI** | Confuse with `bws` (Bitwarden Secrets Manager API — not Vaultwarden) | Use `bw` only — Vaultwarden does NOT expose Secrets Manager API |
| **Tesseract** | Default English-only | Install `tesseract-ocr-slk` + `tesseract-ocr-eng`, set `-l slk+eng` for mixed reports |
| **Ollama** | Run vision model 24/7 (5GB RAM) | On-demand only — start container before OCR batch, stop after |
| **age** | `age -r recipient.txt` syntax mistake (recipient is hex string, not file path) | `age -R recipient.txt` for recipients-file; `-r` for inline |
| **LUKS** | Mount encrypted volume in compose without unlock | Host-level unlock script before `docker compose up`; document in runbook |
| **Sentry SDK** | Default `sendDefaultPii` and full-context capture | `sendDefaultPii: false` + `beforeSend` scrubber + EU region (or self-hosted) |
| **DICOM `pydicom`** | Treat anonymization as optional | Mandatory `dcm.remove_private_tags()` + `Anonymizer` profile before any persistent store |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|---|---|---|---|
| Apple Health full export.xml in-memory parse | OOM on 200MB+ XML | Stream parse with `lxml.etree.iterparse()` + flush per `<Record>`; emit FHIR Bundle in chunks of 1000 | First 5-year export (CEO M1) |
| SQLite WAL unbounded growth | Disk fills, queries slow | Cron `PRAGMA wal_checkpoint(TRUNCATE)` weekly | After ~6 months continuous writes |
| Postgres without index on `(tenant_id, observed_at)` | Slow trends queries | Compound index from M1; verify `EXPLAIN ANALYZE` < 100ms for 90-day window | At ~100K observations |
| Mirror process polls Fasten without delta `_lastUpdated` filter | Re-scans entire Fasten DB | Use `_lastUpdated=gt<since>` query param + checkpoint | At ~10K resources |
| Per-tenant Fasten container memory unbounded | OOM kills neighboring tenants | `mem_limit` per Pitfall 18 | M4 ~10+ tenants/host |
| `pg_dump` without `--jobs` parallelism | Long backup window blocks ETL | M2+: `pg_dump --jobs=4 --format=directory` | At ~1GB DB |
| Drizzle Studio open in production | DB locks, slow queries | Local-only via SSH tunnel; never expose Drizzle Studio via Traefik | Anytime |
| Cron + flock all jobs at 06:00 | Single-writer queue at peak | Stagger jobs by 10-15min: oura@06:00, apple@06:15, lab@06:30 | At 5+ ETL jobs |

---

## Security Mistakes (Beyond OWASP basics)

| Mistake | Risk | Prevention |
|---|---|---|
| Vaultwarden DB on same volume as protected stack | Single point of compromise | Cross-host: Vaultwarden on `docker-srv-01` (per CLAUDE.md), Health stack on local PC / Hetzner |
| Fasten admin password in `.env` checked-in by mistake | Full DB access | `gitleaks` pre-commit + `.gitignore` `.env` strict + Vaultwarden lookup pattern |
| Allow plaintext HTTP from Traefik to Fasten on docker network | Should be encrypted in untrusted networks | M1 OK on local PC bridge network; M4 — network segmentation per tenant + mTLS sidecars (heavy — defer to M5 unless audit demands) |
| Database backups uploaded to S3 with bucket-default encryption | "Encryption" is on cloud provider's keys (BYOK confusion) | age-encrypt before upload; provider-side encryption is bonus, not primary |
| Fasten user accounts shared across "personas" | Data of multiple people in one Fasten = no isolation | Per-person Fasten container (matches A3 family-account workaround) |
| ETL service role connects to Postgres with superuser | Bypasses RLS even if service role limited | Dedicated `app_etl` role with `INSERT/UPDATE` on specific tables only; RLS still enforced |
| `docker exec` shell history saved to host | Commands typed in container persist on host disk | `unset HISTFILE` in container; or use `--rm` ephemeral exec |
| Recovery key shown in compose logs at startup | One log capture = key compromise | Read recovery key from secret file post-startup, never echo to stdout |
| Lab PDF original files on world-readable shares | Pre-OCR files leak | `data/lab/` is `chmod 700` + LUKS volume; NTFS ACL on Windows host equivalent |
| Auto-update Docker images in production | Fasten silent migration; Postgres major version jump | Pin all images to digest; quarterly upgrade ritual |

---

## UX Pitfalls (Domain-specific)

| Pitfall | User Impact | Better Approach |
|---|---|---|
| Show all FHIR fields (raw JSON) | Overwhelming, off-putting | Curated dashboard with "View raw FHIR" expander |
| No "review queue" UI for OCR'd labs | User can't catch hallucinations | Side-by-side PDF + extracted FHIR fields with confirm/reject |
| Display reference range "in red" derived by app | Borderline medical-device function | Reference range from PDF only; coloring matches what lab said |
| One-click "delete all" without export option first | Tenant erasure with no portability | Force Art. 20 FHIR Bundle export before erasure confirmation |
| Health metric trends without unit toggle | Confusion for international users | Locale + per-user unit preference (mmol/L ↔ mg/dL toggle) |
| Show "improving" / "declining" inferred status | Verges on clinical decision support | Show data points + reference range only; user concludes |
| Hide "no data" gaps in time-series charts | Hides ETL failures | Render gaps explicitly; tooltip "no sync since X" |
| LLM-generated summaries of medical history | High hallucination, false confidence (anti-feature A1) | Static cards with structured data only |

---

## "Looks Done But Isn't" Checklist

Items that frequently appear "done" but lack critical pieces.

- [ ] **RLS:** Policy exists on table — verify `pg_policies` returns row + `tests/rls.test.ts` proves cross-tenant isolation
- [ ] **Backup:** `cron` runs nightly — verify quarterly **restore drill** succeeded with byte-identical Postgres + Fasten state
- [ ] **age encryption:** Backups encrypted — verify private key has 3 independent custody locations + key paper printout in fire safe
- [ ] **Apple Health import:** Records ingested — verify daily steps match Health app for spot-check days; verify timezone correct on DST week
- [ ] **Oura sync:** Cron runs — verify `etl_runs.status = 'ok'` for last 7 days + heartbeat alert configured
- [ ] **Lab PDF OCR:** Pipeline runs — verify each ingested lab has been **human-reviewed** and confirmed before write to Fasten
- [ ] **FHIR Patient subject:** ETL POSTs work — verify ALL tenant's observations point to single `Patient/<id>` (no drift)
- [ ] **Encryption-at-rest:** LUKS / BitLocker on volume — verify `lsblk -f` shows `crypto_LUKS` for postgres-data + key custody documented
- [ ] **Fasten image:** Compose pulls image — verify pinned to `:main@sha256:<digest>`, NOT floating `:main` or `:latest`
- [ ] **Logger redaction:** pino configured — verify `paths: ['*']` allowlist + `tests/logger-redaction.test.ts` passes with FHIR Bundle input
- [ ] **GDPR Art. 9 consent:** Schema exists — verify `consent_log` table populated for default tenant + UI flow drafted for M4
- [ ] **Right-to-erasure pipeline:** Tenant offboard — verify `tests/gdpr-erasure.test.ts` proves zero rows + zero files post-erasure
- [ ] **Multi-tenant readiness:** `tenant_id` column — verify RLS active in M1 single-tenant + `withTenant()` wrapper required by ESLint
- [ ] **Sentry / errors:** Disabled in M1 — verify `SENTRY_ENABLED=false` in `.env.example` + no Sentry SDK initialized at runtime
- [ ] **Connection pool:** Drizzle with `postgres@3.4.9` — verify connection acquire/release hook `RESET app.current_tenant` configured
- [ ] **Code mappings:** LOINC/ICD-10/ATC tables exist — verify `code_mappings` populated for top-50 observations + units validated
- [ ] **Pre-commit hooks:** `gitleaks` + `detect-secrets` — verify CI also runs gitleaks (defense-in-depth against `--no-verify`)
- [ ] **Disaster runbook:** `docs/runbooks/disaster-recovery.md` exists — verify DR drill executed successfully in last quarter

---

## Recovery Strategies (when prevention failed)

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| RLS leak discovered post-launch | CATASTROPHIC | (1) Take service offline; (2) audit logs to identify exposed records + tenants; (3) Art. 33 breach notification within 72h to ÚOOÚ; (4) notify affected tenants; (5) fix RLS + add tests; (6) external security audit; (7) reputation recovery (months) |
| Lost age private key | CATASTROPHIC | No technical recovery. Re-import from raw sources (Apple Health export, lab PDFs, DNA raw, Oura via API re-fetch up to retention window). Anything older than re-fetchable = permanent loss. Issue postmortem; rebuild custody plan. |
| FHIR subject drift | EXPENSIVE | Stop ETLs; map all existing Patient resources to canonical Patient; rewrite `subject.reference` on every Observation; re-mirror Postgres analytics; re-derive correlations |
| Apple Health timezone bug | EXPENSIVE | Identify range of affected dates; re-parse export.xml with timezone-fix; mark old observations deprecated in Fasten; ingest corrected; analytics re-mirror |
| OCR hallucinated lab values | EXPENSIVE | Pull all auto-ingested lab observations; manual review against original PDFs; mark suspect rows; rebuild review-queue UI mandatory; re-ingest correctly |
| Backup pipeline plaintext leak | EXPENSIVE | Audit `/tmp`, `/output`, `/var`; secure-wipe found plaintext; rotate age key (re-encrypt last N backups); Art. 33 notification if leak path exposed |
| GPL-3.0 modification disclosed | EXPENSIVE-CATASTROPHIC | Comply with GPL — release modified Fasten source publicly OR rip-and-replace with non-modified upstream; lawyer review; possibly rebuild differentiator |
| Wrong terminology code | MODERATE | Update `code_mappings` table; bulk-update Postgres mirror via SQL; re-derive cross-source dashboards; Fasten resources may need PUT |
| GDPR Art. 17 erasure incomplete | EXPENSIVE | Forensic-wipe missed locations (backups, logs, cache); supervisory authority dialogue; tenant compensation; rebuild erasure pipeline |
| Cron drift / data gap | CHEAP-MODERATE | Catch-up ETL run with extended `since` window; if Oura/Apple retention exceeded, document gap in user dashboard with explanation |
| OCR template drift | MODERATE | Manual re-OCR with new template; compare to old template ingest range; mark uncertain rows for review |
| Per-tenant container OOM | MODERATE | Set mem_limits + restart; investigate import; vertical scale Hetzner; benchmark real capacity |
| Sentry PII capture | MODERATE | Purge Sentry events; rotate any captured tokens; disable Sentry; rebuild with redaction; notify if events shared with 3rd party |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall # | Name | Prevention Phase | Verification |
|---|---|---|---|
| **1** | Multi-tenant theater (no RLS enforcement) | M1 Phase 1.2 | `tests/rls.test.ts` passes; `pg_tables` query returns 0 |
| **2** | Pool reuses tenant context | M1 Phase 1.2 + 1.5 | `withTenant()` ESLint rule; sequential-request RLS test |
| **3** | Lost age private key | M1 Phase 1.7 | Quarterly restore drill calendar reminder |
| **4** | FHIR subject drift | M1 Phase 1.4 | `tests/fhir-subject-coherence.test.ts` |
| **5** | GDPR Art. 9 consent | M1 schema + M4 UI | `consent_log` table; DPIA in `docs/compliance/` |
| **6** | Logger denylist leaks PII | M1 Phase 1.5 | `tests/logger-redaction.test.ts`; ESLint rule |
| **7** | ETL state on disk | M1 Phase 1.4 | `etl_runs` table populated; no state files in `output/` |
| **8** | Apple Health timezone | M1 Phase 1.4 | `tests/apple-health-timezone.test.ts` (DST week sample) |
| **9** | OCR LLM hallucination | M1 Phase 1.6 | Review-queue UI mandatory before Fasten POST |
| **10** | Wrong terminology code | M1 Phase 1.4 | `code_mappings` table; UCUM unit validation |
| **11** | Unit conversion silent error | M1 Phase 1.4 | `tests/unit-conversion.test.ts` |
| **12** | GPL-3.0 SaaS exposure | M1 architecture (firewall) + M4 lawyer review | Custom code license decided; CI license-file hash check |
| **13** | Fasten unpinned `:main` | M1 Phase 1.1 | CI grep for unpinned digest; quarterly upgrade ritual |
| **14** | SQLite single-writer | M1 Phase 1.4 | cron schedule staggered + flock |
| **15** | Fasten ingest API undocumented | M1 Phase 1.0 spike | Spike acceptance test: POST → resource visible in UI |
| **16** | pgcrypto key in env var | M1 Phase 1.2 (or M2 deferral) | Compose `secrets:` block; env-var grep |
| **17** | Plaintext backup intermediate | M1 Phase 1.7 | `tmpfs` mount; CI no-plaintext-FHIR audit |
| **18** | Per-tenant noisy neighbor | M4 prep | `mem_limit` benchmarked + Prometheus alerts |
| **19** | Missing DPA agreements | M4 prep | `docs/compliance/processors.md` populated |
| **20** | Apple Health double-source | M1 Phase 1.4 | `tests/apple-health-dedup.test.ts` |
| **21** | PDF format drift | M2 hardening | Drift hash + manual review trigger |
| **22** | Soft-delete vs Art. 17 | M4 prep | `tests/gdpr-erasure.test.ts` |
| **23** | Sentry auto-captures PII | M1 Phase 1.5 (disabled by default) | Smoke test: trigger error → no PII in capture |
| **24** | Cron drift / sleep | M1 Phase 1.4 | Heartbeat widget + 25h alert |
| **25** | tenant_id hash deanonymizable | M2+ monitoring | HMAC + rotating salt; cardinality limits |
| **26** | Decimal comma confusion | M1 Phase 1.6 | `tests/decimal-comma.test.ts` |
| **27** | SNOMED CT license | M4 prep | License verification; ICD-10 fallback if needed |
| **28** | DICOM PHI in headers | M2 (DICOM) | `pydicom` Anonymizer profile applied |
| **29** | Drizzle push in prod | M1 Phase 1.2 | CI deny `drizzle-kit push`; backup-before-migrate |
| **30** | SSO admin god mode | M4 prep | Per-realm Authentik config |
| **31** | Aggregations bypass RLS | M4 | Aggregate via tenant iteration; audit log |
| **32** | Fasten logs PII | M1 Phase 1.0/1.1 | Spike: log audit; redaction sidecar if needed |
| **33** | Auth.js v5 beta churn | M1 Phase 1.5 | Pin exact beta; smoke test on dependency update |

---

## M1 Verification Gates (BLOCKING — Cannot Ship Phase 1 Without)

Roadmap MUST gate M1 (Phase 1) completion on these — every BLOCKER pitfall has a verification.

```
☐ tests/rls.test.ts             — Pitfall 1, 2 (RLS enforcement + pool reuse)
☐ tests/fhir-subject-coherence  — Pitfall 4 (Patient resolver works)
☐ tests/logger-redaction        — Pitfall 6 (allowlist redaction)
☐ tests/apple-health-timezone   — Pitfall 8 (DST + multi-source)
☐ tests/apple-health-dedup      — Pitfall 20 (iPhone + Watch dedup)
☐ tests/unit-conversion         — Pitfall 11 (canonical + UCUM)
☐ tests/decimal-comma           — Pitfall 26 (sk-locale)
☐ Manual review queue UI for lab PDF — Pitfall 9 (no auto-ingest medical values)
☐ etl_runs / etl_failures tables populated  — Pitfall 7 (no on-disk state)
☐ code_mappings table + LOINC/UCUM YAML     — Pitfall 10 (terminology)
☐ Backup script: pipe-only encryption        — Pitfall 17 (no plaintext intermediate)
☐ Quarterly restore drill executed           — Pitfall 3 (age key recoverable)
☐ Fasten image pinned to @sha256:<digest>    — Pitfall 13
☐ Phase 1.0 spike completed (Fasten API)     — Pitfall 15, 32
☐ consent_log table exists in schema         — Pitfall 5 (M4 prep)
☐ tenant_id NOT NULL on all multi-tenant tables — Pitfall 1
☐ ESLint custom rule: no DB query outside withTenant() — Pitfall 2
☐ CI: gitleaks + detect-secrets + license hash check — Pitfall 12, 38
☐ docs/runbooks/disaster-recovery.md complete with DR drill log — Pitfall 3, 17
```

---

## Sources

**Multi-tenant RLS:**
- [Drizzle ORM Row-Level Security](https://orm.drizzle.team/docs/rls) — `pgPolicy` / `crudPolicy` syntax
- [Permit.io: Postgres RLS Implementation Guide](https://www.permit.io/blog/postgres-rls-implementation-guide) — common pitfalls
- [Nile: Multi-tenant SaaS using Postgres RLS](https://www.thenile.dev/blog/multi-tenant-rls)
- [AWS: Multi-tenant data isolation with RLS](https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/) — connection pool + acquire/release
- [Drizzle RLS feature discussion #2450](https://github.com/drizzle-team/drizzle-orm/discussions/2450)

**SQLite WAL + concurrency:**
- [SQLite WAL documentation](https://www.sqlite.org/wal.html)
- [SQLite User Forum: Multiple Writers](https://sqlite.org/forum/info/b4e8b29ae409cd198652c6b7e70b53b702f269e67e1d2573d627feeba37bbf85)
- [phiresky: SQLite performance tuning](https://phiresky.github.io/blog/2020/sqlite-performance-tuning/)
- [Oldmoe: Concurrent Write Transactions in SQLite](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/)

**GPL-3.0 / AGPL SaaS:**
- [Mend: SaaS Loophole in GPL Open Source Licenses](https://www.mend.io/blog/the-saas-loophole-in-gpl-open-source-licenses/)
- [FOSSA: AGPL License 101](https://fossa.com/blog/open-source-software-licenses-101-agpl-license/)
- [FSF: GPLv3 and Software as a Service](https://www.fsf.org/blogs/licensing/2007-03-29-gplv3-saas) — "mere interaction is not conveying"
- [Vaultinum: Guide to AGPL Compliance](https://vaultinum.com/blog/essential-guide-to-agpl-compliance-for-tech-companies)

**Apple Health export:**
- [TDDA: In Defence of XML — Apple Health Data](https://www.tdda.info/in-defence-of-xml-exporting-and-analysing-apple-health-data) — historical sampling changes, multi-source dedup
- [Apple Health Export XML format](https://www.aihealthexport.com/guides/apple-health-xml-format)
- [HealthKitOnFhir (Microsoft)](https://github.com/microsoft/healthkit-on-fhir) — Swift library reference for mapping
- [Apple HealthKit Quantity Sample Logical Model (FHIR IG)](https://build.fhir.org/ig/HL7/standard-patient-health-record-ig/StructureDefinition-apple-health-kit-quantity-sample.profile.json.html)

**Tesseract Slovak / OCR:**
- [tesseract Issue #4276: Diacritics not always recognised](https://github.com/tesseract-ocr/tesseract/issues/4276)
- [tessdata Issue #130: Slovak slk.traineddata not working correctly](https://github.com/tesseract-ocr/tessdata/issues/130)
- [Tesseract Languages/Scripts supported](https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html)

**Healthcare LLM hallucination:**
- [Medical Hallucination in Foundation Models (medRxiv 2025-02)](https://www.medrxiv.org/content/10.1101/2025.02.28.25323115v2.full.pdf)
- [Multi-model assurance analysis: LLM hallucination during clinical decision support (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12318031/) — Qwen-2.5-72B vs GPT-4o
- [npj Digital Medicine: Framework to assess clinical safety / hallucination of LLMs](https://www.nature.com/articles/s41746-025-01670-7)
- [MedVH: Systematic Evaluation of Hallucination for LVLMs in Medical Context](https://pmc.ncbi.nlm.nih.gov/articles/PMC12363988/)
- [Seeing is Believing? Mitigating OCR Hallucinations in MLLMs](https://arxiv.org/html/2506.20168v2)
- [Overconfidence and Calibration in Medical VQA](https://arxiv.org/html/2604.02543)

**GDPR Art. 9 / Art. 17 / DPIA:**
- [Art. 17 GDPR Right to erasure](https://gdpr-info.eu/art-17-gdpr/)
- [Article 17 Right to be Forgotten (Algolia GDPR)](https://gdpr.algolia.com/gdpr-article-17)
- [Healthcare GDPR Compliance & Article 9 (Secure Privacy)](https://support.secureprivacy.ai/article/industry-specific-dpo-guidance-healthcare/)
- [GDPR.eu: Right to be forgotten](https://gdpr.eu/right-to-be-forgotten/)
- [ICO: Right to erasure](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/)

**FHIR R4 / LOINC / terminology:**
- [LOINC 2161-8 Creatinine in Urine](https://loinc.org/2161-8)
- [LOINC 14683-7 Creatinine [Moles/volume] in Urine](https://loinc.org/14683-7)
- [LOINC 12195-4 Creatinine renal clearance/1.73 sq M in 24 hour Urine and Serum or Plasma](https://loinc.org/12195-4)

**Encryption / age:**
- [FiloSottile/age GitHub](https://github.com/FiloSottile/age)
- [restic-age-key (asymmetric age keys for restic)](https://github.com/josh/restic-age-key)
- [restic forum: storing key in backup location safety](https://forum.restic.net/t/is-storing-key-in-the-backup-location-really-safe/2021)
- [OneUptime: Backup Encryption Configuration](https://oneuptime.com/blog/post/2026-01-25-backup-encryption/view)
- [Severalnines: Database Backup Encryption Best Practices](https://severalnines.com/blog/database-backup-encryption-best-practices/)

**Project context:**
- `Projects/health/CLAUDE.md` — PII Tier 1 cross-aware isolation
- `Projects/health/.planning/PROJECT.md` — M1 scope, key decisions
- `Projects/health/.planning/research/STACK.md` — versions and known issues (Fasten Postgres broken; GPL-3.0 license)
- `Projects/health/.planning/research/FEATURES.md` — anti-features, EU market reality, multi-tenant verdict
- `Projects/health/.planning/research/ARCHITECTURE.md` — A1–A8 architectural decisions

---

*Pitfalls research for: self-hosted personal health data aggregator with EU/SK SaaS pivot path*
*Researched: 2026-05-09*
*Author: GSD researcher (project: health, milestone: M1)*
