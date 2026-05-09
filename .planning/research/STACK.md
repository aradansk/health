# Stack Research

**Domain:** Self-hosted personal health data aggregator with multi-tenant SaaS pivot path
**Researched:** 2026-05-09
**Confidence:** HIGH (versions verified via GitHub releases / official docs / 2026 sources)

## Executive Summary

Stack is locked by CEO decisions in BOOTSTRAP.md and PROJECT.md — this research **confirms current versions, flags compatibility gotchas, and prescribes supporting libraries** rather than re-litigating choices. Key prescriptive calls below:

- **ORM: Drizzle** (not Prisma). SQL-first nature + native RLS support + 7.4kB bundle wins for multi-tenant from day 1. Confidence: HIGH.
- **Apple Health parser: `apple-health-parser` (Python)** + custom FHIR mapper layer. There is **no maintained "drop-in" Apple-Health-XML→FHIR-R4 OSS library for the iOS export format** (HealthKitOnFHIR is Swift on-device, not for the export XML). Custom mapping required. Confidence: HIGH.
- **Lab PDF OCR: Decision tree** — start with Tesseract + local Ollama (Llama 3.2 / Qwen 2.5) for structured extract; fall back to Azure Document Intelligence (Form Recognizer) only if accuracy unacceptable on real lab PDFs. Cloud OCR sends PII Tier 1 outside boundary — avoid until proven necessary. Confidence: MEDIUM.
- **ETL orchestration: cron + flock** in M1 (3 daily jobs, no need for Redis/queue overhead). Migrate to BullMQ when >10 jobs or need retries/backoff. Confidence: HIGH.
- **Encryption-at-rest: LUKS on the host volume** (NOT pgcrypto column-level for Fasten — Fasten manages its own schema). pgcrypto only for **custom analytics tables** that store sensitive denormalized fields. Confidence: HIGH.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Fasten On-Premises** | `v1.1.3` (image: `ghcr.io/fastenhealth/fasten-onprem:v1.1.3`) | FHIR R4 PHR aggregator, 650+ US healthcare provider connectors, manual record wizard, CCDA support | CEO-locked. v1.1.3 is current stable (Oct 2024). Pull pinned tag, NOT `:main` (avoid breaking on nightly). v1.0.0 (Dec 2023) marked production-ready milestone. Active project, MIT-equivalent OSS license. Confidence: HIGH. |
| **PostgreSQL** | `16.13` (image: `postgres:16.13-bookworm` or `postgres:16-alpine` for size) | Primary DB, multi-DB pattern (`fasten`, `analytics`) | CEO-locked. 16.13 released 2026-02-26 (latest 16.x minor). EOL Nov 2028 — runway. Plain Postgres avoids Supabase complexity until SaaS pivot. Confidence: HIGH. |
| **Next.js** | `15.2.4` (App Router, stable) | Custom analytics layer UI + API routes | Stable App Router, React 19 support, Turbopack stable. Don't jump to Next.js 16 (Oct 2025) yet — 15.2.x is battle-tested. Confidence: HIGH. |
| **Drizzle ORM** | `0.45.2` (NPM `drizzle-orm@0.45.2`, kit `drizzle-kit@0.31.x`) | TypeScript ORM, schema, migrations, RLS hooks | **Recommended over Prisma** for multi-tenant RLS — see decision below. Stay on 0.45.x stable line, NOT 1.0.0-beta.x (API churn). Confidence: HIGH. |
| **Traefik** | `v3.7.0` (image: `traefik:v3.7.0`) | Reverse proxy, automatic Docker labels, middleware chains, optional TLS termination | CEO-locked. v3.7.0 released 2026-05-05. v3 is current major; v2.x is EOL. Pin minor (`v3.7`) to prevent surprise upgrades. Confidence: HIGH. |
| **Vaultwarden** | `1.34.5` (image: `vaultwarden/server:1.34.5`, web-vault `2026.1.1`) | Secrets store (manual lookup M1, `bws` sidecar M2+) | CEO-locked. 2026.1.1 series is current. NOTE: Vaultwarden does NOT natively expose Bitwarden Secrets Manager — for `bws` CLI sidecar pattern, use **Bitwarden cloud or upstream Bitwarden self-hosted**. For pure Vaultwarden, sidecar uses `bw` (regular CLI) against personal vault — see "Vaultwarden + bw sidecar" below. Confidence: HIGH. |
| **cloudflared** | `2026.2.x` (image: `cloudflare/cloudflared:latest`, pin digest in production) | CF Tunnel daemon for `health.ardan.sk` ingress (M2+) | Token-based tunnel (`TUNNEL_TOKEN` env var from Vaultwarden). Health-check via `cloudflared tunnel ready`. Confidence: HIGH. |
| **Docker Compose** | v2 (Compose Spec, bundled with Docker Desktop) | Stack orchestration | Standard. Use `compose.yaml` (not legacy `docker-compose.yml`). Confidence: HIGH. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **`apple-health-parser`** (PyPI) | `latest` (alxdrcirilo/apple-health-parser, active 2026) | Parse Apple Health `export.xml` into pandas DataFrames + JSON | M1: Apple Health import ETL. Parses Records/Workouts/etc. Supplement with custom HealthKit→FHIR R4 mapper (see ARCHITECTURE.md). |
| **Python `xml.etree.ElementTree.iterparse`** | stdlib | Streaming XML parsing for huge `export.xml` (often >500MB) | Wrap apple-health-parser if memory pressure on large exports. |
| **`oura-ring`** (PyPI, hedgertronic) | `latest` | Oura Ring API v2 client (sleep/readiness/activity/HRV) | M1: Oura daily sync. Active maintainer. Alternative: `@pinta365/oura-api` (TS/Deno via JSR) if Node ETL preferred. |
| **`pdf2image` + `pytesseract`** | `pdf2image>=1.17`, `pytesseract>=0.3.13`, Tesseract `5.4.x` | Lab PDF → image → OCR text | M1: Local-only lab PDF OCR. Free, no PII leakage. Combine with LLM structured extract. |
| **`Ollama`** + `qwen2.5:7b` or `llama3.2:3b` | Ollama `0.4.x`, Qwen 2.5 7B (or smaller) | Structured extract: OCR text → FHIR Observation JSON (LOINC codes) | M1+: After Tesseract, run text through local LLM with FHIR R4 Observation schema prompt. Keeps PII local. |
| **`fhir.resources`** (PyPI) | `>=8.0.0` (FHIR R4 / R4B / R5 pydantic models) | Validate FHIR R4 resources before POST to Fasten | Use in ETL workers to construct + validate Observation/Patient/MedicationRequest before injection. |
| **`zod`** (NPM) | `>=3.23` | Runtime schema validation in Next.js API routes | All API endpoints. Required for safe untrusted input parsing. |
| **`postgres`** (NPM, porsager/postgres) | `>=3.4` | Postgres driver under Drizzle | Drizzle's recommended driver for Node. Faster than `pg`. |
| **`@auth/drizzle-adapter`** + **`next-auth`** | NextAuth `v5.x` (Auth.js) | Auth in custom analytics layer (M3+) | Drizzle-native adapter. Defer to M3 — M1 single-user can use HTTP basic auth or Traefik forward-auth. |
| **`pino`** (NPM) | `>=9.x` | Structured JSON logging with PII redaction | **MANDATORY**: configure `redact` paths for any field that could contain PII. Never log raw FHIR payloads. |
| **`bullmq`** (NPM, only if scaling beyond cron) | `>=5.x` | Redis-backed job queue with retries/cron/rate-limit | M2+ when >5 ETL jobs or need retry semantics. NOT needed M1. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **`age`** (FiloSottile/age) v1.2.x | Encrypted DB backups → off-site | Choose age over gpg: 100x simpler, modern AEAD, ssh-key-compatible. `pg_dump | age -r <recipient> > backup.age`. |
| **LUKS / `cryptsetup`** v2.7.x | Block-device encryption for Postgres data volume on host | Pre-create LUKS volume, mount to `/var/lib/postgres-encrypted`, bind-mount into container. Docker compose can't manage LUKS itself — host-level setup. AES-NI = 2-5% perf hit. |
| **`drizzle-kit`** v0.31.x | Schema migrations, introspect, push, generate SQL | `drizzle-kit generate` for SQL migrations (review before prod). `drizzle-kit push` only in dev. |
| **`docker-compose-traefik-letsencrypt-cloudflare`** (eingress reference) | Reference compose pattern for Traefik + CF DNS-01 | Reference only — adapt to CF Tunnel pattern (no DNS-01 needed when using tunnel). |
| **`pre-commit`** (Python) | Git hook framework: detect-secrets, gitleaks, ruff, prettier | MANDATORY for PII Tier 1 project. Block accidental commit of `.env`, lab PDFs, DICOM. |
| **`gitleaks`** v8.x | Secret scanning in pre-commit hook | Catches Oura tokens, Fasten admin password, etc. |

## Installation

```bash
# Python ETL workers (in projects/etl/)
pip install \
  apple-health-parser \
  oura-ring \
  pdf2image pytesseract \
  fhir.resources \
  pillow \
  python-dotenv \
  httpx

# System deps for OCR
apt install -y tesseract-ocr poppler-utils

# Ollama (host-level, Docker container alternative available)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b      # ~4.7GB, good FHIR JSON output
# OR smaller for low RAM:
ollama pull llama3.2:3b     # ~2.0GB

# Next.js analytics layer (in projects/analytics/)
npx create-next-app@15.2.4 analytics --ts --app --tailwind --src-dir --no-eslint
cd analytics
npm install \
  drizzle-orm@0.45.2 \
  postgres@^3.4 \
  zod@^3.23 \
  pino@^9 \
  next-auth@^5

npm install -D \
  drizzle-kit@^0.31 \
  @types/node \
  pino-pretty

# Pre-commit (root of repo)
pip install pre-commit
pre-commit install
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **Drizzle 0.45.x** | **Prisma 7** | Prisma 7's TS Query Compiler (1.6MB, 85% smaller than legacy Rust engine) closes the bundle gap. Choose Prisma if team has stronger Prisma muscle memory or wants Prisma Studio UI. RLS is workable in Prisma but feels grafted-on; Drizzle's `crudPolicy()` and SQL-first semantics are first-class. **For multi-tenant RLS from day 1, Drizzle is more idiomatic.** |
| **Drizzle 0.45.x** | **Drizzle 1.0-beta** | Stay on 0.45 stable line for production. 1.0-beta has API churn (consolidated package layout, refined relational query API). Re-evaluate when 1.0 GA ships. |
| **Tesseract + Ollama (local)** | **Azure Document Intelligence** | Use Azure if (a) lab PDFs are scans of handwritten forms, (b) accuracy in Tesseract bench shows >5% extraction errors on real lab data, (c) DPIA explicitly approves cloud OCR transit (PII Tier 1). Azure leads on accuracy (~99.8%) but costs ~$1.50/1k pages and exfiltrates PII to Microsoft. Defer to M3 if at all. |
| **Tesseract + Ollama (local)** | **Google Document AI** | Strong on multilingual (good for SK lab forms in Slovak). Cost-comparable to Azure. Same PII concern. |
| **cron + flock** | **BullMQ + Redis** | BullMQ wins when (a) >5 jobs, (b) you need retry/backoff/rate-limit, (c) you want UI for job status (Bull Board). NOT M1 — 3 daily jobs (Apple Health one-shot, Oura sync, Lab PDF watcher) handle fine with cron. Add Redis when scaling. |
| **cron + flock** | **Celery + Redis/RabbitMQ** | Celery is Python-native (matches ETL workers) but heavier. Skip in M1 — cron is simpler. Reconsider if ETL grows complex enough to need DAGs (then jump to Dagster/Prefect, not Celery). |
| **age for backups** | **gpg** | gpg is fine if you already have an established gpg keyring or need email-style signing/web-of-trust. For backup-only use case, age is simpler, faster, modern AEAD. |
| **LUKS on host volume** | **Docker volume encryption plugin** | LUKS is the standard, predictable, broadly supported. Plugins like `docker-volume-crypt` add complexity for marginal benefit on single-host. |
| **Plain Postgres 16** | **Supabase Self-Hosted** | Defer Supabase to M4 SaaS pivot. Supabase = Postgres + GoTrue + PostgREST + Storage + Realtime + Edge Functions. Powerful but heavier. M1 only needs Postgres. |
| **`apple-health-parser` (Python)** | **Custom JS XML stream parser** | Python parser is more mature for this dataset (apple-health-parser is actively maintained 2026). Pick JS only if entire ETL stack is Node. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Fasten image tag `:main`** | Bleeding-edge, can break on any push | Pin `:v1.1.3` or `:v1.1` |
| **Postgres `:latest`** | Major version jump silently breaks on container recreate | Pin `:16.13-bookworm` or at minimum `:16-alpine` |
| **Apple's `HealthKitOnFHIR` (Swift, StanfordBDHG)** | Swift Package, runs on iOS device — does NOT parse the iOS export.zip XML format | Use `apple-health-parser` (Python) + custom HealthKit→FHIR mapper layer |
| **Apple Health MCP Server (Momentum)** | "Evolved into Open Wearables" — moving target, not a stable library dependency | Roll your own thin parser layer using `apple-health-parser` |
| **Cloud OCR (Azure/Google) in M1** | Sends Tier 1 PII outside our boundary without DPIA | Tesseract + local Ollama; cloud only after DPIA in M3+ |
| **`pg` (npm, node-postgres) under Drizzle** | Slower than `postgres` (porsager) for Drizzle workloads | `postgres@^3.4` driver |
| **Sending FHIR resources to public LLM APIs (OpenAI, Anthropic) for analysis** | PII Tier 1 + GDPR Art. 9 + explicit consent required + DPIA | Local Ollama only; defer cloud LLM to post-DPIA |
| **`docker-compose` v1 (legacy Python)** | Unmaintained, missing Compose Spec features | `docker compose` v2 (built-in to Docker Desktop) |
| **DNS-01 with Let's Encrypt for `health.ardan.sk`** | Unnecessary when using CF Tunnel — Cloudflare terminates TLS at edge | CF Tunnel ingress, internal HTTP between Traefik ↔ apps |
| **Storing tokens in `.env` checked into git** | PII Tier 1 project — leaked Oura token = personal health data exposure | Vaultwarden + manual lookup (M1) → `bws`/`bw` sidecar (M2+) |
| **Prisma Postgres adapter via Data Proxy** | Cloud-routed queries; defeats self-hosted intent | If using Prisma, use direct Postgres connection |
| **Fasten "Multi-User mode" assumption** | Not yet verified — needs research before architecture lock-in (see PROJECT.md open question #5) | M1 = single Fasten instance. Resolve in research/multi-tenant-fasten.md before M4 |

## ORM Decision: Drizzle (prescriptive)

**Recommendation: Drizzle 0.45.2** for multi-tenant RLS analytics layer.

**Rationale:**

1. **Native RLS support.** Drizzle exposes `pgTable.enableRLS()` and `crudPolicy()` helpers; SQL-first nature makes RLS policies natural. Prisma's RLS path is via session vars but not first-class — historically grafted on.
2. **Multi-tenant `tenant_id` pattern is idiomatic.** Set per-request session variable `set local app.tenant_id = '<uuid>'` in middleware, and Postgres applies policies transparently to every Drizzle query. Documented pattern with examples on Neon/Supabase blogs.
3. **Bundle size matters in serverless future.** 7.4kB Drizzle vs Prisma's heavier runtime. If health portal ever needs edge runtime (Cloudflare Workers for read-heavy patient self-service), Drizzle wins.
4. **No magic.** Drizzle generates SQL that you can copy and run. Easier to debug RLS issues, where Prisma's query engine abstracts SQL.
5. **Schema-as-code.** Drizzle schemas are TypeScript files you check in — pairs cleanly with Postgres-side RLS policies expressed in SQL migration files.

**Trade-offs accepted:**
- Smaller ecosystem than Prisma (fewer Stack Overflow hits, fewer starter kits).
- No Prisma Studio equivalent — use `psql`, `pgAdmin`, or `Drizzle Studio` (web UI shipped with drizzle-kit, simpler than Prisma Studio).
- More manual relational query construction; offset by `db.query.X.findMany({ with: ... })` API in 0.45+.

**Implementation sketch (M3):**

```typescript
// schema/health.ts
import { pgTable, uuid, timestamp, jsonb, pgPolicy } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';

export const observations = pgTable('observations', {
  id: uuid('id').primaryKey().defaultRandom(),
  tenantId: uuid('tenant_id').notNull(),
  fhirResource: jsonb('fhir_resource').notNull(),
  createdAt: timestamp('created_at').defaultNow(),
}, (t) => ({
  rls: pgPolicy('tenant_isolation', {
    as: 'permissive',
    for: 'all',
    to: 'authenticated',
    using: sql`tenant_id = current_setting('app.tenant_id')::uuid`,
  }),
})).enableRLS();

// middleware.ts (Next.js)
import { db } from './db';
import { sql } from 'drizzle-orm';

export async function withTenant(tenantId: string, fn: () => Promise<any>) {
  return db.transaction(async (tx) => {
    await tx.execute(sql`set local app.tenant_id = ${tenantId}`);
    return fn();
  });
}
```

## Lab PDF OCR Decision Tree

Start cheapest + most private; escalate only on proven failure.

```
1. Tesseract 5.4 + pdf2image → text
       │
       ├─ Text quality OK? (legible, structured)
       │     │
       │     ├─ YES → 2. Local Ollama (qwen2.5:7b) with FHIR R4 Observation
       │     │       JSON schema prompt → structured Observation resources
       │     │              │
       │     │              ├─ Validates against fhir.resources? → DONE (PII stays local)
       │     │              └─ Fails validation > 20% of fields → escalate
       │     │
       │     └─ NO (poor scan / handwriting) → escalate
       │
       └─ Escalation path (only after DPIA, M3+):
              ├─ Azure Document Intelligence prebuilt-document model
              │     ($1.50/1k pages, ~99.8% accuracy, table-aware)
              │     PII transit to Microsoft EU region — DPIA required
              └─ Google Document AI Health Form parser
                    (similar cost, strong multilingual incl. Slovak)
```

**Per-PDF cost ceiling (cloud):** ~$0.0015. For ~50 lab PDFs/year self-use, total = $0.075/yr. Not a cost concern; **the gate is privacy/compliance**, not money.

**M1 acceptance bar:** Tesseract + Ollama achieves >80% correct LOINC code mapping on 5 sample lab PDFs from real Slovak labs. If <80%, lab OCR feature → M2 with Azure escalation path planned.

## ETL Orchestration Decision

**M1: cron + flock.** Three jobs, none time-critical:
- `00 02 * * * flock -n /tmp/oura.lock python /etl/oura_sync.py` (daily 02:00)
- `00 03 * * 0 flock -n /tmp/applehealth.lock python /etl/apple_health_import.py` (weekly Sun 03:00, gated on file presence)
- `*/30 * * * * flock -n /tmp/labpdf.lock python /etl/lab_pdf_watcher.py` (every 30min, watches `data/lab-inbox/`)

`flock` prevents overlap if previous run hangs. Logs to `pino`-formatted JSON per job. Failures log + email (or Discord webhook).

**Migrate to BullMQ when ANY of:**
- More than 5 distinct ETL jobs
- Need retry-with-backoff (e.g., Oura API 429 handling — currently handled in-script)
- Need scheduled UI / dashboard
- Multi-tenant ETL (one tenant's job shouldn't block another's)

**Skip Celery** unless team becomes Python-heavy and wants Celery Beat. BullMQ pairs better with Next.js worker pattern.

## Vaultwarden + bw Sidecar Pattern (M2+)

**Important constraint discovered:** Vaultwarden does **NOT natively expose Bitwarden Secrets Manager API** (`bws` CLI). It is a Bitwarden-compatible vault but the Secrets Manager is a separate Bitwarden product. Sources confirm this discrepancy.

**Pattern for Vaultwarden:**

```yaml
# compose.yaml fragment
services:
  bw-init:
    image: bitwarden/cli:latest
    environment:
      - BW_HOST=https://vaultwarden.host
      - BW_CLIENTID=${BW_CLIENTID}
      - BW_CLIENTSECRET=${BW_CLIENTSECRET}
    volumes:
      - bw-secrets:/secrets
    entrypoint:
      - /bin/sh
      - -c
      - |
        bw config server $$BW_HOST
        bw login --apikey
        export BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw)
        bw get item "fasten-admin" --session $$BW_SESSION | jq -r .login.password > /secrets/fasten_admin
        bw get item "oura-token" --session $$BW_SESSION | jq -r .login.password > /secrets/oura_token

  fasten:
    depends_on:
      bw-init:
        condition: service_completed_successfully
    secrets:
      - fasten_admin

volumes:
  bw-secrets:

secrets:
  fasten_admin:
    file: bw-secrets/fasten_admin
```

This pattern uses regular `bw` CLI (not `bws`) against the Vaultwarden instance. M1 = manual lookup; introduce sidecar in M2+ when secret count >10.

## Stack Patterns by Variant

**If staying single-user forever (no SaaS pivot):**
- Skip `tenant_id` columns entirely — saves a column on every table
- Skip Drizzle RLS hooks — use plain Postgres user permissions
- BUT: this contradicts CEO decision in PROJECT.md (multi-tenant readiness from day 1). Architecture stays as designed.

**If SaaS pivot triggers (M4+):**
- Migrate Postgres → Supabase Self-Hosted (in-place: Supabase IS Postgres + auth/storage/realtime sidecars)
- Add Authentik in front of Traefik
- Per-tenant Fasten instance pattern: Traefik routes `<tenant>.health.ardan.sk` → dedicated Fasten container with separate Fasten DB schema
- OR resolve `multi-tenant-fasten.md` open question — does Fasten Multi-User mode exist natively?

**If running on Hetzner CX22 instead of local PC:**
- Identical compose stack (key benefit of containerization)
- LUKS encryption set up at server provisioning (Hetzner provides custom install ISO)
- Backup target: Hetzner Storage Box ($3/mo for 1TB) or Backblaze B2

**If 24/7 uptime required:**
- Move from PC to Hetzner CX22 sooner (M2 instead of M4)
- Add `restart: unless-stopped` to all compose services
- Health checks: `cloudflared tunnel ready`, `traefik healthcheck`, `pg_isready`

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `fasten-onprem:v1.1.3` | Postgres 14, 15, 16 | Fasten uses GORM internally; Postgres 16 fine. Verify on first deploy. |
| `drizzle-orm@0.45.2` | `postgres@^3.4`, `node@^20`, `next@15.x` | Stable production combo. |
| `next@15.2.4` | `react@19.x`, `node@>=18.18` | React 19 required for Next 15. Don't mix React 18 deps. |
| `traefik:v3.7.0` | `cloudflared:2026.2.x` | Traefik handles HTTP/2 and HTTP/3; cloudflared upstream supports both. Use HTTP between cloudflared → Traefik (no TLS on internal hop) per CF best practice with origin cert. |
| `vaultwarden:1.34.5` | `bw@2025.10.x` (CLI), `bws@1.x` (Secrets Manager — NOT compatible with Vaultwarden) | Use regular `bw` CLI. Vaultwarden does not expose Secrets Manager API. |
| `postgres:16.13` | `pgcrypto` (built-in), `pg_trgm`, `pg_stat_statements` | Enable extensions: `CREATE EXTENSION pgcrypto;` in `analytics` DB. Fasten manages its own extensions in `fasten` DB. |
| `pytesseract@0.3.13` | `tesseract@>=5.4` | Tesseract binary install required. Add `tesseract-ocr-slk` (Slovak language pack) for SK lab PDFs. |
| `Ollama@0.4.x` | `qwen2.5:7b`, `llama3.2:3b` | qwen2.5 better at structured JSON output (tested 2025-2026). Llama 3.2 3B for low-RAM. |

## Healthcare-Specific Notes

- **FHIR R4 conformance:** Fasten On-Premises is FHIR R4 native. When ingesting custom data (Apple Health, Oura, lab PDFs), construct **valid FHIR R4 Observation/Patient/MedicationRequest** resources, validate via `fhir.resources` pydantic models before POST. Never bypass FHIR layer to write directly to Fasten DB — breaks Fasten data model invariants.
- **LOINC codes** for lab Observations: required for interoperability. Use [LOINC FHIR Terminology Service](https://loinc.org/fhir/) to look up codes for Slovak lab tests. Ollama prompt should include common LOINC codes for top 20 lab panels.
- **GDPR Art. 9 (special category — health data):** Encryption-at-rest mandatory (LUKS). Encryption-in-transit (HTTPS via CF Tunnel). Audit logging of every read/write to FHIR resources. DPIA required before first paying tenant in M4+.
- **Data residency:** Hetzner CX22 in EU (Germany/Finland). Cloudflare Tunnel terminates TLS at CF edge — confirm CF data residency for the zone (`ardan.sk`). For SaaS EU pivot: ensure no data leaves EU regions.
- **Audit trail:** Every FHIR resource write should produce an audit log row (separate `audit_log` table in `analytics` DB) — actor, resource type, resource ID, action, timestamp. Required for GDPR Art. 32.
- **Patient consent (M4+):** GDPR Art. 9 explicit consent before processing. Consent management UI required. Out-of-scope for M1 (single-user = self-consent implicit).

## Sources

- [Fasten On-Premises GitHub Releases](https://github.com/fastenhealth/fasten-onprem/releases) — v1.1.3 latest stable confirmed (HIGH)
- [PostgreSQL 16.13 release announcement](https://www.postgresql.org/about/news/postgresql-1812-178-1612-1516-and-1421-released-3235/) and [PostgreSQL 16.13 release](https://www.postgresql.org/about/news/postgresql-183-179-1613-1517-and-1422-released-3246/) — version verified (HIGH)
- [Drizzle ORM RLS docs](https://orm.drizzle.team/docs/rls) — first-class RLS support confirmed (HIGH)
- [Drizzle ORM latest releases](https://orm.drizzle.team/docs/latest-releases) and [Drizzle on npm](https://www.npmjs.com/package/drizzle-orm) — 0.45.2 stable verified (HIGH)
- [Drizzle vs Prisma 2026 (Bytebase)](https://www.bytebase.com/blog/drizzle-vs-prisma/), [Drizzle vs Prisma 2026 (DEV)](https://dev.to/pockit_tools/drizzle-orm-vs-prisma-in-2026-the-honest-comparison-nobody-is-making-3n6g), [Prisma vs Drizzle (Makerkit)](https://makerkit.dev/blog/tutorials/drizzle-vs-prisma) — multi-tenant RLS comparison (MEDIUM, multiple sources agreeing)
- [Next.js 15 stable](https://nextjs.org/blog/next-15) and [Next.js current March 2026](https://www.abhs.in/blog/nextjs-current-version-march-2026-stable-release-whats-new) — 15.2.4 verified stable (HIGH)
- [Traefik v3.7.0 release](https://github.com/traefik/traefik/releases) — May 2026 release verified (HIGH)
- [Vaultwarden releases](https://github.com/dani-garcia/vaultwarden/releases) — 1.34.5 verified (HIGH)
- [Bitwarden Secrets Manager CLI docs](https://bitwarden.com/help/secrets-manager-cli/) — `bws` is NOT supported by Vaultwarden, must use regular `bw` (HIGH, official source)
- [Cloudflare Tunnel + Traefik (Matt Dyson)](https://mattdyson.org/blog/2024/02/using-traefik-with-cloudflare-tunnels/) and [cloudflared + traefik docker (Gero Gerke)](https://gero.dev/blog/cloudflared-traefik-docker) — CF Tunnel sidecar pattern (HIGH, multiple working examples)
- [apple-health-parser PyPI](https://pypi.org/project/apple-health-parser/) and [GitHub alxdrcirilo/apple-health-parser](https://github.com/alxdrcirilo/apple-health-parser) — active 2026 maintenance (HIGH)
- [HealthKitOnFHIR (Stanford BDHG)](https://github.com/StanfordBDHG/HealthKitOnFHIR) — Swift on-device, NOT for export.xml (HIGH, source review)
- [Oura API docs](https://cloud.ouraring.com/docs/error-handling) and [Oura support article](https://support.ouraring.com/hc/en-us/articles/4415266939155-The-Oura-API) — 5000 req/5min rate limit verified (HIGH)
- [oura-ring (hedgertronic)](https://github.com/hedgertronic/oura-ring) — Python client (HIGH)
- [SparkCo OCR comparison](https://sparkco.ai/blog/comparing-ocr-apis-abbyy-tesseract-google-azure), [Best OCR 2026 (Unstract)](https://unstract.com/blog/best-pdf-ocr-software/), [Tesseract vs MS OCR 2026](https://ironsoftware.com/csharp/ocr/blog/compare-to-other-components/tesseract-vs-microsoft-ocr-comparison/) — Tesseract vs cloud OCR comparison (MEDIUM, vendor-influenced sources balanced across 3+)
- [Serialisation Strategy Matters: FHIR LLM (arXiv 2604.21076)](https://arxiv.org/html/2604.21076) — Ollama + FHIR R4 pipeline using Llama / Qwen quantized (MEDIUM, single academic source)
- [PostgreSQL pgcrypto docs](https://www.postgresql.org/docs/current/pgcrypto.html) and [column_encrypt v4.0](https://vibhorkumar.wordpress.com/2026/04/12/column_encrypt-v4-0-a-simpler-safer-model-for-column-level-encryption-in-postgresql/) — column-level encryption options (HIGH for pgcrypto, MEDIUM for column_encrypt)
- [LUKS Postgres docker (oneuptime 2026-02)](https://oneuptime.com/blog/post/2026-02-08-how-to-encrypt-docker-volumes-at-rest/view) and [Encrypting Postgres with LUKS (Medium)](https://medium.com/postgresql-blogs/encrypting-postgresql-data-directory-with-luks-on-linux-cabcbca119a1) — LUKS pattern (MEDIUM)
- [age vs gpg (Filo Substack)](https://gerowen.substack.com/p/age-vs-gpg-pgp-encryption), [Switching from GPG to age (Luke Hsiao)](https://luke.hsiao.dev/blog/gpg-to-age/) — age preferred for backups (HIGH, multiple sources)
- [BullMQ vs Celery (StackShare)](https://stackshare.io/celery/vs/bullmq) and [Cron alternatives 2026 (CloudRay)](https://cloudray.io/articles/cron-job-alternative) — orchestration trade-offs (MEDIUM)
- [Bitwarden Secrets Manager CLI Docker](https://bitwarden.com/help/developer-quick-start/) — sidecar pattern reference (HIGH, official)
- [Cloudflared docker compose patterns](https://github.com/jonas-merkle/container-cloudflare-tunnel) and [Cloudflare Tunnel Docker compose (Docker Recipes)](https://docker.recipes/devops/cloudflared-tunnel) — token-based tunnel (HIGH)

---
*Stack research for: self-hosted personal health data aggregator with multi-tenant SaaS pivot path*
*Researched: 2026-05-09*
