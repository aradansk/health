# Architecture Research

**Domain:** Self-hosted personal health data aggregator (Fasten OnPrem + custom FHIR analytics layer) with EU/SK multi-tenant SaaS pivot path
**Researched:** 2026-05-09
**Confidence:** HIGH on M1 component layout and data flow (verified against Fasten upstream README, Drizzle RLS docs, Traefik v3 docs); MEDIUM on per-tenant orchestration scaling numbers (30-50/CX22 is FEATURES.md estimate, needs M4 benchmark); MEDIUM on Fasten ingest API surface (Fasten OnPrem README explicitly: "not able to import data from healthcare providers directly. You can only use this application to manually enter data, or upload FHIR Bundles that have been exported though other means" — programmatic POST endpoint exists but is undocumented; manual upload via UI confirmed)

> **Architectural posture:** This document is opinionated. Where the FEATURES.md / STACK.md research left genuine open questions, I make a concrete recommendation and flag the alternative. The orchestrator + roadmapper consume this directly into Phase 1 sub-phasing.

---

## Headline Architectural Decisions

| # | Decision | Rationale | Confidence |
|---|----------|-----------|------------|
| **A1** | **Fasten SQLite = system of record for FHIR resources.** Custom Postgres analytics DB = **derived store** (read-mirror + cross-source joins). | Single FHIR write path = single audit trail; one schema invariant boundary. Fasten owns FHIR resource lifecycle (resource ID generation, versioning, encounter/practitioner cross-refs). Postgres holds tenant-owned cross-source analytics, tags, notes, ETL run state, audit log — things Fasten does not model. Avoids two-master sync hell. | HIGH |
| **A2** | **All ETLs write to Fasten via FHIR Bundle POST first, then mirror selected resources to Postgres on Fasten "resource created" event** (poll-based for M1, webhook later if Fasten exposes one). | Keeps Fasten conformant; analytics never sees a resource Fasten hasn't validated. Single source of truth holds. | MEDIUM-HIGH (Fasten ingest API needs a 2-day spike in Phase 1 before locking) |
| **A3** | **Multi-tenant strategy: PER-TENANT FASTEN INSTANCE + SHARED ANALYTICS POSTGRES with `tenant_id` + RLS** (not separate Postgres per tenant). | Fasten Multi-User is "work in progress" (FEATURES.md verdict). SQLite + multi-writer = wrong fit for shared. Postgres + RLS is industry-standard for shared analytics. Per-tenant Postgres = ops burden (N pg_dump cron jobs, N WAL streams, N upgrade paths) without compliance benefit beyond what RLS + audit gives. | HIGH for Fasten part, HIGH for Postgres part |
| **A4** | **`tenant_id` column + RLS hooks ACTIVE in M1 single-tenant.** Default tenant `andrej` provisioned at init. RLS policies enforce on every query via `SET LOCAL app.current_tenant`. | "Multi-tenant theater" (the column exists but isn't enforced) is worse than nothing — it gives false confidence. RLS policies + transaction wrappers active on day 1 means M4 just adds tenant provisioning, not a security retrofit. | HIGH |
| **A5** | **Build order = infra-first: Postgres + RLS + Traefik before any application code.** Phase 1 sub-phases are stack-bottom-up. | If RLS hooks don't work, every later phase rebuilds ETL writes. Cheaper to verify the foundation in week 1 than refactor in week 8. | HIGH |
| **A6** | **Encryption layers compose as: LUKS host volume (mandatory) + pgcrypto for `provider_name`, `freetext_notes`, `dna_findings.text` (defense-in-depth) + age for backups (mandatory, off-site).** No Postgres TDE (not in community PG). LUKS key = TPM-sealed (Linux prod) / BitLocker recovery key in Vaultwarden (Win dev). | Three independent layers; compromise of one layer doesn't expose the next. Vaultwarden cannot hold the LUKS key (chicken-and-egg: Vaultwarden needs the disk to be unlocked first). | HIGH |
| **A7** | **Logging baseline: pino with PII redaction allowlist, NOT denylist. Default = redact.** Metrics counters only, no values. Sentry/error tracking = explicit env-var opt-in, scrub before send. | PII Tier 1 means leak budget is zero. Allowlist (only fields explicitly marked safe leave the redaction filter) is the only design that survives a careless `logger.info({ patient })` call. | HIGH |
| **A8** | **ETL pipeline state lives in Postgres `etl_runs` and `etl_failures` tables (not files on disk).** cron + flock kicks off the script; the script itself is idempotent and resumable from `last_successful_observed_at`. | Files on disk are not transactional with the data they describe. If ETL crashes mid-write, the on-disk state and the DB drift. Single source of truth for "what we've ingested" = the same DB the data went into. | HIGH |

---

## Standard Architecture

### M1 System Overview (Single-User, Local PC)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         M1 — LOCAL PC HOST                           │
│                  (Windows + Docker Desktop + WSL2)                   │
│                         BitLocker on host volume                     │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                  EDGE LAYER (M2+ Public, M1 LAN-only)                │
├──────────────────────────────────────────────────────────────────────┤
│   ┌──────────────────┐                                                │
│   │ cloudflared      │  (commented in M1; uncommented Phase 1.9)      │
│   │ (CF Tunnel)      │  → terminates TLS at CF edge                   │
│   └────────┬─────────┘                                                │
│            │ HTTP (no LE in Traefik)                                  │
│            ▼                                                           │
│   ┌──────────────────┐                                                │
│   │ Traefik v3.7     │  Service-discovery via Docker labels           │
│   │ :80 (LAN-only)   │  Routes: /fasten/* → fasten:8080               │
│   │ :8080 dashboard  │          /*        → analytics:3000            │
│   │ (127.0.0.1 only) │                                                │
│   └────────┬─────────┘                                                │
└────────────┼──────────────────────────────────────────────────────────┘
             │ docker network: health-edge
   ┌─────────┼─────────────────────────────────────────────┐
   │         │                                              │
┌──▼──────┐ │ ┌────────────────────┐                        │
│ Fasten  │ │ │ Next.js 15.2.4     │ ◄──────┐              │
│ OnPrem  │ │ │ Analytics layer    │        │              │
│ :main   │ │ │  - App Router      │        │ HTTP         │
│ (digest │ │ │  - Drizzle 0.45    │        │ (read-only)  │
│  pinned)│ │ │  - tenant_id + RLS │        │              │
│         │ │ │  - Server Actions  │        │              │
│ /opt/   │ │ │    + tRPC          │        │              │
│  fasten/│ │ │  - Auth.js v5      │        │              │
│  db/    │ │ └────────┬───────────┘        │              │
│ (SQLite)│ │          │ pg connection      │              │
└────┬────┘ │          │ (postgres@3.4.9)   │              │
     │      │          │                    │              │
     │ FHIR │          ▼                    │              │
     │ POST │ ┌──────────────────────────┐  │              │
     │ /api │ │ postgres:16.13-bookworm  │  │              │
     │      │ │ DB: analytics            │  │              │
     │      │ │  ┌────────────────────┐  │  │              │
     │      │ │  │ tenant_id + RLS    │  │  │              │
     │      │ │  │ pgcrypto extension │  │  │              │
     │      │ │  └────────────────────┘  │  │              │
     │      │ │ Tables:                  │  │              │
     │      │ │  - tenants               │  │              │
     │      │ │  - observations (mirror) │  │              │
     │      │ │  - etl_runs              │  │              │
     │      │ │  - etl_failures (DLQ)    │  │              │
     │      │ │  - audit_log             │  │              │
     │      │ │  - tags, notes (M2)      │  │              │
     │      │ │  - dna_findings (M2)     │  │              │
     │      │ │  - dicom_metadata (M2)   │  │              │
     │      │ └──────────┬───────────────┘  │              │
     │      └─────────── │ ─────────────────┘              │
     │                   │                                  │
     │  ┌────────────────┼──────────────────────────┐      │
     │  │   ETL LAYER    │ (Python 3.13)            │      │
     │  ├────────────────┼──────────────────────────┤      │
     │  │                │                          │      │
     │  │  ┌──────────┐  │  ┌──────────┐  ┌────────┐│      │
     │  │  │ Apple    │  │  │ Oura     │  │ Lab PDF ││      │
     │  │  │ Health   │  │  │ daily    │  │ OCR     ││      │
     │  │  │ XML→FHIR │  │  │ sync     │  │ (Tess+  ││      │
     │  │  │ (manual  │  │  │ (cron)   │  │ Ollama) ││      │
     │  │  │  drop)   │  │  │          │  │ (cron)  ││      │
     │  │  └────┬─────┘  │  └────┬─────┘  └───┬────┘ │      │
     │  │       │        │       │            │      │      │
     │  │       └────────┴───────┴────────────┘      │      │
     │  │                │                            │      │
     │  │       1) POST FHIR Bundle ──────────────────┘      │
     │  │       2) Update etl_runs in Postgres               │
     │  │       3) On error: insert etl_failures (DLQ)       │
     │  └─────────────────────────────────────────────┘      │
     │                                                        │
┌────▼─────────────────────────────────────────────────────┐ │
│  HOST VOLUMES (LUKS / BitLocker encrypted at rest)        │ │
├────────────────────────────────────────────────────────────┤ │
│  fasten-db        (SQLite + Fasten cache)                 │ │
│  postgres-data    (analytics DB)                          │ │
│  data/imports/    (Apple Health zip drop, lab PDFs) :ro   │ │
│  data/dicom/      (M2)                              :ro   │ │
│  output/etl/      (transformed FHIR bundles, OCR text)    │ │
└────────────────────────────────────────────────────────────┘
                                                              │
┌─────────────────────────────────────────────────────────────┘
│  EXTERNAL SECRET STORE (cross-project, M2+)
├─────────────────────────────────────────────────────────────
│  Vaultwarden on docker-srv-01:8094
│   - Health stack uses bw CLI sidecar (M2+) OR manual .env (M1)
│   - LUKS recovery key NOT here (chicken-and-egg)
└─────────────────────────────────────────────────────────────

         ┌────────────────────────────────────────────────┐
         │  OFF-SITE BACKUP (Hetzner Storage Box / S3 / B2)│
         ├────────────────────────────────────────────────┤
         │  age-encrypted nightly:                         │
         │   - pg_dump analytics                           │
         │   - cp Fasten SQLite (via sqlite3 .backup)      │
         │   - rclone push to B2 (M2+)                     │
         └────────────────────────────────────────────────┘
```

### M4 System Overview (Multi-Tenant SaaS)

```
                    ┌──────────────────────────────────┐
                    │    Hetzner CX22 (~5€/mo, EU DE)  │
                    │    LUKS-encrypted volume         │
                    └──────────────────────────────────┘

         ┌──────────────────────────────────────────────────────┐
         │ EDGE                                                  │
         │  cloudflared → Traefik v3.7                          │
         │   Host(`tenant1.health.ardan.sk`) → fasten-tenant1   │
         │   Host(`tenant2.health.ardan.sk`) → fasten-tenant2   │
         │   Host(`*.health.ardan.sk`)       → analytics shared │
         └──────────────────────────────────────────────────────┘
                  │
   ┌──────────────┼─────────────────────────────────────────────┐
   │              │                                              │
┌──▼─────┐   ┌────▼─────┐   ┌──────────┐                         │
│ fasten │   │ fasten   │   │ fasten   │   ... up to ~30-50      │
│ tenant1│   │ tenant2  │   │ tenantN  │   per CX22 (estimate)   │
│ SQLite │   │ SQLite   │   │ SQLite   │                         │
│ vol-T1 │   │ vol-T2   │   │ vol-TN   │                         │
└────────┘   └──────────┘   └──────────┘                         │
   │              │              │                               │
   │ FHIR POST    │              │                               │
   ▼              ▼              ▼                               │
┌────────────────────────────────────────────────────────┐       │
│ Authentik (SSO, M4)                                    │       │
│   - issues per-tenant JWT with tenant_id claim         │       │
│   - federates to per-tenant Fasten via OIDC            │       │
└────────────────────────────────────────────────────────┘       │
                  │                                               │
                  ▼                                               │
┌────────────────────────────────────────────────────────────┐   │
│ Next.js Analytics (shared, multi-tenant)                   │   │
│   - extracts tenant_id from JWT                            │   │
│   - SET LOCAL app.current_tenant = <tenant_id>             │   │
│   - all Drizzle queries RLS-enforced                       │   │
└──────────┬─────────────────────────────────────────────────┘   │
           │                                                      │
           ▼                                                      │
┌────────────────────────────────────────────────────────────┐   │
│ postgres:16.13 (shared analytics DB)                       │   │
│   - SAME schema as M1                                      │   │
│   - RLS already enforced (no schema migration)             │   │
│   - tenants table grows from 1 row → N                     │   │
└────────────────────────────────────────────────────────────┘   │
                                                                  │
┌────────────────────────────────────────────────────────────────┘
│ Tenant orchestration layer (M4 — Next.js admin UI + scripts)
│   - Provision new tenant: insert into tenants, generate compose
│     fragment, docker compose up -d fasten-tenantN, Traefik label
│     auto-detected, age-encrypted secrets per tenant
│   - Decommission: docker compose down + age archive of vol +
│     pgcrypto delete tenant rows
└────────────────────────────────────────────────────────────────
```

### Component Responsibilities

| Component | Owns | Does NOT own | M1 / M4 difference |
|-----------|------|--------------|---------------------|
| **Fasten OnPrem (SQLite)** | FHIR resource CRUD, resource ID generation, encounter timeline, manual record wizard, FHIR Bundle upload UI, resource versioning, single-user auth | Cross-source correlation, tags/notes, ETL run state, multi-tenant routing, audit trail beyond Fasten user actions | M4: one container per tenant, same image, isolated SQLite volume |
| **Postgres analytics DB** | `tenant_id`-keyed cross-source query plane, ETL state, audit log, derived analytics (correlation views), tags/notes, DNA findings, DICOM metadata index | FHIR resource lifecycle (Fasten owns), session state (Auth.js owns), file blobs (Fasten + DICOM stores own) | M4: same DB, RLS already enforced, just adds tenants rows |
| **Next.js analytics layer** | Custom dashboards, time-series viz (T8), cross-source charts (D4), tag UI (M2 D6), search across all sources, audit log review, admin (M4 tenant provisioning) | Auth (delegated to Auth.js v5 / Authentik), FHIR resource editing (delegated to Fasten UI via iframe / link-out) | M4: tenant_id from JWT instead of fixed `andrej` env var |
| **Traefik** | HTTP routing, host/path-based dispatch, service discovery via Docker labels, request logging | TLS (Cloudflare does it), auth (Auth.js / Authentik does it) | M4: subdomain routing per tenant via wildcard `Host(*.health.ardan.sk)` + label-driven service registration |
| **cloudflared sidecar** | Public ingress tunnel, TLS termination at CF edge | TLS at backend, internal routing | Same in M1 (off) and M4 (on) |
| **Python ETL workers** | Source format → FHIR R4 mapping, OCR pipeline, Oura OAuth refresh, idempotent retries, write to `etl_runs` / `etl_failures` | FHIR storage (always POSTs to Fasten), schema migrations (Drizzle owns) | M4: take tenant_id from job config, run per-tenant cron |
| **Vaultwarden + bw sidecar (M2+)** | App secrets (Fasten admin, Oura tokens, Postgres password, NextAuth secret) | LUKS recovery key (chicken-and-egg), TLS certs (CF owns) | M4: per-tenant secrets in Vaultwarden under tenant-namespaced item names |
| **age-encrypted backup pipeline** | Nightly snapshot of Postgres + Fasten SQLite, encrypted to public key, off-site upload | Real-time replication, point-in-time recovery beyond previous-day granularity | M4: per-tenant volume snapshot (still single age recipient, multi-tenant entries) |
| **Ollama (sidecar, on-demand)** | Local vision LLM for lab PDF table validation | General LLM analytics (anti-feature A1) | Same M1/M4 |

---

## Recommended Project Structure

```
Projects/health/
├── compose.yaml                          # Top-level Compose v2 file
├── compose.override.yaml                 # Local dev overrides (M1; gitignored .local variants)
├── .env.example                          # Placeholders only
├── .env                                  # gitignored — real secrets via Vaultwarden lookup
├── .gitignore                            # Strict: data/, output/, *.pdf, *.dcm, .env, secrets/
├── .gitattributes                        # `* text=auto eol=lf` (Win→Linux line ending safety)
├── .dockerignore
├── CLAUDE.md                             # PII Tier 1 cross-aware rules (already written)
├── BOOTSTRAP.md                          # Handoff context (already written)
├── MEMORY.md                             # Per-project quick facts
│
├── .planning/
│   ├── PROJECT.md
│   ├── research/
│   │   ├── STACK.md
│   │   ├── FEATURES.md
│   │   ├── ARCHITECTURE.md               # ← THIS FILE
│   │   ├── PITFALLS.md
│   │   └── SUMMARY.md
│   └── M1/
│       ├── ROADMAP.md
│       └── phases/
│           └── 1.1_infra-skeleton/
│           └── 1.2_postgres-rls/
│           └── ...
│
├── projects/
│   ├── infra/
│   │   ├── postgres/
│   │   │   ├── init/
│   │   │   │   ├── 01_databases.sh       # CREATE DATABASE analytics, extensions
│   │   │   │   └── 02_roles.sh           # app_authenticated role, RLS scaffolding
│   │   │   └── postgresql.conf           # (mounted via volume — see STACK.md tuning section)
│   │   ├── traefik/
│   │   │   └── (no static config; all via Docker labels)
│   │   └── backup/
│   │       ├── backup.sh                  # pg_dump + sqlite .backup + age encrypt
│   │       ├── restore.sh                 # decrypt + restore (smoke-test monthly)
│   │       └── crontab                    # 03:00 nightly
│   │
│   ├── analytics/                         # Next.js custom analytics layer
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── drizzle.config.ts
│   │   ├── src/
│   │   │   ├── app/                       # App Router
│   │   │   │   ├── layout.tsx
│   │   │   │   ├── (auth)/               # Auth.js v5 routes
│   │   │   │   ├── (dashboard)/
│   │   │   │   │   ├── page.tsx          # T1 dashboard shell
│   │   │   │   │   ├── trends/page.tsx   # T8 time-series
│   │   │   │   │   └── correlate/page.tsx# D4 cross-source (M2-M3)
│   │   │   │   ├── api/
│   │   │   │   │   ├── etl/health        # POST endpoint: signed bundle ingest
│   │   │   │   │   └── audit/            # GDPR Art. 32 evidence pack
│   │   │   │   └── admin/                # M4: tenant provisioning UI
│   │   │   ├── db/
│   │   │   │   ├── schema.ts             # Drizzle schema (tenants, observations, audit_log, etl_runs, ...)
│   │   │   │   ├── policies.ts           # pgPolicy / crudPolicy definitions
│   │   │   │   ├── client.ts             # postgres@3.4.9 + drizzle init
│   │   │   │   └── tenant-context.ts     # withTenant() transaction wrapper
│   │   │   ├── lib/
│   │   │   │   ├── logger.ts             # pino + redaction allowlist
│   │   │   │   ├── audit.ts              # writeAudit(actor, resource, action)
│   │   │   │   ├── fhir-client.ts        # FHIR R4 client to Fasten
│   │   │   │   └── validate.ts           # zod boundary validators
│   │   │   └── components/
│   │   ├── drizzle/                      # generated migrations (committed)
│   │   └── tests/
│   │       └── rls.test.ts               # ★ critical test: RLS leak proofs
│   │
│   ├── etl/                              # Python ETL workers
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── health/
│   │   │   │   ├── etl/
│   │   │   │   │   ├── apple_health.py   # XML → FHIR Observation mapper
│   │   │   │   │   ├── oura.py           # OAuth + daily sync
│   │   │   │   │   ├── lab_pdf.py        # Tesseract + Ollama orchestrator
│   │   │   │   │   ├── runs.py           # etl_runs / etl_failures DB writers
│   │   │   │   │   └── fhir_client.py    # POST FHIR Bundle to Fasten
│   │   │   │   ├── mappers/
│   │   │   │   │   ├── healthkit_to_fhir.py   # 50+ HKQuantityType → FHIR Observation.code
│   │   │   │   │   └── oura_to_fhir.py        # Oura sleep/readiness → FHIR
│   │   │   │   ├── ocr/
│   │   │   │   │   ├── tesseract.py
│   │   │   │   │   ├── ollama_validate.py     # vision LLM table reconstruction
│   │   │   │   │   └── loinc_lookup.py        # cached LOINC code mapper
│   │   │   │   └── secrets.py            # Vaultwarden bw lookup OR env fallback
│   │   │   └── main.py                   # entrypoint dispatcher: argv 'oura' / 'apple-health' / 'lab-ocr'
│   │   ├── crontab                       # 06:00 oura, every 5min apple-health drop poll, on-demand lab
│   │   └── tests/
│   │
│   └── orchestration/                    # M4 only: tenant provisioning scripts (skeleton in M1)
│       ├── provision_tenant.sh           # docker compose up -d fasten-${TENANT}
│       ├── decommission_tenant.sh
│       └── compose.tenant.template.yaml
│
├── data/                                 # ★ gitignored, LUKS-encrypted volume
│   ├── imports/
│   │   ├── incoming/                     # Drop apple_health_export.zip here
│   │   └── processing/                   # ETL atomic-stages here
│   ├── dicom/                            # M2 DICOM CD/disc rips (read-only mount)
│   └── lab/                              # Lab PDFs (read-only mount, OCR processes)
│
├── output/                               # gitignored
│   ├── etl/                              # Processed FHIR bundles, OCR text artifacts
│   ├── reports/                          # Generated reports
│   └── screenshots/                      # /superpowers screenshots, dev-only
│
├── docs/                                 # Reference docs (Fasten admin notes, FHIR mapping cheatsheets)
│   ├── fasten-admin.md
│   ├── fhir-mappings/
│   │   ├── apple-health-to-fhir.md
│   │   └── oura-to-fhir.md
│   └── runbooks/
│       ├── disaster-recovery.md
│       ├── ocr-stuck.md                  # Dead-letter manual review playbook
│       └── tenant-provision.md           # M4
│
└── memory/                               # Per-project memory (gitignored if PII references)
```

### Structure Rationale

- **`projects/infra/` is its own subtree** so M4 migration to Hetzner moves these files unchanged. Compose lives at root for convenience but the per-service Dockerfiles, init scripts, and tuning live under `projects/`.
- **`projects/analytics/` and `projects/etl/` are independently buildable Docker images.** They share Postgres but compile/dependency-graphs are isolated. Lets you upgrade Next.js without touching Python deps.
- **`data/` and `output/` are sibling-of-projects** so a `chmod -R o-rwx data/` and a `mkfs.luks` underneath catch them as one unit. Never under `projects/` (would tempt accidental commit).
- **`drizzle/` (generated migrations) is committed**, but `drizzle-kit push` is dev-only. Production = `drizzle-kit migrate` against committed SQL. PII Tier 1 needs reviewable migrations.
- **`projects/orchestration/` is empty/stub in M1**, reified in M4. Keeping the folder reserved sets expectations; copying single-tenant `compose.yaml` into `compose.tenant.template.yaml` and parametrizing is the M4 step, not a rewrite.

---

## Architectural Patterns

### Pattern 1: Fasten as System of Record + Postgres as Analytics Mirror

**What:** All FHIR resources are written to Fasten first (POST FHIR Bundle to Fasten ingest), then a poll-based mirror process selects observations relevant for cross-source analytics and projects them into Postgres `observations` table (foreign key to Fasten resource ID, no resource body duplicated for non-mirrored resources).

**When to use:** Any time you have an authoritative domain DB with a fixed schema (Fasten = FHIR R4) + need a flexible analytics/correlation layer with custom dimensions (tags, tenant_id, cross-source joins).

**Trade-offs:**
- **Pro:** Single FHIR write path. Fasten's data invariants protected. Analytics layer can be rebuilt from Fasten anytime (idempotent re-mirror).
- **Pro:** Fasten upgrades don't break analytics; analytics schema evolves independently.
- **Con:** Mirror lag (poll interval = 60s in M1) means analytics queries may miss the most-recent ETL output.
- **Con:** Two DBs to back up (mitigated: same backup script handles both).
- **Con:** If Fasten ingest API is undocumented (status: yes, README confirms manual upload only), need a 2-day Phase 1 spike to identify POST endpoint or fall back to "drop FHIR bundle JSON into Fasten import folder via volume mount" approach.

**Example (TypeScript — analytics mirror reader):**

```typescript
// src/lib/fasten-mirror.ts
import { db } from '@/db/client';
import { observations } from '@/db/schema';
import { withTenant } from '@/db/tenant-context';
import { eq, gt } from 'drizzle-orm';

/**
 * Mirror process: poll Fasten resources newer than last_mirrored_at,
 * project relevant fields into Postgres observations table.
 * Runs as cron job inside ETL container, not Next.js (separation of concerns).
 */
export async function mirrorFastenToPostgres(tenantId: string) {
  return withTenant(tenantId, async (tx) => {
    const lastMirrored = await tx.query.etlRuns.findFirst({
      where: eq(etlRuns.kind, 'fasten_mirror'),
      orderBy: (e, { desc }) => desc(e.completedAt),
    });

    const since = lastMirrored?.completedAt ?? new Date('2000-01-01');
    const fastenObs = await fetchFastenObservationsSince(since);  // FHIR /Observation?_lastUpdated=gt...

    for (const obs of fastenObs) {
      await tx.insert(observations).values({
        tenantId,
        fastenResourceId: obs.id,
        loincCode: obs.code?.coding?.[0]?.code ?? null,
        valueQuantity: obs.valueQuantity?.value ?? null,
        observedAt: new Date(obs.effectiveDateTime),
        source: obs.meta?.source ?? 'unknown',
      }).onConflictDoUpdate({
        target: observations.fastenResourceId,
        set: { /* upsert */ },
      });
    }

    await tx.insert(etlRuns).values({
      tenantId,
      kind: 'fasten_mirror',
      completedAt: new Date(),
      recordCount: fastenObs.length,
    });
  });
}
```

### Pattern 2: Tenant-Context Transaction Wrapper (RLS Enforcement)

**What:** Every database operation that touches tenant data goes through `withTenant(tenantId, fn)` which opens a transaction and issues `SET LOCAL app.current_tenant = '<uuid>'`. RLS policies on every table reference `current_setting('app.current_tenant')`, so even a bug that forgets the `where tenant_id = ...` clause cannot leak.

**When to use:** Any multi-tenant Postgres app. Mandatory for PII Tier 1.

**Trade-offs:**
- **Pro:** Defense in depth — application layer bug ≠ data leak. RLS catches.
- **Pro:** RLS policies enforce on `INSERT` / `UPDATE` / `DELETE` too (with `WITH CHECK`), not just SELECT.
- **Con:** Every query must run inside a transaction. Connection-pool patterns that issue queries without explicit transactions (e.g. `db.select()` without `.transaction()`) bypass RLS.
- **Con:** `SET LOCAL` only persists in the transaction; if a connection is reused across requests without proper reset, leakage is possible. Use connection pooling carefully.
- **Mitigation:** Add a critical test (`rls.test.ts`) that opens a transaction with tenant A, attempts to read tenant B's row, asserts empty result. Run in CI as a regression gate.

**Example (Drizzle + postgres@3.4.9):**

```typescript
// src/db/tenant-context.ts
import { db } from './client';
import { sql } from 'drizzle-orm';

export async function withTenant<T>(
  tenantId: string,
  fn: (tx: typeof db) => Promise<T>
): Promise<T> {
  return db.transaction(async (tx) => {
    // SET LOCAL is transaction-scoped; safe across concurrent requests
    await tx.execute(sql`set local app.current_tenant = ${tenantId}`);
    await tx.execute(sql`set local role app_authenticated`);
    return fn(tx);
  });
}

// src/db/schema.ts (excerpt — observations with RLS)
import { pgTable, pgPolicy, pgRole, uuid, text, timestamp, jsonb, integer } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';

export const appAuthenticated = pgRole('app_authenticated').existing();

export const observations = pgTable('observations', {
  id: uuid('id').primaryKey().defaultRandom(),
  tenantId: uuid('tenant_id').notNull().references(() => tenants.id, { onDelete: 'cascade' }),
  fastenResourceId: text('fasten_resource_id').notNull().unique(),
  source: text('source').notNull(),
  loincCode: text('loinc_code'),
  valueQuantity: integer('value_quantity'),
  observedAt: timestamp('observed_at').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
}, (t) => ({
  tenantIsolation: pgPolicy('tenant_isolation', {
    as: 'permissive',
    to: appAuthenticated,
    for: 'all',
    using: sql`${t.tenantId} = current_setting('app.current_tenant')::uuid`,
    withCheck: sql`${t.tenantId} = current_setting('app.current_tenant')::uuid`,
  }),
})).enableRLS();
```

```sql
-- Generated migration (review before applying)
ALTER TABLE observations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON observations
  AS PERMISSIVE FOR ALL TO app_authenticated
  USING (tenant_id = current_setting('app.current_tenant')::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
```

### Pattern 3: ETL Idempotency via `etl_runs` Watermarks

**What:** Each ETL job records a "watermark" (`last_observed_at`) in the `etl_runs` table after a successful run. Next run starts from `watermark + 1ms`. Crashes are recoverable: re-run resumes from last successful watermark, never re-processes a record already committed.

**When to use:** Any periodic data sync (Oura daily, Apple Health import, lab OCR). Mandatory for at-least-once delivery.

**Trade-offs:**
- **Pro:** Crash-recovery is automatic. No "stuck import" mystery.
- **Pro:** Backfill is identical to incremental (set watermark to `2020-01-01`, ETL fetches all).
- **Con:** Must track watermarks per-source (Apple Health uses iOS export timestamp, Oura uses `day` field, lab uses upload timestamp).
- **Con:** Idempotency relies on `ON CONFLICT DO UPDATE` upserts in mirror writes — schema must have unique constraint on `(tenant_id, source, native_id)` or similar.

**Example:**

```python
# projects/etl/src/health/etl/oura.py
from datetime import datetime, timedelta, timezone
from health.etl.runs import EtlRun, last_watermark, record_run, record_failure
from health.etl.fhir_client import FastenClient

def run(tenant_id: str):
    fasten = FastenClient.from_env()
    last = last_watermark(tenant_id, 'oura_daily') or datetime(2024, 1, 1, tzinfo=timezone.utc)
    today = datetime.now(timezone.utc).date()
    start = (last + timedelta(days=1)).date()

    if start > today:
        return  # Already up-to-date

    try:
        for day in daterange(start, today):
            sleep = oura_api.get_sleep(day)
            readiness = oura_api.get_readiness(day)
            bundle = build_fhir_bundle(tenant_id, day, sleep, readiness)  # validate via fhir.resources
            fasten.post_bundle(bundle)
            record_run(tenant_id, 'oura_daily', watermark=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc))
    except Exception as e:
        record_failure(tenant_id, 'oura_daily', str(e), payload_redacted=True)
        raise  # exit non-zero so cron sends mail
```

### Pattern 4: Per-Tenant Fasten Container Orchestration (M4)

**What:** Each tenant gets its own Fasten container (~150 MB idle, isolated SQLite volume). Traefik subdomain routing dispatches `tenant{N}.health.ardan.sk` to `fasten-tenant{N}:8080`. Provisioning script writes a Docker compose fragment, `docker compose up -d fasten-tenant{N}`, Traefik label-driven discovery picks it up.

**When to use:** M4 SaaS pivot. **NOT M1.**

**Trade-offs:**
- **Pro:** Strongest data isolation — tenant data is in tenant's own container + volume. Compliance story (GDPR Art. 32 separation of concerns).
- **Pro:** Tenant offboarding = `docker compose down + age archive` (Art. 17 right to erasure trivial).
- **Pro:** Per-tenant Fasten upgrades possible (one tenant on `:main`, another on `:v1.2.0`).
- **Con:** Resource overhead. ~150 MB idle per tenant; CX22 (4 GB) ceiling = ~30-50 tenants per FEATURES.md estimate (needs M4 benchmark).
- **Con:** N WAL streams across N SQLite files = harder backup orchestration. Mitigation: per-tenant `sqlite3 .backup` then single-pass age-encrypt directory.

**Example (Traefik labels in compose.tenant.template.yaml):**

```yaml
# projects/orchestration/compose.tenant.template.yaml
# Run: TENANT=acme docker compose -f compose.yaml -f compose.tenant.template.yaml up -d
services:
  fasten-${TENANT}:
    image: ghcr.io/fastenhealth/fasten-onprem:main@sha256:REPLACE_WITH_DIGEST
    container_name: health-fasten-${TENANT}
    restart: unless-stopped
    environment:
      - HOSTNAME=fasten-${TENANT}
      - HOST_IP=0.0.0.0
      - HOST_PORT=8080
    volumes:
      - fasten-db-${TENANT}:/opt/fasten/db
      - fasten-cache-${TENANT}:/opt/fasten/cache
    networks:
      - health-edge
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.fasten-${TENANT}.rule=Host(`${TENANT}.health.ardan.sk`) && PathPrefix(`/fasten`)"
      - "traefik.http.routers.fasten-${TENANT}.entrypoints=web"
      - "traefik.http.services.fasten-${TENANT}.loadbalancer.server.port=8080"
      - "traefik.http.middlewares.fasten-${TENANT}-strip.stripprefix.prefixes=/fasten"
      - "traefik.http.routers.fasten-${TENANT}.middlewares=fasten-${TENANT}-strip"
      # Resource limits per FEATURES.md estimate
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.5'

volumes:
  fasten-db-${TENANT}:
  fasten-cache-${TENANT}:
```

### Pattern 5: PII Redaction Allowlist (Logging)

**What:** pino logger configured with `redact: { paths: [...], remove: true }` for **everything** by default; a tiny set of fields (request ID, tenant ID UUID, timestamp, status code, HTTP method, route name) are explicitly allowed through.

**When to use:** PII Tier 1 mandatory. **Not optional.**

**Trade-offs:**
- **Pro:** Hardest possible default. A careless `logger.info({ patient: fhirResource })` produces `[REDACTED]`, not a leak.
- **Con:** Debugging takes more work. Devs add explicit `safe: { metricName: ..., recordCount: ... }` envelopes for diagnostic info.
- **Con:** Sentry / error tracking integrations need explicit before-send hooks; default Sentry sends way too much.

**Example:**

```typescript
// src/lib/logger.ts
import pino from 'pino';

const ALLOWLIST = [
  'requestId', 'tenantId', 'route', 'method', 'statusCode', 'durationMs',
  'kind', 'recordCount', 'level', 'time', 'pid', 'hostname', 'msg',
];

export const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  // Redact EVERYTHING that's not on the allowlist
  redact: {
    paths: ['*'],
    censor: (value, path) => {
      const top = path[0];
      if (ALLOWLIST.includes(String(top))) return value;
      return '[REDACTED]';
    },
  },
  formatters: {
    level: (label) => ({ level: label }),
  },
});

// Usage — explicit safe envelope, never raw FHIR
logger.info({ requestId, tenantId, route: '/api/etl/oura', recordCount: 14 }, 'oura sync ok');
// NOT: logger.info({ patient }, 'sync done');  ← would log [REDACTED]
```

---

## Data Flow

### Apple Health XML → FHIR Bundle → Fasten → Mirror → Analytics

```
[User exports Health from iPhone, AirDrops zip to PC]
    │
    ▼
[Drop file in data/imports/incoming/apple_health_export.zip]
    │
    ▼ (host bind-mount, :ro)
[Python ETL polls every 5min via os.scandir + mtime]
    │
    ▼
[Atomic stage: copy → tmp → os.replace into data/imports/processing/<ts>_export.zip]
    │
    ▼
[apple-health-parser: zip → DataFrame of <Record> elements]
    │
    ▼
[Mapper: HKQuantityTypeIdentifierStepCount → FHIR Observation
                                              code = LOINC 55423-8 "Steps"
                                              valueQuantity { value, unit: 'count' }
                                              effectiveDateTime = startDate
                                              subject = Patient/<tenant_andrej>]
    │
    ▼
[Validate via fhir.resources pydantic models — REJECT bundle if invalid]
    │
    ▼
[POST FHIR Bundle to Fasten ingest endpoint]
    │
    ├─ on success:
    │     ▼
    │   [INSERT etl_runs (tenant_id='andrej', kind='apple_health',
    │                     completed_at=now(), record_count=N, watermark=...)]
    │
    └─ on failure:
          ▼
        [INSERT etl_failures (tenant_id, kind, payload_redacted, error_msg)]
        [exit non-zero → cron mailx alert]

[Separately, every 60s Postgres-side mirror reader:]
    │
    ▼
[GET /api/secure/Observation?_lastUpdated=gt<since> from Fasten]
    │
    ▼
[withTenant('andrej', tx => INSERT INTO observations
   (tenant_id, fasten_resource_id, source='apple_health', loinc_code,
    value_quantity, observed_at) ON CONFLICT (fasten_resource_id) DO UPDATE)]
    │
    ▼
[Custom analytics dashboards now query Postgres for cross-source correlation]
```

### Oura API → FHIR Bundle → Fasten → Mirror → Analytics

```
[06:00 cron in ETL container fires `python -m health.etl.oura`]
    │
    ▼
[Read OURA_REFRESH_TOKEN from /run/secrets (M2: bw sidecar; M1: env)]
    │
    ▼
[OAuth2 refresh flow → access_token (stale tokens auto-renewed)]
    │
    ▼
[GET https://api.ouraring.com/v2/usercollection/sleep?start_date=...&end_date=...
 GET .../daily_readiness/?...
 GET .../heartrate/?... (with rate-limit backoff)]
    │
    ▼
[Mapper: Oura sleep_score → FHIR Observation
   code = LOINC 93832-4 "Sleep duration" + custom Oura code
   valueQuantity {...}
   subject = Patient/<tenant_andrej>]
    │
    ▼
[Validate → POST FHIR Bundle → record_run / record_failure → mirror picks up]
```

### Lab PDF → OCR → Ollama → FHIR → Fasten → Mirror

```
[User drops scan.pdf into data/lab/incoming/]
    │
    ▼
[ETL on-demand or hourly poll]
    │
    ▼
[pdfplumber: extract text + table cells]
    │
    ├─ pdfplumber returns clean text → skip OCR
    │
    └─ pdfplumber returns junk (image PDF) →
         [pdf2image → PNG → Tesseract 5 with -l slk+eng]
    │
    ▼ (text + table data)
[Ollama qwen2.5:7b prompt:
   "You are a Slovak lab report parser. Extract a JSON list of
    { test_name, value, unit, reference_low, reference_high, observed_at }.
    Map test_name to LOINC code using this lookup table: {...}.
    Output only valid JSON."]
    │
    ▼
[fhir.resources validate — for each row, build FHIR Observation]
    │
    ├─ < 80% LOINC mapped → mark for manual review
    │     ▼
    │   [INSERT etl_failures (tenant_id, kind='lab_ocr',
    │                         pdf_path, parsed_json, status='needs_review')]
    │   [Notify: write to runbook docs/runbooks/ocr-stuck.md backlog]
    │
    └─ >= 80% mapped →
         [POST FHIR Bundle to Fasten]
         [Move PDF to data/lab/processed/]
         [INSERT etl_runs]
```

### Multi-Tenant Read Flow (M4)

```
[User browser → tenant1.health.ardan.sk]
    │
    ▼
[Cloudflare Tunnel → Traefik]
    │
    ▼ (Host header preserves tenant1)
[Traefik Host(`tenant1.health.ardan.sk`) matches]
    │
    ├─ /fasten/* → fasten-tenant1:8080 (per-tenant container)
    │
    └─ /* → analytics:3000 (shared Next.js)
          │
          ▼
        [Auth.js v5 middleware extracts JWT]
          │
          ▼
        [JWT contains { sub: <user_id>, tenant_id: <uuid>, ... }]
          │
          ▼
        [Server Component / API route:
           withTenant(tenantId, async (tx) => {
             return tx.select().from(observations).where(...)
                              // RLS auto-filters: tenant_id = current_setting()
           })]
          │
          ▼
        [Postgres applies RLS: returns only rows where tenant_id = JWT.tenant_id]
          │
          ▼
        [Response → user]
```

---

## Encryption Layer Composition

### Three Layers of Defense

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: HOST FILESYSTEM ENCRYPTION (mandatory, M1 day 1)       │
├─────────────────────────────────────────────────────────────────┤
│  Linux prod (Hetzner CX22):                                     │
│    LUKS2 on /dev/sdb (data volume)                              │
│    Cipher: aes-xts-plain64, key-size 512                        │
│    Key: TPM-sealed at boot (or SSH-entered passphrase)          │
│    Mount: /var/lib/health-data                                  │
│    Bind-mount into containers                                   │
│                                                                 │
│  Windows dev (Docker Desktop + WSL2):                           │
│    BitLocker on C:\ (whole disk)                                │
│    Recovery key: stored in Vaultwarden ext (not Health VW)      │
│    Docker Desktop's WSL2 distro inherits encryption             │
│                                                                 │
│  Performance: AES-NI = 2-5% overhead. Acceptable for PII.      │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: pgcrypto COLUMN-LEVEL (defense-in-depth, M1 selective) │
├─────────────────────────────────────────────────────────────────┤
│  Apply ONLY to ultra-sensitive free-text columns:               │
│    - audit_log.actor_email                                      │
│    - notes.freetext (M2)                                        │
│    - dna_findings.text (M2)                                     │
│    - encounters.provider_name_freetext                          │
│  Skip for indexed columns (LOINC code, value_quantity) —        │
│    pgcrypto encryption breaks BTREE index ordering              │
│                                                                 │
│  Pattern: pgp_sym_encrypt('plaintext', key)                     │
│  Key derivation: env-var-derived KDF (key in Vaultwarden)       │
│  Trade-off: query-time decrypt cost ~0.1 ms/row                 │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: BACKUP ENCRYPTION (mandatory, M2 day 1)                │
├─────────────────────────────────────────────────────────────────┤
│  age (FiloSottile/age) — modern AEAD, ssh-key compatible        │
│                                                                 │
│  Nightly backup.sh:                                             │
│    1. pg_dump analytics | age -r <pubkey> > backup.pg.age       │
│    2. sqlite3 fasten.db ".backup /tmp/f.db" && \                │
│         age -r <pubkey> /tmp/f.db > fasten.sqlite.age           │
│    3. rclone copy *.age b2:health-backups/$(date +%Y/%m/%d)/    │
│    4. local 7-day retention; B2 lifecycle policy: 90 days       │
│                                                                 │
│  Recipient pubkey = age public key (committable).               │
│  Private key = on a SEPARATE air-gapped device                  │
│    (printed paper QR + USB stick in safe).                      │
│  NOT in Vaultwarden (would couple "lost VW = lost backup keys") │
│                                                                 │
│  Restore drill: monthly /superpowers:verification-before-       │
│   completion test on staging.                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Management Diagram

```
                ┌──────────────────────────────────┐
                │  KEY HIERARCHY (don't cross-link) │
                └──────────────────────────────────┘

LUKS host volume key
   ├─ Linux prod: TPM-sealed → unlocks at boot via tpm2-totp or
   │              passphrase entered via SSH at boot (initramfs dropbear)
   └─ Windows dev: BitLocker, recovery key stored in personal
                   password manager (NOT Health Vaultwarden, NOT in repo)

pgcrypto column-level key
   ├─ Stored as env var PGCRYPTO_KEY in app container
   ├─ M1: manual lookup from Vaultwarden, written to .env
   └─ M2+: bw sidecar fetches at startup, writes to /run/secrets/

age backup recipient key
   ├─ Public key: committable, in compose.yaml or .env
   └─ Private key: air-gapped paper QR + USB stick in physical safe
       (Vaultwarden would defeat the purpose: VW down = backup down)

Application secrets (Fasten admin, Oura tokens, NextAuth secret)
   ├─ M1: manual .env (gitignored), looked up from Vaultwarden by hand
   └─ M2+: bw sidecar init container writes to tmpfs /run/secrets/
```

**Why no Vaultwarden for LUKS recovery key:**
Vaultwarden runs on docker-srv-01:8094. If docker-srv-01 disk fails and you need to restore the Health host from backup, you need the backup decrypt key (age private), and you need the disk LUKS key. If both live in Vaultwarden, and Vaultwarden also went down with docker-srv-01 (or you're restoring on a brand-new machine), you're locked out. **Air-gap the recovery keys.**

---

## Failure Modes & Recovery

| Failure | Trigger / Detection | Impact | Recovery |
|---------|---------------------|--------|----------|
| **Fasten container OOM** | `docker logs fasten` shows OOMKilled; healthcheck fails | Custom ETL writes fail (POST 502); analytics reads stale data | `restart: unless-stopped` policy auto-restarts. SQLite file persists on volume. If repeated, raise `mem_limit`. |
| **Postgres volume corruption** | `pg_isready` healthcheck fails; logs show WAL replay errors | Analytics down. ETL writes still go to Fasten. Mirror lags. | Restore last age-encrypted backup; replay ETL since `last_completed_at` watermark to fill gap. **Monthly restore drill mandatory.** |
| **OCR queue stuck** (lab PDFs accumulating) | `etl_failures.kind = 'lab_ocr'` count > N; manual review backlog growing | New labs not indexed, but existing data unaffected | Manual review via Next.js admin route `/api/admin/dlq?kind=lab_ocr`; user fixes mappings, re-queues. Runbook: `docs/runbooks/ocr-stuck.md` |
| **Vaultwarden unavailable** | `bw login` exits non-zero in init sidecar (M2+) | App startup fails — **fail-closed** for healthcare. App does NOT start with empty creds. | Manual `.env` fallback documented in runbook; oncall can paste from password manager. |
| **LUKS key lost** | Boot fails, no passphrase prompt unlocks | Total data loss if no off-site backup | Restore from age backup (private key from physical safe) on new LUKS-formatted volume. |
| **age backup private key lost** | Cannot decrypt nightly backups | Total backup loss IF host also lost | Print backup of private key as paper QR; store in safe. Restore drill verifies QR readability monthly. |
| **Apple Health export.zip parse error** | `apple-health-parser` exception | Single import fails | Atomic-stage didn't move file → still in `data/imports/incoming/`. Inspect → re-export from iPhone if corrupt → retry. `etl_failures` row records the attempt. |
| **Oura OAuth refresh token expires/revoked** | 401 on refresh attempt | Daily Oura sync stops | Manual re-auth flow: ETL container exposes one-shot OAuth callback URL, user opens browser, grants access, new refresh token written to Vaultwarden. |
| **Fasten ingest endpoint changes (upstream main bump)** | POST 404 / 415 | All ETL writes fail | Pin `:main@sha256:digest`, re-pin every 8 weeks with smoke test (Phase 1.4 includes smoke-test script). |
| **Drizzle migration fails mid-deploy** | `drizzle-kit migrate` exits non-zero | App version mismatch with DB | Migrations are reviewed before apply (committed SQL); rollback via reverse migration committed in same PR. Test on staging copy of prod DB. |
| **Cloudflared tunnel disconnects** | CF dashboard shows tunnel down | App unreachable from internet | `restart: unless-stopped`; CF tunnel reconnects within 30s. If persistent, re-issue tunnel token. |
| **Disk fills (Fasten cache, OCR temp files)** | docker volume monitoring; `df -h` | Postgres stops accepting writes (synchronous_commit=on prevents partial commits) | M1: weekly cleanup cron. M2+: alerting via uptime-kuma → Discord. Hard limit: docker volume mount with `--storage-opt size=10G`. |
| **WSL2 inotify dropped events (Win dev only)** | ETL never sees a dropped file | Apple Health zip sits in `incoming/` forever | Polling-only design (per STACK.md cross-platform notes) — no inotify dependency. |
| **Cron job overlap (long-running OCR)** | Two `lab_pdf` ETL processes running simultaneously | Race on `etl_failures` writes | `flock -n /tmp/health-etl-lab.lock python -m health.etl.lab_pdf` — non-blocking lock; second invocation exits. |
| **RLS policy bypass (bug)** | Tested via `tests/rls.test.ts` regression suite | **Catastrophic data leak between tenants** | CI gate: opens tx with tenant A, queries for tenant B rows, asserts empty. Blocks deploy if breaks. |
| **PII leaks into logs** | Manual code review; pino redact catches default | Compliance breach (Art. 32) | Allowlist-default redaction; secret scanning in pre-commit (gitleaks); periodic log audit. |

---

## Build Order — Phase 1 Sub-Phase Recommendations

The roadmap will define Phases. Here's the dependency-aware order I recommend the roadmapper consume:

| Phase | Name | Deliverable | Depends On | Why This Order |
|-------|------|-------------|------------|----------------|
| **1.1** | **Compose Skeleton + LUKS/BitLocker** | `compose.yaml` with empty service stubs, encrypted host volume mounted, `docker compose config` validates | (none) | Foundation. Encryption-at-rest cannot be added later for PII Tier 1 — must be the first thing. |
| **1.2** | **Postgres + RLS Scaffolding** | Postgres 16.13 running, `analytics` DB created, `tenants` + `observations` + `etl_runs` tables, RLS policies enforced, `tests/rls.test.ts` passing | 1.1 | The RLS test is the gate. If RLS doesn't work, every later phase rebuilds. **Critical regression test for SaaS pivot.** |
| **1.3** | **Traefik + Internal Routing** | Traefik v3.7, dashboard on `127.0.0.1:8080`, no public exposure, label-driven discovery working | 1.1 | Edge in place before any service that needs routing. CF Tunnel deferred to 1.9. |
| **1.4** | **Fasten Container + Smoke Test** | Fasten OnPrem `:main@sha256:digest` running, accessible via Traefik at `/fasten/*`, single admin login works, FHIR Bundle upload via UI smoke-tested, **POST endpoint identified for ETL** (2-day spike) | 1.3 | Resolves A2 confidence gap (Fasten ingest API). Without this, ETL phases are blocked. |
| **1.5** | **Next.js Analytics Skeleton + Auth.js** | Next.js 15.2.4 / 16.x running, Drizzle 0.45.2 connected to Postgres, single-user Auth.js login, `withTenant` wrapper proven, default tenant `andrej` provisioned in `tenants` table | 1.2, 1.3 | Custom layer baseline before any analytics features built on top. |
| **1.6** | **Oura ETL (simplest pipeline)** | Python ETL container, OAuth2 flow with refresh, daily cron writes Oura data to Fasten, mirror picks up to Postgres | 1.4, 1.5 | Easiest ETL: well-documented API, JSON in / FHIR out, no OCR. Validates the FHIR write path end-to-end. |
| **1.7** | **Apple Health XML ETL** | apple-health-parser integrated, polling drop folder, atomic staging, FHIR mapper for top 10 HK types, ETL idempotent via watermark | 1.6 (reuses fhir_client, etl_runs patterns) | Proves bulk import path. Reuses Phase 1.6 infrastructure (FHIR client, etl_runs, mirror). |
| **1.8** | **Lab PDF OCR Pipeline (single template)** | Tesseract + pdfplumber + Ollama qwen2.5:7b on-demand, Unilabs SK template, dead-letter queue, manual review UI sketched | 1.7 | Hardest ETL — defer until easier ones prove the framework. M1 acceptance bar: >80% LOINC accuracy on 5 sample PDFs (per FEATURES.md). |
| **1.9** | **Backup + CF Tunnel + Public Access** | age-encrypted nightly backups to B2, restore drill executed, cloudflared sidecar enabled, `health.ardan.sk` reachable, monthly restore drill scheduled | 1.6, 1.7, 1.8 (must have data to back up) | LAST. Public exposure is the final step; everything must work locally first. Backup before public access (in case public access leak triggers wipe-and-restore). |

**Notes on phasing:**
- 1.1-1.3 are **infra-only**, no application code. ~1 week.
- 1.4-1.5 are **integration**, ~1 week. The Fasten ingest API spike (1.4) is the highest-risk item; allocate 2 days, escalate if blocked.
- 1.6-1.8 are **feature deliverables**, the user-visible value. ~2-3 weeks.
- 1.9 is **production hardening**, ~3 days.
- **Total M1 estimate: 5-7 weeks** depending on Fasten API spike outcome and OCR accuracy bar. Aligns with PROJECT.md "co najskor — ~1 mesiac" with realistic stretch.

---

## Multi-Tenant Evolution Path (M1 → M4 Without Rewrite)

The key insight: **the only thing that changes is the source of `tenantId` and the existence of multiple Fasten containers.** Schema, RLS, application code, ETL — unchanged.

| Concern | M1 Single-User | M4 Multi-Tenant SaaS |
|---------|----------------|----------------------|
| `tenant_id` source | Hardcoded `APP_TENANT_DEFAULT=andrej` env var | JWT claim from Authentik, extracted in middleware |
| RLS enforcement | Active (`SET LOCAL app.current_tenant = '<andrej_uuid>'` in every transaction) | Same code, different tenant_id value |
| Fasten container | One container, one volume | N containers, N volumes, Traefik subdomain dispatch |
| Postgres | Same DB, RLS isolates rows | Same DB, RLS isolates rows |
| ETL workers | One cron schedule, runs as `andrej` | Per-tenant cron lines OR one orchestrator that iterates tenants |
| Auth | Auth.js v5 single user | Auth.js v5 → Authentik provider, JWT claims |
| Secrets | One `.env` | bw sidecar pulls per-tenant items by namespace |
| Backup | One pg_dump + one Fasten SQLite | One pg_dump (multi-tenant DB) + N Fasten SQLite snapshots |
| Routing | Single domain `health.ardan.sk` | Wildcard `*.health.ardan.sk` |

**The non-rewrite contract:**
1. **Never write code that assumes "the tenant" without going through `withTenant()`.** No global "current user" state. CI lint rule could enforce.
2. **Never put tenant data in Fasten resources without including `subject = Patient/<tenant_id>`.** Fasten is single-user-per-instance, but FHIR resources still need patient references for M4 sanity.
3. **Mirror reader code reads tenant_id from job config**, not from a global. M1: hardcoded `andrej`. M4: iterates `tenants` table.
4. **All secrets accessed by tenant-namespaced key.** M1: `OURA_REFRESH_TOKEN_andrej`. M4: same pattern, just N items.

If these four invariants are maintained, M4 = (a) provision per-tenant Fasten containers via Traefik labels, (b) swap Auth.js single-user for Authentik OIDC, (c) iterate tenants in cron — no schema migration, no app rewrite.

---

## Anti-Patterns

### Anti-Pattern 1: "Multi-Tenant Theater" — `tenant_id` Column Without RLS

**What people do:** Add `tenant_id UUID` to every table, add `WHERE tenant_id = ?` to every query, but don't enable RLS.

**Why it's wrong:** A single forgotten WHERE clause leaks all tenant data. Reviewers can't catch every query in a growing codebase. PII Tier 1 leak budget = zero.

**Do this instead:** Enable RLS from day 1 (M1 single tenant). RLS policies enforce on every operation. Application bug becomes "no rows returned" (visible failure), not "wrong rows returned" (silent leak).

### Anti-Pattern 2: ETL Writes Directly to Postgres

**What people do:** ETL pipelines write to the analytics DB, then "later" sync to Fasten.

**Why it's wrong:** Two write paths means two sources of truth. Drift is inevitable. FHIR conformance lost (Postgres has no schema invariants for FHIR). Data lifecycle (versioning, encounters) becomes incoherent.

**Do this instead:** ETL always writes to Fasten via FHIR Bundle POST. Mirror process reads Fasten and writes derived Postgres rows. **One write path, one source of truth.**

### Anti-Pattern 3: Fasten Postgres "Just Try It"

**What people do:** Ignore upstream "BROKEN" warning, configure Fasten with `db: postgres`, hope for the best.

**Why it's wrong:** STACK.md verified this verbatim from Fasten config.yaml. Days lost debugging unsupported config.

**Do this instead:** Fasten = SQLite-only until upstream marks Postgres GA. Re-evaluate at every Fasten release. Postgres serves analytics only.

### Anti-Pattern 4: Logging FHIR Resources for "Debugging"

**What people do:** `logger.info({ bundle: fhirBundle }, 'ingested')` to debug ETL failures.

**Why it's wrong:** FHIR Bundle = patient record. Log file = potentially shipped to centralized logging, indexed, searchable, forever. **PII Tier 1 leak.**

**Do this instead:** Log envelope only: `{ kind, recordCount, durationMs }`. For dev debugging, use a separate dev-only opt-in flag (`DEBUG_PII=1`) that writes to a tmpfs-only log, never persisted.

### Anti-Pattern 5: Atomic Imports Skipped

**What people do:** ETL reads `data/imports/incoming/export.zip` directly, parses, then deletes/moves the file.

**Why it's wrong:** If ETL crashes mid-parse, file is gone, partial data in DB. If user drops a new file mid-process, old + new data interleave.

**Do this instead:** Atomic stage to `processing/<ts>_export.zip` via `os.replace`. Process from there. Move to `processed/` only on commit. (See STACK.md `stage_and_atomic` snippet.)

### Anti-Pattern 6: Single Encryption Layer

**What people do:** "BitLocker is enough." OR "pgcrypto is enough." OR "TLS in transit is enough."

**Why it's wrong:** Each layer protects against different threats. BitLocker stops physical theft. pgcrypto stops privilege-escalation read-DB-as-root. age stops backup-tape-theft. **Threats don't compose; defenses must.**

**Do this instead:** All three layers in M1, layered. Performance cost is < 10% combined.

### Anti-Pattern 7: Vaultwarden as Sole Backup Key Store

**What people do:** Put age private key in Vaultwarden so "everything is in one place."

**Why it's wrong:** If Vaultwarden goes down or is compromised at the same time as the host (correlated failure: shared infra, ransomware), you've lost both the data and the key to recover it.

**Do this instead:** Vaultwarden for app secrets (rotating, low value if leaked alone). Air-gapped paper QR + USB for backup decrypt keys (rare access, high value, uncorrelated with running infra).

### Anti-Pattern 8: Fasten "main" tag without Digest Pin

**What people do:** `image: ghcr.io/fastenhealth/fasten-onprem:main`

**Why it's wrong:** Compose may or may not re-pull on restart depending on local cache; an upstream main bump can silently change behavior between restarts. Reproducible deploys lost.

**Do this instead:** `image: ghcr.io/fastenhealth/fasten-onprem:main@sha256:<digest>`. Re-pin every 8 weeks via smoke-test script.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Oura API v2** | OAuth2 (Authorization Code) → refresh token. Daily cron with HTTP backoff. | PAT deprecated. Rate limits well-documented; daily fetch ≪ limit. Webhooks not offered for daily summaries. |
| **Apple Health (iOS)** | No API. User exports `Apple_Health_Export.zip` from iPhone Health app, AirDrops to PC, drops in `data/imports/incoming/`. ETL polls via mtime. | inotify dead over WSL2 bind mounts (STACK.md). Polling only. ~50-500 MB zip. |
| **Cloudflare Tunnel** | `cloudflared` sidecar with `TUNNEL_TOKEN` env var. CF dashboard creates tunnel, copies token. | TLS terminated at CF edge. Backend (Traefik) is HTTP-only. |
| **Vaultwarden** (cross-project, on docker-srv-01:8094) | M1: manual lookup, paste into `.env`. M2+: bw CLI sidecar with `BW_HOST`, `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_PASSWORD`. | NOT bws (Vaultwarden doesn't expose Bitwarden Secrets Manager API). |
| **B2 / Hetzner Storage Box / S3** (off-site backup) | rclone push of age-encrypted files. | Choose B2 for cost: $0.005/GB/mo. Hetzner Storage Box: predictable monthly cost, EU data residency. |
| **LOINC Terminology** | Bulk download (one-time) of LOINC.csv → seed Postgres `loinc_codes` table. Cached lookup at OCR time. | Open license. Slovak lab test names need 50-100 manual mappings to cover top 80%. |
| **(M3+) Azure Document Intelligence (EU region)** | OCR escalation for poor-quality lab PDFs. **PII LEAVES MACHINE — DPIA required.** | Defer until M3. SCC + processor agreement. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Next.js Analytics ↔ Postgres | postgres@3.4.9 driver, SET LOCAL transactions, RLS-enforced | Connection pooling: pool size 10, transaction-scoped per request |
| Next.js Analytics ↔ Fasten | HTTPS/HTTP read-only (Traefik internal network); FHIR REST search | M1: read-only. Custom layer never modifies Fasten resources. |
| Python ETL ↔ Fasten | HTTP POST FHIR Bundle to ingest endpoint; HTTP GET for mirror polling | Internal docker network, no auth bypass. ETL container has Fasten admin password from secrets. |
| Python ETL ↔ Postgres | psycopg 3.2, `etl_runs` / `etl_failures` writes, mirror writes to `observations` | Same RLS model; ETL uses `app_authenticated` role with tenant_id env var |
| Traefik ↔ Services | Docker labels (declarative routing) | No central traefik.yml — every service self-declares its route |
| cloudflared ↔ Traefik | HTTP over health-edge docker network | TLS terminated at CF edge, no cert in Traefik |
| Backup script ↔ Postgres | `pg_dump` over docker exec / docker network | Read-only role used for backup; no role with WRITE participates in backup pipe |
| Backup script ↔ Fasten | `sqlite3 .backup` via volume mount to ETL container | Hot backup safe (SQLite WAL handled by `.backup`) |
| Ollama ↔ ETL | HTTP `/api/generate` on internal docker network | On-demand only; sidecar starts when lab OCR cron fires |

---

## FHIR Conformance Gates

The custom analytics layer must not break Fasten's FHIR data model. Three gates:

### Gate 1: ETL Output Validation (before POST to Fasten)

```python
# projects/etl/src/health/etl/fhir_client.py
from fhir.resources.observation import Observation
from fhir.resources.bundle import Bundle

def validate_bundle(bundle_dict: dict) -> Bundle:
    """Raises ValidationError if bundle is not valid FHIR R4."""
    bundle = Bundle.model_validate(bundle_dict)
    for entry in bundle.entry or []:
        # Each Observation must have code + subject + effectiveDateTime
        if isinstance(entry.resource, Observation):
            assert entry.resource.code is not None
            assert entry.resource.subject is not None
            assert entry.resource.effectiveDateTime is not None
    return bundle
```

### Gate 2: LOINC Code Presence on Lab Observations

```python
# Reject lab Observations without LOINC code (would degrade interoperability)
def assert_loinc(obs: Observation):
    has_loinc = any(
        c.system == "http://loinc.org"
        for c in (obs.code.coding or [])
    )
    if not has_loinc:
        raise ValueError(f"Observation {obs.id} lacks LOINC code")
```

### Gate 3: Mirror Read-Only Contract

The mirror process **never modifies Fasten data**. It only reads `_lastUpdated`-filtered resources and projects them into Postgres `observations` table. Tests assert this:

```typescript
// tests/mirror.test.ts
it('mirror should only issue GET requests to Fasten', async () => {
  const fastenSpy = spyOn(fastenClient, 'request');
  await mirrorFastenToPostgres('andrej-uuid');
  for (const call of fastenSpy.calls) {
    expect(call.method).toBe('GET');
  }
});
```

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| **M1: 1 tenant (Andrej)** | Local PC, Docker Desktop, manual `.env` secrets, single Fasten container, single Postgres DB. As described. |
| **M2-M3: 1 tenant + DICOM/DNA** | Add Orthanc DICOM container (separate stack), Ollama always-on for OCR. PC RAM at ~6 GB usage. Watch WSL2 mem limit. |
| **M4: 5-10 tenants (pilot)** | Migrate to Hetzner CX22 (4 GB). Per-tenant Fasten containers. Authentik SSO. Per-tenant secrets in Vaultwarden. CX22 fits ~30-50 idle / 5-10 active per FEATURES.md estimate. |
| **M5: 30-50 tenants (paid)** | CX22 → CX32 (8 GB) if hitting RAM ceiling. Add `pgbackrest` for PITR (vs nightly age dump). Consider managed Postgres (Aiven EU) to offload backup ops. |
| **100+ tenants** | Postgres → managed (Aiven/Neon EU). Fasten containers → schedule across multiple Hetzner nodes (Docker Swarm or k3s). Per-tenant secrets → HashiCorp Vault if Vaultwarden namespacing creaks. |

### Scaling Priorities (what breaks first)

1. **First bottleneck (M4 pilot):** Per-tenant Fasten container RAM. ~150 MB idle × 30 tenants = ~4.5 GB just for Fasten. CX22 has 4 GB. **Validation in M4: actual idle RAM with 5 tenants, extrapolate.** May need to upgrade to CX32 earlier than expected.
2. **Second bottleneck (M4-M5):** Postgres connection pool exhaustion if per-tenant analytics queries are heavy. Solution: pgbouncer in transaction mode. RLS continues to work because `SET LOCAL` is transaction-scoped.
3. **Third bottleneck (M5+):** Backup window — N Fasten SQLite files + 1 Postgres dump. Solution: parallelize per-tenant Fasten backups; switch Postgres to pgbackrest streaming.
4. **Fourth bottleneck (post-MVP):** OCR queue if many tenants upload many lab PDFs. Solution: BullMQ + Redis with priority queues; Ollama horizontal scale with vLLM.

---

## Healthcare-Specific Architectural Notes

### GDPR Art. 17 (Right to Erasure) — Per-Tenant Architecture Wins

Per-tenant Fasten containers (D11 in FEATURES.md) make Art. 17 trivial: `docker compose down fasten-tenant{N} && docker volume rm health_fasten-db-tenant{N}`. Postgres analytics: `DELETE FROM tenants WHERE id = ?` cascades to all tenant data via FK. **Document the runbook in M4** (`docs/runbooks/tenant-offboard.md`).

### GDPR Art. 20 (Data Portability) — FHIR Bundle Export

Custom layer must add a comprehensive FHIR Bundle export endpoint (Fasten's OOTB export is limited). M4 deliverable: `GET /api/admin/tenants/:id/export` returns a Bundle with all `Patient`, `Observation`, `Condition`, `MedicationRequest`, `Encounter`, `Practitioner`, `Organization`, `Immunization`, `AllergyIntolerance` resources for the tenant. age-encrypt with tenant's age public key (registered at onboard) before serving.

### GDPR Art. 32 (Audit Logs) — Defense Evidence

Every FHIR resource read AND write produces an `audit_log` row: `{ tenant_id, actor_id, resource_type, resource_id, action: 'read'|'create'|'update'|'delete', timestamp, request_id }`. This is **mandatory infrastructure**, not nice-to-have. Enforce via `withTenant` wrapper that auto-writes audit row.

### Medical Device Avoidance — Architectural Constraints

Per FEATURES.md anti-features (A1, A4, A11): **no AI inference outputs** stored in `observations` table. Ollama is used only as a **transcription assistant** for lab PDF OCR — its output is text/JSON that maps to existing FHIR codes; it never generates new clinical findings. Architectural constraint: `observations.source` enum does not include 'ai_inference' or similar. Any addition would need legal review.

---

## Sources

- [Fasten OnPrem GitHub README](https://github.com/fastenhealth/fasten-onprem) — single-user model, "multi-user is work in progress", manual entry / Bundle upload only
- [Fasten OnPrem CONTRIBUTING.md](https://github.com/fastenhealth/fasten-onprem/blob/main/CONTRIBUTING.md) — dev setup, hints at API endpoints
- [Fasten OnPrem v1.0.0 Release Notes (Issue #349)](https://github.com/fastenhealth/fasten-onprem/issues/349) — current feature surface
- [Drizzle ORM RLS docs](https://orm.drizzle.team/docs/rls) — `pgPolicy`, `crudPolicy`, `enableRLS`
- [Drizzle RLS GitHub Discussion #2450](https://github.com/drizzle-team/drizzle-orm/discussions/2450) — community patterns
- [Neon RLS + Drizzle blog post](https://neon.com/blog/modelling-authorization-for-a-social-network-with-postgres-rls-and-drizzle-orm) — `SET LOCAL` transaction pattern, multi-tenant
- [Neon Docs: Simplify RLS with Drizzle](https://neon.com/docs/guides/rls-drizzle) — production-grade pattern
- [Traefik v3 Docker provider](https://doc.traefik.io/traefik/providers/docker/) — label-driven routing
- [Traefik in Multi-Tenant Kubernetes (architecture analog)](https://doc.traefik.io/traefik/security/multi-tenant-kubernetes/)
- [Multi-Tenant Docker Architecture (oneuptime.com 2026)](https://oneuptime.com/blog/post/2026-02-08-how-to-design-a-multi-tenant-docker-architecture/view) — per-tenant container patterns
- [Cloudflare Tunnel docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) — TLS termination, token connector
- [age-encryption.org spec](https://age-encryption.org/v1) — modern AEAD, ssh-key-compatible
- [Postgres 16 Docs — Row Security Policies](https://www.postgresql.org/docs/16/ddl-rowsecurity.html) — `current_setting()`, `SET LOCAL` semantics
- [pino redact docs](https://github.com/pinojs/pino/blob/main/docs/redaction.md) — paths and censor patterns
- [HL7 FHIR R4 Bundle](https://www.hl7.org/fhir/R4/bundle.html) — ingest semantics
- [HL7 Europe Lab Report v9.1.0](https://fhir.ehdsi.eu/laboratory/) — EU lab IG (M5 future-proofing)
- STACK.md (this project, 2026-05-09) — Fasten/Postgres/Drizzle/Traefik version pins, cross-platform notes
- FEATURES.md (this project, 2026-05-09) — multi-tenant verdict (per-tenant Fasten), feature dependencies, anti-features, EU healthcare landscape

---

*Architecture research for: self-hosted personal health data aggregator with EU/SK SaaS pivot path*
*Researched: 2026-05-09*
*Author: GSD researcher (project: health, milestone: M1)*
