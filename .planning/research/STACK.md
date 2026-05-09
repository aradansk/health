# Stack Research

**Domain:** Self-hosted personal health data aggregator built on **Fasten On-Premises** (open-source FHIR aggregator) with EU/SK multi-tenant SaaS pivot path
**Researched:** 2026-05-09
**Overall Confidence:** HIGH on infra/runtime layer; MEDIUM on Fasten upstream trajectory and OCR pipeline (both flagged for plan-phase decisions)

> **Two important corrections to PROJECT.md / CLAUDE.md surfaced during this research:**
>
> 1. **Fasten license is GPL-3.0, not MIT.** Verified via `gh api repos/fastenhealth/fasten-onprem` (`"license": "GPL-3.0"`). Implications for SaaS pivot are flagged in Open Stack Questions §2.
> 2. **Fasten Postgres support is explicitly broken.** Upstream `config.yaml` says verbatim: *"postgres will be supported in the future, but is completely **BROKEN** at the moment."* The architecture in PROJECT.md/BOOTSTRAP.md that reads "one Postgres container, multi-DB: fasten + analytics" must be amended — Fasten ships SQLite-only today. Postgres serves only the custom analytics layer. This is **not a blocker** (Fasten's SQLite is fine for single-user, runs on the same encrypted volume) but the schema-level `fasten` DB plan is moot.

## TL;DR Recommendation

```
              ┌────────────────────────────────────────────────────────────┐
              │ Cloudflare Tunnel (cloudflared sidecar)  →  Traefik v3.7   │
              │  health.ardan.sk  TLS terminated by CF (no LE for M1)      │
              └──────────┬─────────────────────────────────────────────────┘
                         │ http (internal docker network)
        ┌────────────────┼─────────────────────────────────────────┐
        │                │                                         │
   ┌────▼─────┐    ┌─────▼───────┐                          ┌──────▼─────┐
   │ Fasten   │    │ Next.js 16  │                          │ ETL workers│
   │ on-prem  │    │ analytics   │                          │ (cron+flock│
   │ :main    │    │ App Router  │                          │  M1 → BullMQ│
   │ (digest- │    │ Drizzle 0.45│                          │  if scaling)│
   │  pinned) │    │ + RLS       │                          │ Apple H.   │
   │ SQLite   │    │ tenant_id   │                          │ Oura v2    │
   │ /opt/    │    │             │                          │ Lab OCR    │
   │ fasten/  │    └─────┬───────┘                          │ DICOM (M2) │
   │ db/      │          │                                  └────┬───────┘
   └──────────┘          ▼                                       ▼
                   ┌─────────────────────────────────────────────────┐
                   │  postgres:16.13-bookworm  (analytics ONLY)      │
                   │  pgcrypto column-level for sensitive fields     │
                   │  BitLocker (Win dev) / LUKS (Linux prod) on vol │
                   └─────────────────────────────────────────────────┘
```

**Headline picks (HIGH confidence unless noted):**

| Layer | Pick | Reject |
|---|---|---|
| **FHIR aggregator** | `ghcr.io/fastenhealth/fasten-onprem:main` **pinned to a sha256 digest** — license **GPL-3.0** | `:v1.1.3` (19 months stale, missing multi-user, Quest, Epic logo updates) ; `:sandbox` (synthetic data only) ; floating `:main` |
| **Fasten DB backend** | **SQLite (Fasten's only working option)** stored on encrypted volume | Fasten + Postgres — config explicitly says *"BROKEN at the moment"* |
| **Analytics DB** | `postgres:16.13-bookworm` (Debian, NOT alpine — ICU collation issues) | `postgres:18.x` (newest but ecosystem lag) ; `postgres:17` (fine alternative) ; alpine variants |
| **Application framework** | **Next.js 16.2.6** with App Router (latest as of 2026-05-07) | Pages Router (deprecated path) ; SvelteKit / Remix (CEO ecosystem alignment) |
| **ORM** | **Drizzle ORM 0.45.2** with `pgPolicy` / `crudPolicy` for RLS (drizzle-kit 0.31.10) | Prisma (no first-class RLS — Issue #12735 open since 2022) ; Sequelize (legacy) ; Drizzle 1.0-beta (API churn) |
| **PG driver** | **`postgres@3.4.9`** (porsager) under Drizzle | `pg` (node-postgres) is fine but ~30% slower under Drizzle workloads; Drizzle docs prefer `postgres` |
| **Reverse proxy** | **Traefik v3.7.0** (2026-05-05 release) behind Cloudflare Tunnel | Caddy (less compose-discovery) ; nginx (manual config explosion at multi-tenant) |
| **TLS termination** | **Cloudflare** (CF Tunnel terminates externally; Traefik = HTTP-only internal) | Let's Encrypt at Traefik (unnecessary when CF already does it) ; self-signed (browser warnings) |
| **Secrets** | **Vaultwarden + manual `.env` for M1** ; `bw` CLI sidecar in M2 (NOT `bws` — Vaultwarden does NOT expose Bitwarden Secrets Manager API) | Docker Secrets natively (Vaultwarden Discussion #3462) ; HashiCorp Vault (overkill solo) |
| **Compose** | `docker compose` v2 plugin, file `compose.yaml` (no dash) | `docker-compose` legacy v1 binary (EOL Sept 2022) |
| **Apple Health parser** | **Python `apple-health-parser`** (active March 2026 release) on a Python ETL container | Node — no maintained library ; HealthKitOnFHIR (Swift on-device, NOT export.xml) ; Apple Health MCP Server (moving target) |
| **Oura sync** | **OAuth2 only** (Personal Access Tokens deprecated — confirmed in Pinta365 SDK + Oura docs) ; daily cron | PAT-based scripts (will break) ; webhooks (Oura doesn't offer them for daily summaries) |
| **Lab PDF OCR** | **Tesseract 5 + local Ollama (qwen2.5:7b)** for table validation in M1; **Azure Document Intelligence (EU region)** as paid escalation if accuracy <80% | Pure Tesseract without LLM postprocess (Slovak multi-column lab layouts unreliable) ; cloud OCR in M1 (PII leaves boundary, GDPR Art. 9 friction) |
| **ETL orchestration** | **cron + flock** in M1 (3 jobs) ; **BullMQ + Redis** if scaling >5 jobs | Celery (Python overhead, unneeded) ; Dagster/Prefect (DAG complexity) |
| **Disk encryption-at-rest** | **BitLocker on host (Windows dev)** + **LUKS on Hetzner (prod)** — same Postgres volume contents work both | Postgres TDE (not in community PG) ; pgcrypto-only (column-level — use as defense-in-depth, not sole control) |
| **Backup encryption** | **`age`** (FiloSottile/age) for `pg_dump` + Fasten SQLite snapshots | `gpg` (more friction, no clear win) ; cloud backup w/o encryption |
| **Host (M1)** | Local Windows PC + Docker Desktop (WSL2 backend) | docker-srv-01 (firemny — strict isolation per CLAUDE.md) ; Hetzner now (no PII in cloud before DPIA — defer to M4) |

## Recommended Stack

### Core Containers

| Service | Image / Version (pin) | Purpose | Why this version |
|---|---|---|---|
| **Fasten on-prem** | `ghcr.io/fastenhealth/fasten-onprem:main@sha256:<digest>` | FHIR aggregator (patient-side EMR) | **No proper SemVer release since v1.1.3 (2024-10-01)**; main branch is the only path to recent fixes (Quest Diagnostics PR Sept 2024, basic multi-user PR #503 Aug 2024, Epic logos through Feb 2026). **Pin to a digest** — floating `:main` will silently break compose semantics on rebuild. |
| **Postgres** | `postgres:16.13-bookworm` | Custom analytics DB only | 16.13 is the latest 16.x patch (2026-02-26 release). Bookworm-slim has full glibc — `pg_dump`, `tzdata`, ICU collations all work. **Avoid alpine** for Postgres: ICU collation differences between musl and glibc cause index ordering inconsistencies on cross-platform restore. EOL November 2028 — runway. |
| **Traefik** | `traefik:v3.7.0` | Reverse proxy + service discovery | v3.7.0 released 2026-05-05. v3.x is current major (since Apr 2024). v2.x EOL'd in 2025. Pin minor to prevent surprise upgrades. |
| **Cloudflared** | `cloudflare/cloudflared:2026.4.x` | CF Tunnel sidecar (M2+) | CF rolls weekly; pin to a quarter rather than floating `latest`. Tunnel auth via `TUNNEL_TOKEN` env var (token-based connector). |
| **Next.js (analytics)** | `node:22-bookworm-slim` runtime, `next@16.2.6` | Custom analytics UI + Server Actions + tRPC | Node 22 LTS is the supported Next.js 16 baseline. App Router default. **Note: 16.2.6 is bleeding-edge (released 2026-05-07).** A more conservative pick is `next@15.2.4` if stability concerns trump features — both work with Drizzle 0.45. |
| **Python ETL** | `python:3.13-slim-bookworm` | Apple Health XML parser, Oura sync, OCR orchestrator | 3.13 stable; slim Debian to keep `lxml`, `pdfplumber`, `pillow` wheels working without compile. **Avoid alpine** — these all build from source there (8–15 min). |
| **Vaultwarden** (separate stack) | `vaultwarden/server:1.36.0` | Already running on `docker-srv-01:8094` per CLAUDE.md; Health stack pulls secrets via `bw` CLI when M2 sidecar is built | 1.36.0 (2026-05-03) is current. Cross-project — not deployed inside Health stack. M1 = manual `.env` lookup. |
| **Ollama** (optional sidecar) | `ollama/ollama:0.4.x` + `qwen2.5:7b` | Vision-LLM table validation of Tesseract output for lab PDFs — fully on-device | qwen2.5:7b chosen over llama3.2:3b for better structured-JSON output (matters for FHIR Observation construction). RAM cost ~5 GB. Run on-demand only. |

### Application Layer (Next.js / TypeScript)

| Tool | Version | Purpose | Why |
|---|---|---|---|
| `next` | `^16.2.6` (or `^15.2.4` if conservative) | App Router, Server Actions, Server Components | Stable, RSC + Server Actions native, App Router is documentation default. Verified latest on npm 2026-05-07. |
| `react` | `^19.0.x` | Required peer of Next.js 16 | RSC + actions native. |
| `drizzle-orm` | `^0.45.2` | TypeScript ORM with **first-class Postgres RLS** via `pgPolicy` / `crudPolicy` | Verified latest stable on npm 2026-03-27. Stay on 0.45.x line — `1.0.0-beta.22` exists but has API churn. |
| `drizzle-kit` | `^0.31.10` | Migrations + schema push tooling | Verified latest on npm 2026-03-17. RLS policies emitted into migration SQL. |
| `postgres` (porsager) | `^3.4.9` | PG driver under Drizzle | Drizzle's recommended driver. Verified npm latest 2026-04-05. Faster than `pg` for Drizzle queries. **Note**: for RLS context vars (`SET LOCAL`), test that pooling does not cross transactions; see schema sketch. |
| `zod` | `^3.24.x` | Runtime validation for ETL inputs (Apple Health, Oura, Lab JSON) + API route bodies | Defensive parsing at PII boundary — non-negotiable for Tier 1. |
| `next-auth` (Auth.js) | `^5.0.0-beta.x` for v5 (preferred for App Router) ; `^4.24.14` if v5 betas are unacceptable | Session middleware in M1 single-user; pluggable to Authentik in M4 | v5 is beta-but-production-ready per Auth.js team. v4.24.14 is the last v4 stable. |
| `pino` | `^9.x` | Structured JSON logging with PII redaction | **MANDATORY**: configure `redact` paths for fields that could contain PII. Never log raw FHIR payloads. |
| `tailwindcss` | `^3.4.x` | Styling — pinned to v3 for now (v4 still has compose/postcss rough edges) | |
| `shadcn/ui` (copied components, no dep) | latest | Headless components — keeps frontend bundle lean | |
| `recharts` | `^2.13.x` | Charts (sleep over time, lab trend lines) | Recharts 2 is stable; 3 is RC — defer. |

### ETL / Worker Layer (Python — separate container)

| Library | Version | Purpose |
|---|---|---|
| `apple-health-parser` | `^0.5.x` (per PyPI 2026-03 release, alxdrcirilo) | Apple Health export.zip → DataFrame → JSON for analytics ingest |
| `oura-ring` (hedgertronic) | `latest` (active 2026) | Oura API v2 client (sleep/readiness/activity/HRV/SpO2/stress) |
| `httpx[http2]` | `^0.28.x` | Generic HTTP client (any non-Oura sync); sync mode is sufficient for daily cron |
| `pdfplumber` | `^0.11.x` | Lab PDF text + table extraction (text-mode PDFs) |
| `pdf2image` | `^1.17.x` | Convert image-mode PDFs to PIL images for Tesseract |
| `pytesseract` | `^0.3.13` | Wraps Tesseract 5 binary; install `tesseract-ocr-slk` (Slovak) language pack |
| `pillow` | `^11.x` | Image preprocessing before OCR (deskew, contrast) |
| `psycopg[binary]` | `^3.2.x` | Postgres driver from Python ETL into analytics DB |
| `fhir.resources` | `>=8.0.0` (FHIR R4 / R4B / R5 pydantic models) | Validate FHIR R4 resources before POST to Fasten |
| `python-dotenv` | `^1.0.x` | Load `.env` (M1) |
| `apscheduler` | `^3.10.x` | In-process scheduler (M1) — replaced by BullMQ if scaling >5 jobs |

### Development Tools

| Tool | Purpose | Notes |
|---|---|---|
| `age` v1.2.x (FiloSottile/age) | Encrypted DB backups → off-site | 100× simpler than gpg, modern AEAD, ssh-key-compatible. `pg_dump | age -r <recipient> > backup.age`. Multiple sources (Luke Hsiao, Filo blog) recommend over gpg for backup-only use. |
| LUKS / `cryptsetup` v2.7.x (Linux prod) | Block-device encryption for Postgres data volume | Pre-create LUKS volume, mount to `/var/lib/postgres-encrypted`, bind-mount into container. AES-NI = 2–5% perf hit. |
| BitLocker (Windows dev) | Volume encryption for Docker Desktop's WSL2 disk | Docker Docs explicitly recommends BitLocker for Windows hosts running containers with secrets. |
| `drizzle-kit` v0.31.10 | Schema migrations, introspect, push, generate SQL | `drizzle-kit generate` for SQL migrations (review before prod). `drizzle-kit push` only in dev. |
| `pre-commit` | Git hook framework: detect-secrets, gitleaks, ruff, prettier | **MANDATORY** for PII Tier 1. Block accidental commit of `.env`, lab PDFs, DICOM. |
| `gitleaks` v8.x | Secret scanning in pre-commit hook | Catches Oura tokens, Fasten admin password. |
| Drizzle Studio (web UI) | Schema/data browsing | Shipped with drizzle-kit, simpler than Prisma Studio. Local-only by default. |

## Installation

### Compose skeleton (M1, single-host, Windows dev / Linux prod compatible)

```yaml
# compose.yaml (no dash — Compose v2 convention)
name: health

networks:
  health-internal:
    driver: bridge
  health-edge:
    driver: bridge

volumes:
  fasten-db:        # SQLite + Fasten cache
  fasten-cache:
  fasten-certs:
  postgres-data:    # analytics DB (separate volume — encrypt at host layer)

services:
  cloudflared:
    image: cloudflare/cloudflared:2026.4.0
    container_name: health-cloudflared
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:?}
    networks:
      - health-edge
    # M1: leave commented while building locally; uncomment for health.ardan.sk
    # depends_on:
    #   - traefik

  traefik:
    image: traefik:v3.7.0
    container_name: health-traefik
    restart: unless-stopped
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=health-edge"
      - "--entrypoints.web.address=:80"
      - "--api.dashboard=true"
      - "--api.insecure=true"        # internal LAN only — never expose
      - "--accesslog=true"
      - "--log.level=INFO"
    ports:
      - "127.0.0.1:8080:8080"        # dashboard, localhost only
      - "127.0.0.1:80:80"            # M1: LAN-only, CF Tunnel takes over later
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - health-edge
      - health-internal

  fasten:
    image: ghcr.io/fastenhealth/fasten-onprem:main@sha256:REPLACE_WITH_DIGEST
    container_name: health-fasten
    restart: unless-stopped
    environment:
      - HOSTNAME=fasten
      - HOST_IP=0.0.0.0
      - HOST_PORT=8080
    volumes:
      - fasten-db:/opt/fasten/db
      - fasten-cache:/opt/fasten/cache
      - fasten-certs:/opt/fasten/certs/shared
    networks:
      - health-edge
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.fasten.rule=Host(`health.ardan.sk`) && PathPrefix(`/fasten`)"
      - "traefik.http.routers.fasten.entrypoints=web"
      - "traefik.http.services.fasten.loadbalancer.server.port=8080"
      - "traefik.http.middlewares.fasten-strip.stripprefix.prefixes=/fasten"
      - "traefik.http.routers.fasten.middlewares=fasten-strip"

  postgres:
    image: postgres:16.13-bookworm
    container_name: health-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${POSTGRES_USER:?}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?}
      - POSTGRES_DB=postgres   # bootstrap; we create analytics via init
      - POSTGRES_INITDB_ARGS=--encoding=UTF-8 --locale=C.UTF-8
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./projects/infra/postgres/init:/docker-entrypoint-initdb.d:ro
    networks:
      - health-internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  analytics:
    build:
      context: ./projects/analytics
      dockerfile: Dockerfile
    container_name: health-analytics
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL:?}
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET:?}
      - NEXTAUTH_URL=${NEXTAUTH_URL:-http://localhost:3000}
      - APP_TENANT_DEFAULT=${APP_TENANT_DEFAULT:-andrej}
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - health-internal
      - health-edge
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.analytics.rule=Host(`health.ardan.sk`) && PathPrefix(`/`)"
      - "traefik.http.routers.analytics.entrypoints=web"
      - "traefik.http.routers.analytics.priority=1"
      - "traefik.http.services.analytics.loadbalancer.server.port=3000"

  etl:
    build:
      context: ./projects/etl
      dockerfile: Dockerfile
    container_name: health-etl
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL:?}
      - OURA_CLIENT_ID=${OURA_CLIENT_ID:?}
      - OURA_CLIENT_SECRET=${OURA_CLIENT_SECRET:?}
      - OURA_REFRESH_TOKEN_PATH=/run/secrets/oura_refresh_token
    volumes:
      - ./data/imports:/srv/imports:ro          # apple_health_export.zip drops here
      - ./data/dicom:/srv/dicom:ro              # M2 — RO from M1 perspective
      - ./output/etl:/srv/output:rw
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - health-internal
```

### `.env.example` (placeholders only — never commit real `.env`)

```bash
# Postgres
POSTGRES_USER=health_admin
POSTGRES_PASSWORD=__GENERATED_BY_VAULTWARDEN__
DATABASE_URL=postgresql://health_admin:__PASS__@postgres:5432/analytics

# Next.js / Auth.js
NEXTAUTH_SECRET=__OPENSSL_RAND_BASE64_32__
NEXTAUTH_URL=http://localhost:3000
APP_TENANT_DEFAULT=andrej

# Oura
OURA_CLIENT_ID=__FROM_OURA_DEV_PORTAL__
OURA_CLIENT_SECRET=__FROM_OURA_DEV_PORTAL__

# Cloudflare Tunnel (M2+)
CLOUDFLARE_TUNNEL_TOKEN=__FROM_CF_DASHBOARD__
```

### Postgres init: analytics DB + RLS scaffolding

`./projects/infra/postgres/init/01_databases.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  CREATE DATABASE analytics;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname analytics <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- column-level encryption
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- tenant_id UUIDs
  CREATE EXTENSION IF NOT EXISTS citext;         -- emails

  -- Multi-tenant scaffolding (single tenant in M1, RLS-ready)
  CREATE ROLE app_user NOLOGIN;
  CREATE ROLE app_authenticated NOLOGIN INHERIT;
  GRANT app_authenticated TO app_user;
EOSQL
```

### Drizzle RLS skeleton (multi-tenant, `tenant_id` + Postgres RLS)

```typescript
// schema.ts
import { pgTable, pgPolicy, pgRole, uuid, text, timestamp, jsonb } from 'drizzle-orm/pg-core';
import { sql } from 'drizzle-orm';

export const appAuthenticated = pgRole('app_authenticated').existing();

export const tenants = pgTable('tenants', {
  id: uuid('id').primaryKey().defaultRandom(),
  name: text('name').notNull(),
  createdAt: timestamp('created_at').defaultNow(),
});

export const observations = pgTable('observations', {
  id: uuid('id').primaryKey().defaultRandom(),
  tenantId: uuid('tenant_id').notNull().references(() => tenants.id),
  source: text('source').notNull(),     // 'apple_health' | 'oura' | 'lab_pdf' | 'dna' | 'dicom'
  type: text('type').notNull(),         // FHIR Observation.code mapping (LOINC where possible)
  fhirResource: jsonb('fhir_resource').notNull(),
  observedAt: timestamp('observed_at').notNull(),
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

```typescript
// middleware.ts (Next.js — set tenant context per request transaction)
import { db } from './db';
import { sql } from 'drizzle-orm';

export async function withTenant<T>(tenantId: string, fn: (tx: typeof db) => Promise<T>): Promise<T> {
  return db.transaction(async (tx) => {
    await tx.execute(sql`set local app.current_tenant = ${tenantId}`);
    return fn(tx);
  });
}
```

Per-request, the analytics service issues `SET LOCAL app.current_tenant = '...uuid...'` inside a transaction. RLS then enforces isolation regardless of bugs in app-layer filters. **Important:** must run in a transaction (`SET LOCAL` is transaction-scoped) — pooled non-tx queries leak across tenants. Proven pattern (Supabase, Neon docs).

### Python ETL Dockerfile skeleton

```dockerfile
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-slk \
      poppler-utils \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
USER 1000:1000
ENTRYPOINT ["python", "-u", "src/main.py"]
```

## Alternatives Considered

| Recommended | Alternative | When to use alternative |
|---|---|---|
| Fasten on-prem | OpenEMR / OpenMRS | Heavy, clinic-side, opposite of patient-centric goal. **Wrong fit.** |
| Fasten on-prem | Self-build FHIR server (HAPI FHIR + custom UI) | If we need providers' actual FHIR APIs (US chains) and not aggregator. M5 SaaS only — M1 must avoid the rebuild. |
| Postgres 16.13 | Postgres 17.9 / 18.3 | 17 is fine; 18 brings AIO + skip-scan but ecosystem (Drizzle, pg, pgcrypto patches) just got stable on 17. **For M1, 16.13 = lowest risk + 5-year support window into 2028.** Switch to 17 at next major M3/M4 break. |
| Plain Postgres | Supabase Self-Hosted | Defer to M4 SaaS pivot — Postgres + GoTrue + PostgREST + Storage + Realtime + Edge Functions in one stack. **Premature in M1** (CEO PROJECT.md decision). |
| Drizzle | Prisma 7 | Prisma 7's TS Query Compiler closes some bundle gap. RLS still requires raw SQL — Issue #12735 open since 2022. Choose if team has stronger Prisma muscle memory. |
| Drizzle 0.45 | Drizzle 1.0-beta | Stay on 0.45 stable. 1.0-beta has API churn (consolidated package layout, refined relational query API). Re-evaluate when 1.0 GA ships. |
| Drizzle | Kysely + manual SQL | If we wanted query-builder-only. Drizzle gives schema introspection + RLS in one — Kysely doesn't model RLS policies. |
| Drizzle | TypeORM / Sequelize | **Don't.** Both treat Postgres as "MySQL-with-extras"; no RLS modeling, slower, larger bundle, weak TS support. |
| `postgres` (porsager) driver | `pg` (node-postgres) | `pg` works fine; ~30% slower in Drizzle benchmarks. Choose `pg` only if you have existing infra utilities depending on it. |
| Traefik v3.7 | Caddy v2 | Caddy is simpler config but compose service-discovery is bolted on. Traefik labels are battle-tested for multi-service compose. |
| Traefik v3.7 | nginx + njs | Full control, but at multi-tenant we'd hand-write per-host configs. Traefik label-driven is more maintainable. |
| `apple-health-parser` (Python) | `fedecalendino/apple-health` | Older (last commit 2023-ish), narrower API. `apple-health-parser` 2026-03 is more active. |
| `apple-health-parser` | `markwk/qs_ledger` | Single-file script, not a library. Reference only. |
| `apple-health-parser` | Roll our own with stdlib `xml.etree.iterparse` | Acceptable backup if PyPI lib hits a parsing bug — Apple's `export.xml` schema is stable across iOS versions. |
| Tesseract + Ollama vision validator | Pure Tesseract 5 | OK for clean print PDFs, but Slovak lab reports often have multi-column layouts → Tesseract row reconstruction is unreliable. **Vision LLM as adjudicator** catches mistakes. |
| Tesseract + Ollama | Azure Document Intelligence (EU) | $1.50/1000 pages OCR + $10/1000 pages prebuilt. Acceptable cost, GDPR-OK in EU regions, but **PII leaves machine** — defer to M3+ when DPIA is in place. **HIPAA-comparable BAA available**. |
| Tesseract + Ollama | Google Document AI | Strong on multilingual (good for SK lab forms). Cost-comparable to Azure. Same PII concern. |
| Cloudflare Tunnel | Tailscale Funnel | Tailscale is great for SSH/admin but is a single TCP relay; CF Tunnel gives TLS termination + WAF + DDoS for free at health.ardan.sk. |
| Cloudflare Tunnel | Direct port forward + Let's Encrypt at Traefik | Requires public IPv4 + ACME at Traefik. Works but exposes the host IP. CF Tunnel is the better posture for a personal data plane. |
| Vaultwarden (manual M1) | HashiCorp Vault | Vault is enterprise-grade but operational tax (unseal, audit, replication) ≫ what a 1-person M1 needs. |
| Vaultwarden (manual M1) | Doppler / 1Password Secrets Automation | Cloud secret manager. **Reject** — secrets for health PII pipeline shouldn't live in 3rd-party SaaS. |
| `bw` CLI sidecar (M2) | SOPS + age-encrypted `.env` in repo | Better git-friendliness but every CEO PC needs the age key — works for solo, less for multi-machine. **Acceptable secondary path** if Vaultwarden sidecar slips. |
| Auth.js v5 | Lucia | Lucia v3 just deprecated — community in flux. Auth.js v5 has Authentik provider already. |
| Auth.js v5 | Clerk / Supabase Auth | Cloud user DB = PII residency concerns + lock-in. M1 single-user makes this irrelevant; M4+ should use Authentik (self-hosted) per CLAUDE.md. |
| BitLocker / LUKS (FDE) | VeraCrypt | More cross-platform but slower, more friction. Per-platform native (BitLocker, LUKS) is faster + integrated. |
| BitLocker / LUKS | pgcrypto column-level only | Column-level requires app to know which fields to encrypt. **Use as defense-in-depth on top of FDE**, not instead of. Specifically encrypt: lab values free-text fields, doctor names, recipe notes. |
| `age` for backups | `gpg` | gpg is fine if you already have gpg keyring. For backup-only, age is simpler, faster, modern AEAD. |
| cron + flock | BullMQ + Redis | Redis-backed queue with retries/cron/rate-limit. M2+ when >5 ETL jobs or need retry semantics. NOT M1. |
| cron + flock | Celery + Redis/RabbitMQ | Python-native (matches ETL workers) but heavier. Skip in M1. Reconsider only if ETL grows complex enough to need DAGs (then jump to Dagster/Prefect). |

## What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| **Fasten configured for Postgres** | Fasten upstream `config.yaml` says verbatim *"postgres will be supported in the future, but is completely **BROKEN** at the moment"*. Trying to wire it now = wasted days. | SQLite (Fasten default), separate Postgres for analytics. Re-evaluate at each Fasten release. |
| **Fasten v1.1.3 release tag** in production | v1.1.3 is from 2024-10-01 — 19 months stale at time of writing. Misses Quest, multi-user (Aug 2024), Epic logo updates (Feb 2026). | `:main` pinned to a specific image **digest** (sha256). Track upstream and re-pin every 8 weeks with smoke test. |
| **`postgres:latest` or floating `:16`** | "Latest" rolled to 18.3 in Feb 2026; major version upgrades are NOT in-place. | `postgres:16.13-bookworm` — **always pin both major.minor and base distro**. |
| **`postgres:*-alpine`** | musl/glibc ICU collation differences silently break index ordering on cross-host restore. Marginal size win not worth corruption risk. | `postgres:16.13-bookworm`. |
| **Postgres TDE (Transparent Data Encryption)** | Not in community Postgres; only EDB / Crunchy / Fastware forks have it. | **BitLocker/LUKS at host filesystem layer** + **pgcrypto column-level** for the most sensitive fields. |
| **Apple Health + Node parser** | No actively maintained Node library for the XML schema. Building from scratch wastes time. | **Python ETL container** with `apple-health-parser`. Output JSON → analytics DB ingest. |
| **Apple's `HealthKitOnFHIR` (Swift, StanfordBDHG)** | Swift Package, runs on iOS device — does NOT parse the iOS `export.xml` format | `apple-health-parser` (Python) + custom HealthKit→FHIR mapper layer |
| **Apple Health MCP Server (Momentum)** | "Evolved into Open Wearables" — moving target, not a stable library dependency | Roll your own thin parser layer using `apple-health-parser` |
| **Oura Personal Access Tokens** | Officially deprecated. Will be revoked. | OAuth2 with refresh-token flow; token rotation handled by ETL container. |
| **Cloud OCR for M1 (Azure / Textract / Vision API)** | PII Tier 1 + GDPR Art. 9 = explicit consent, DPIA, SCC if outside EEA. | Local Tesseract 5 + on-device Ollama vision validator. **Stay 100% on-machine** in M1. |
| **Sending FHIR resources to public LLM APIs (OpenAI, Anthropic)** | PII Tier 1 + GDPR Art. 9 + explicit consent + DPIA | Local Ollama only; defer cloud LLM to post-DPIA. |
| **Prisma for RLS** | Issue #12735 open since 2022; raw SQL escape hatch defeats the ORM's value-add. | **Drizzle** with first-class `pgPolicy`. |
| **Sequelize / TypeORM** | Maintenance mode-ish, no Postgres RLS modeling, large bundle, weak TS support. | Drizzle. |
| **`pg` driver under Drizzle (without testing)** | Doesn't change correctness but ~30% slower in Drizzle benchmarks; use of `SET LOCAL` requires explicit transaction wrapping (same with `postgres` driver). | **`postgres@3.4.9`** with explicit `BEGIN; SET LOCAL ...; SELECT ...; COMMIT;` per request. |
| **Floating `traefik:latest`** | Major version v2 → v3 changed config syntax substantially. | `traefik:v3.7.0` pin; bump in a maintenance milestone. |
| **Let's Encrypt at Traefik when CF Tunnel is in front** | CF terminates TLS at edge. ACME at Traefik = duplicate work, plus Tunnel auth flow conflicts with HTTP-01 challenge. | Traefik HTTP-only on internal `health-edge` network. CF handles all public TLS. |
| **`docker-compose` v1 binary** | Last release Sept 2022, EOL'd by Docker. | `docker compose` v2 plugin (built into Docker Desktop and `docker-ce`). |
| **`docker-compose.yml` filename** | Legacy. Compose v2 prefers `compose.yaml` (no dash). Both still work; new convention is cleaner. | `compose.yaml` for new projects. |
| **`watchdog` / `watchfiles` for ETL file detection on Windows host bind mounts** | inotify events don't propagate from Windows host → Linux container (Docker for-win Issue #8479, watchfiles Issue #169). | Polling loop with `os.scandir` + mtime, OR drop-detection trigger via simple HTTP endpoint. |
| **`alpine` Python images** | musl + missing wheels = pip builds from source. ETL container build time goes from ~30 s → 12+ min. Image saves 50 MB. | `python:3.13-slim-bookworm`. |
| **`bws` CLI against Vaultwarden** | Vaultwarden does NOT expose Bitwarden Secrets Manager API (Discussion #3462). `bws` will fail. | Regular `bw` CLI against Vaultwarden — uses Bitwarden vault APIs (which Vaultwarden DOES expose). |
| **Hardcoded paths in `compose.yaml`** | Breaks portability between Windows dev (`/c/ANDREJ/...`) and Hetzner prod (`/srv/...`). | `.env`-driven `${HEALTH_DATA_PATH:?}` with `:?` to fail loudly if missing. |
| **Reading source mounts read-write** | Risk of accidental writes to manual import data. PII Tier 1 = even one bug is one bug too many. | Source mounts always `:ro`; only `output/`, `data/processed/`, `postgres-data` volumes are `:rw`. |
| **Putting `.htpasswd` / Auth.js sessions in git** | Standard breach. | `.gitignore` strict, validated via `gitleaks` pre-commit hook. |
| **Storing tokens in `.env` checked into git** | PII Tier 1 — leaked Oura token = personal health data exposure | Vaultwarden + manual lookup (M1) → `bw` sidecar (M2+). |

## Stack Patterns by Variant

**M1 — Local Windows PC (Docker Desktop, WSL2):**
- All services on `127.0.0.1` only — `traefik` does NOT bind `0.0.0.0`
- BitLocker on the Windows volume hosting Docker Desktop's `\\wsl$\docker-desktop-data\...`
- File watching via polling (inotify dead over bind mounts)
- Apple Health export workflow: AirDrop `.zip` to PC → drop in `data/imports/` → ETL polls every 5 min and processes any new file
- ETL backfills: manual `docker compose run --rm etl python -m health.etl.backfill --since 2023-01-01`
- No CF Tunnel, no public DNS — purely LAN

**M2 — Local PC + CF Tunnel for `health.ardan.sk`:**
- `cloudflared` sidecar uncommented; tunnel token from CF dashboard
- Traefik still binds `127.0.0.1:80` only — CF Tunnel forwards to it inside the same compose network
- DNS: CF DNS proxy enabled (orange-cloud) on `health.ardan.sk`
- TLS: full handled by CF; Traefik knows nothing about certs
- Authelia/Authentik **NOT YET** — Auth.js v5 single-user mode

**M3 — DICOM + DNA datasets:**
- Add **Orthanc** container as DICOM store, behind separate `/dicom` Traefik route, password-gated
- DNA raw `.txt` ingest → Python ETL with `myvariant.info` lookup library → `analytics.dna_findings` table
- Keep stack on local PC unless CEO commits to Hetzner

**M4 — Pre-SaaS (multi-tenant orchestration):**
- Migration target: **Hetzner CX22** (€3.79/mo, 2 vCPU / 4 GB / 40 GB, German+Finnish DCs, GDPR-default)
- LUKS on the cloud volume, key kept off-server (entered at boot via SSH)
- Auth.js → Authentik provider; Authentik runs as 5th compose service
- Per-tenant strategy: **schema-per-tenant inside `analytics` DB**, not separate Postgres instances. Schemas isolate while sharing connection pool.
- Fasten: per-tenant container, namespaced volumes, Traefik routing by `Host(*.health.ardan.sk)` strip-prefix to per-tenant Fasten

**M5 — Production SaaS (paying tenants):**
- Postgres → consider managed (Aiven/Neon EU regions) for backup automation, or stay self-hosted with `pgbackrest` + age-encrypted off-site
- DPIA finalized, SCC in place for any cloud OCR fallback
- HA: 2× CX32 with `pg_auto_failover` only if uptime SLO requires it — most B2C health apps run single-node + nightly snapshot

## Atomic Imports Pattern (cross-platform safe)

Apple Health exports are 50–500 MB ZIPs. Naive ingest reads → DB while next file lands → race. Use `os.replace` atomic pattern:

```python
import os, tempfile, shutil
from pathlib import Path

def stage_and_atomic(source: Path, dest_dir: Path) -> Path:
    """Move large export file into processing dir atomically.

    Source: /srv/imports/incoming/export.zip (mounted RO from host)
    Dest:   /srv/imports/processing/<ts>_export.zip (RW)
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".staging.", suffix=".zip", dir=dest_dir)
    os.close(fd)
    shutil.copy2(source, tmp)
    final = dest_dir / f"{int(source.stat().st_mtime)}_{source.name}"
    os.replace(tmp, final)
    return final
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
              │     ($1.50/1k pages OCR + $10/1k pages prebuilt, ~99.8% accuracy, table-aware)
              │     PII transit to Microsoft EU region — DPIA required
              └─ Google Document AI Health Form parser
                    (similar cost, strong multilingual incl. Slovak)
```

**Per-PDF cost ceiling (cloud):** ~$0.0015. For ~50 lab PDFs/year self-use, total = $0.075/yr. **The gate is privacy/compliance, not money.**

**M1 acceptance bar:** Tesseract + Ollama achieves >80% correct LOINC code mapping on 5 sample lab PDFs from real Slovak labs. If <80%, lab OCR feature → M2 with Azure escalation path planned.

## Postgres Tuning (CX22 prod / dev parity)

In `postgresql.conf` (mounted via volume or set via `command:` flags):

```conf
# Connections
max_connections = 50              # solo + ETL + analytics, plenty headroom
listen_addresses = '*'            # internal docker network only

# Memory (CX22 = 4 GB; reserve 1 GB for OS + container overhead)
shared_buffers = 512MB
work_mem = 16MB
maintenance_work_mem = 128MB
effective_cache_size = 2GB

# WAL / durability
wal_level = replica               # for future PITR
synchronous_commit = on           # PII Tier 1: never lose committed transactions
checkpoint_timeout = 15min
max_wal_size = 2GB

# Logging (privacy: never log full statements with PII)
log_min_duration_statement = 1000  # >1s slow queries only
log_line_prefix = '%m [%p] %u@%d '
log_statement = 'none'             # NEVER 'all' — would log lab values

# Locale / encoding (lock to UTF-8 + C.UTF-8 collation)
# set via initdb args in compose
```

## Vaultwarden + bw Sidecar Pattern (M2+)

**Important constraint discovered:** Vaultwarden does NOT natively expose Bitwarden Secrets Manager API (`bws` CLI). It is a Bitwarden-compatible vault but Secrets Manager is a separate Bitwarden product. Discussion #3462.

**Pattern for Vaultwarden uses regular `bw` CLI:**

```yaml
# compose.yaml fragment (M2+)
services:
  bw-init:
    image: bitwardencli/bw:2025.10
    environment:
      - BW_HOST=https://vaultwarden.ardan.sk
      - BW_CLIENTID=${BW_CLIENTID}
      - BW_CLIENTSECRET=${BW_CLIENTSECRET}
      - BW_PASSWORD=${BW_PASSWORD}
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

M1 = manual lookup; introduce sidecar in M2+ when secret count >10.

## Healthcare-Specific Notes

- **FHIR R4 conformance:** Fasten On-Premises is FHIR-compatible (specific R4/R5 not declared in upstream README). When ingesting custom data (Apple Health, Oura, lab PDFs), construct **valid FHIR R4 Observation/Patient/MedicationRequest** resources, validate via `fhir.resources` pydantic models before POST. Never bypass FHIR layer to write directly to Fasten DB — breaks Fasten data model invariants.
- **LOINC codes** for lab Observations: required for interoperability. Use [LOINC FHIR Terminology Service](https://loinc.org/fhir/) to look up codes for Slovak lab tests. Ollama prompt should include common LOINC codes for top 20 lab panels.
- **GDPR Art. 9 (special category — health data):** Encryption-at-rest mandatory (LUKS/BitLocker). Encryption-in-transit (HTTPS via CF Tunnel). Audit logging of every read/write to FHIR resources. **DPIA required before first paying tenant in M4+.**
- **Data residency:** Hetzner CX22 in EU (Germany/Finland). Cloudflare Tunnel terminates TLS at CF edge — confirm CF data residency for the zone (`ardan.sk`). For SaaS EU pivot: ensure no data leaves EU regions.
- **Audit trail:** Every FHIR resource write should produce an audit log row (separate `audit_log` table in `analytics` DB) — actor, resource type, resource ID, action, timestamp. Required for GDPR Art. 32.
- **Patient consent (M4+):** GDPR Art. 9 explicit consent before processing. Consent management UI required. Out-of-scope for M1 (single-user = self-consent implicit).

## Version Compatibility

| Package A | Compatible With | Notes |
|---|---|---|
| `fasten-onprem:main` (Feb 2026 build) | Docker 24+, Podman 4+ | Distroless `static-debian11`. Currently SQLite-only. Upstream main branch is more current than v1.1.3 release tag. |
| `postgres:16.13-bookworm` | Drizzle 0.45+, postgres@3.4+, psycopg 3.2+ | Supported until November 2028 (PG 16 EOL). |
| `traefik:v3.7.0` | Docker provider, compose labels | v2 → v3 config schema changes; do NOT mix v2 docs blindly. |
| Drizzle `0.45.2` + drizzle-kit `0.31.10` | Postgres 12+, Node 20+ | RLS requires Postgres 9.5+; `pgPolicy` available since 0.36. |
| Next.js 16.2.6 | Node 18.18+, React 19 | App Router stable; Pages Router still works but deprecated. (15.2.4 also supported with same stack.) |
| Cloudflare Tunnel | Any TCP/HTTP backend | TLS terminated at CF; backend can be HTTP-only. |
| `cloudflared` 2026.4.x | Linux/AMD64, ARM64 | Self-update controlled by `--no-autoupdate`. |
| `apple-health-parser` (PyPI) | Python 3.10+ | Tracks Apple's `export.xml` schema; iOS 17+ confirmed. |
| `pytesseract` 0.3.13 | Tesseract binary 5.x | Use Tesseract 5 for LSTM accuracy on Slovak text (`tesseract-ocr-slk` package). |
| `pdfplumber` 0.11.x | Text-mode PDFs from major lab vendors | Image-mode PDFs need OCR fallback. |
| Auth.js v5 (beta) / v4.24.14 | Next.js 15 + 16 | v5 production-ready despite "beta" tag (per Auth.js team). |
| Vaultwarden 1.36.0 | `bw` CLI 2025.10.x | Use regular `bw` CLI, NOT `bws`. |
| Postgres 16 | `pgcrypto`, `pg_trgm`, `pg_stat_statements`, `uuid-ossp`, `citext` | Enable extensions: `CREATE EXTENSION pgcrypto;` etc. in `analytics` DB at init. |
| Ollama 0.4.x | qwen2.5:7b, llama3.2:3b | qwen2.5 better at structured JSON output. llama3.2 3B for low-RAM. |

## Cross-Platform Notes (Windows dev → Linux prod)

1. **Bind-mount paths.** Docker Desktop on Windows expects `/c/...` (lowercase). On Linux: that path doesn't exist. `.env`-driven `HEALTH_DATA_PATH` with `:?` failure-fast.
2. **inotify dead over WSL2 bind mounts.** ETL must poll, never watch via `watchdog`/`watchfiles` — silent drop. Polling is also Linux-portable, so ETL code is unchanged for prod.
3. **Line endings.** Add `* text=auto eol=lf` to `.gitattributes` for `*.sh`, `*.py`, `*.conf`, `*.yml`. Otherwise Windows `core.autocrlf=true` corrupts `entrypoint.sh` files inside images.
4. **File mtime granularity.** NTFS has 100 ns; ext4 has 1 ns. Polling: use `>= last_seen_mtime`, never `==`.
5. **Path case sensitivity.** Windows is case-insensitive; Linux strict. Stick to lowercase + `pathlib.Path` everywhere.
6. **Postgres locale.** Force `C.UTF-8` via `POSTGRES_INITDB_ARGS` so collation order is identical on both platforms; otherwise indexes built on Windows differ from Linux.
7. **BitLocker (Windows) vs LUKS (Linux) at-rest encryption.** Both transparent to Postgres + Fasten. **No code change needed cross-platform.**
8. **CF Tunnel daemon.** `cloudflared` runs identically on both — no Windows-specific tweaks.
9. **`docker compose` plugin.** Same v2 spec on both. Use `compose.yaml` filename consistently.
10. **WSL2 memory limit on Windows.** Docker Desktop default 8 GB RAM cap can starve Postgres + Next.js + ETL + Ollama. Configure `.wslconfig` to allow 12 GB or skip Ollama on dev box.

## Confidence Matrix

| Decision | Confidence | Source |
|---|---|---|
| Fasten on-prem **GPL-3.0** license (NOT MIT) | HIGH | `gh api repos/fastenhealth/fasten-onprem` returned `"license": "GPL-3.0"`. **PROJECT.md and CLAUDE.md state MIT — both must be corrected.** |
| Fasten = SQLite-only (Postgres broken) | HIGH | Direct quote from upstream `config.yaml`: *"postgres will be supported in the future, but is completely **BROKEN** at the moment."* |
| Fasten v1.1.3 latest tagged release; main branch active through Feb 2026 | HIGH | `gh api releases` (latest 2024-10-01) + `commits` (last commit 2026-02-13). |
| Postgres 16.13-bookworm vs alpine | HIGH | Postgres team and ecosystem caveats on musl ICU collation; Docker Hub confirms 16.13-bookworm current; PG 16.13 release Feb 2026. |
| Drizzle ORM `0.45.2` latest stable | HIGH | npm registry direct query 2026-05-09. |
| drizzle-kit `0.31.10` latest stable | HIGH | npm registry direct query 2026-05-09. |
| Drizzle first-class RLS (`pgPolicy` / `crudPolicy`) | HIGH | Drizzle docs at `orm.drizzle.team/docs/rls`; release notes for 0.36.0 + drizzle-kit 0.27.0. |
| Prisma RLS gap | HIGH | GitHub Issue #12735 open since 2022; multiple 2026 articles confirm raw SQL workaround. |
| Next.js `16.2.6` latest (or `15.2.4` conservative) | HIGH | npm registry direct query 2026-05-09 for next; release date 2026-05-07. |
| Traefik v3.7.0 (released 2026-05-05) | HIGH | `gh api repos/traefik/traefik/releases/latest`. |
| Vaultwarden 1.36.0 (released 2026-05-03) | HIGH | `gh api repos/dani-garcia/vaultwarden/releases/latest`. |
| Vaultwarden does NOT expose Bitwarden Secrets Manager API (`bws`) | HIGH | Discussion #3462 on dani-garcia/vaultwarden + Bitwarden docs. |
| `postgres@3.4.9` (porsager) latest | HIGH | npm registry direct query 2026-05-09. |
| Cloudflare Tunnel + Traefik sidecar pattern | HIGH | Multiple community forum posts + gero.dev + Matt Dyson (cited). |
| Cloudflare GDPR posture (ISO 27701, DPF, EU CoC) | HIGH | Cloudflare Trust Hub + DPA docs. |
| Hetzner CX22 specs (€3.79/mo, 2 vCPU/4 GB) + GDPR-by-default (DE/FI DCs) | HIGH | Hetzner pricing page + multiple 2026 reviews. |
| Oura PAT deprecated → OAuth2 only; rate limit 5000 req / 5 min | HIGH | Oura error-handling docs + 3rd-party SDK confirmation. |
| `apple-health-parser` PyPI 2026-03 active | HIGH | PyPI release date + GitHub activity. |
| BitLocker = Docker Desktop Windows recommendation for at-rest | HIGH | Docker Docs (encryption guidance for Windows secrets). |
| Tesseract 5 + Ollama vision validator pattern | MEDIUM | Multiple 2026 OSS projects (validated-table-extractor, llm_aided_ocr, ExtractThinker); accuracy on Slovak lab PDFs **not yet measured** — flagged for plan-phase. |
| Azure Document Intelligence EU + healthcare BAA | MEDIUM | Pricing + region docs; HIPAA-style BAA for healthcare confirmed; **GDPR Art. 28 DPA needs separate sign-off**. |
| pgcrypto sufficient as defense-in-depth | MEDIUM | Postgres docs; we're not relying on it as sole control — FDE + pgcrypto layered. |
| Vaultwarden `bw` CLI sidecar at M2 | MEDIUM | Pattern documented in homelab community but no canonical Vaultwarden-bless'd recipe; some discussion threads from 2022 still relevant. **Will require ~1 day of plan-phase prototyping.** |
| Schema-per-tenant strategy at M4 | MEDIUM | Common Postgres SaaS pattern (Citus blog, Postgres weekly), but **per-tenant Fasten container** orchestration unproven at scale — flagged. |
| Multi-user Fasten reaching feature parity | LOW | Upstream PR #503 added basic user mgmt 2024-08; full multi-tenant story is "WIP" per README. **May force per-tenant container path** in M4. |

## Open Stack Questions for Plan-Phase

These do NOT block stack selection but require decisions during M1 plan:

1. **Fasten `:main` digest pinning cadence.** How often do we re-pin? Proposal: every 8 weeks, with a smoke test (login, manual record entry, sync from a US sandbox provider) before promoting. Plan-phase to define test harness.

2. **License compliance for GPL-3.0** — our Next.js custom analytics layer is *separate* from Fasten (different process, communicates over filesystem volumes only — no linking). This is the **aggregate vs derivative** distinction; aggregate = our analytics is independent. **Confirm legal interpretation before SaaS pivot** (M4). For now (M1 single-user) personal use is unrestricted. **Action: PROJECT.md and CLAUDE.md need correction from "MIT" to "GPL-3.0" when researcher returns.**

3. **Lab PDF OCR baseline accuracy.** Need a benchmark set of 10 anonymized Slovak lab PDFs (Synlab, Alpha Medical, Klinická biochémia) to measure Tesseract+Ollama accuracy vs Azure Document Intelligence. **Plan-phase deliverable: `research/lab-pdf-ocr-bench.md`** with concrete % accuracy on key fields (test name, value, unit, reference range, abnormal flag).

4. **Apple Health → FHIR mapping coverage.** `apple-health-parser` produces typed records, but we need a mapping to FHIR R4 Observation resources for Fasten ingest **OR** we keep Apple Health data only in our analytics DB and skip FHIR conversion in M1. Recommendation: skip FHIR in M1 (analytics-only), add mapper in M3.

5. **Multi-tenant Fasten architecture choice (M4).** **Per-tenant Fasten container** (clean isolation, ~150 MB/tenant) vs **wait for Fasten Multi-User maturity**. Likely answer: per-tenant container until upstream proves OK, but DECIDE before M3 plan.

6. **DICOM viewer (M3).** OHIF Viewer (browser-based, more polished) vs Orthanc (DICOM server, basic web viewer). Probably both — Orthanc as store, OHIF as UI. Plan-phase research.

7. **Backup encryption + offsite target.** `pgbackrest` to S3 with age-encrypted dumps, OR `restic` to Backblaze B2 (EU region). Decision affects budget (B2 EU is ~$5/TB/mo; Hetzner Storage Box is €3.49/TB/mo). M3 decision.

8. **Authentik vs Authelia (M4).** Authentik = polished UI, OAuth2/OIDC provider, larger footprint (~700 MB RAM). Authelia = smaller, headless, fits a 4 GB CX22. Recommend Authelia for M4 unless we need branded login pages for paying tenants — then Authentik in M5.

9. **WSL2 memory cap on Windows dev box.** `.wslconfig` tuning if Ollama vision validator is included; otherwise skip Ollama on dev and run only on prod (or run only for specific batch jobs).

10. **Vaultwarden sidecar specifics** — `bw login --apikey` vs `bw login --raw` flow, session refresh policy, what happens when Vaultwarden is unreachable at boot. Plan-phase prototype required.

11. **Next.js 15 vs 16 choice** — 16.2.6 is brand new (released 2026-05-07). For M1 stability, 15.2.4 is conservative. For M2+ feature completeness, 16. Decide in plan-phase based on actual Next.js 16 issue-tracker velocity at that time.

## Sources

**Authoritative — Fasten:**
1. [fastenhealth/fasten-onprem GitHub repo](https://github.com/fastenhealth/fasten-onprem) — license GPL-3.0 verified via `gh api`
2. [Fasten v1.1.3 release (2024-10-01)](https://github.com/fastenhealth/fasten-onprem/releases/tag/v1.1.3)
3. Fasten `config.yaml` (raw text via `gh api`) — explicit "postgres BROKEN" warning
4. Fasten `docker-compose-prod.yml` — `ghcr.io/fastenhealth/fasten-onprem:main` is the canonical prod tag
5. [Fasten user docs](https://docs.fastenhealth.com/getting-started/main.html) — installation steps

**Authoritative — Postgres:**
6. [PostgreSQL Docs — Encryption Options (16)](https://www.postgresql.org/docs/16//encryption-options.html)
7. [PostgreSQL Versioning Policy](https://www.postgresql.org/support/versioning/) — 5-year support windows
8. [PostgreSQL release news (Feb 2026)](https://www.postgresql.org/about/news/postgresql-182-178-1612-1516-and-1421-released-3235/) — current patch versions
9. [PostgreSQL TDE wiki](https://wiki.postgresql.org/wiki/Transparent_Data_Encryption) — confirms TDE not in community edition
10. [Docker Hub — postgres official image](https://hub.docker.com/_/postgres) — current tags, alpine variants

**Authoritative — Drizzle / Next.js / Auth:**
11. [Drizzle ORM RLS docs](https://orm.drizzle.team/docs/rls) — `pgPolicy`, `crudPolicy`, role helpers
12. [drizzle-kit 0.27.0 release notes](https://github.com/drizzle-team/drizzle-orm/releases/tag/drizzle-kit@0.27.0)
13. [Drizzle 0.36.0 release notes](https://github.com/drizzle-team/drizzle-orm/releases/tag/0.36.0)
14. [Prisma RLS Issue #12735](https://github.com/prisma/prisma/issues/12735) — open since 2022
15. [Next.js 15 + Drizzle + Postgres tutorial (Strapi blog)](https://strapi.io/blog/how-to-use-drizzle-orm-with-postgresql-in-a-nextjs-15-project)
16. [Neon RLS + Drizzle guide](https://neon.com/docs/guides/rls-drizzle) — `crudPolicy` patterns
17. npm registry direct queries 2026-05-09: `drizzle-orm@0.45.2`, `drizzle-kit@0.31.10`, `next@16.2.6`, `postgres@3.4.9`, `next-auth@4.24.14` (latest stable) / `^5.0.0-beta.x`

**Authoritative — Traefik / Cloudflare:**
18. [Traefik v3.7.0 release (2026-05-05)](https://github.com/traefik/traefik/releases) — verified via `gh api`
19. [Traefik v3 + Cloudflare Tunnel community thread](https://community.traefik.io/t/how-to-correctly-use-traefik-with-cloudflare-tunnel-on-docker/25526)
20. [Matt Dyson — Using Traefik with Cloudflare Tunnels (2024)](https://mattdyson.org/blog/2024/02/using-traefik-with-cloudflare-tunnels/)
21. [Gero.dev — cloudflared + traefik + docker walkthrough](https://gero.dev/blog/cloudflared-traefik-docker)
22. [Cloudflare GDPR Trust Hub](https://www.cloudflare.com/trust-hub/gdpr/) — ISO 27701, DPF, EU CoC certifications
23. [Cloudflare DPA](https://www.cloudflare.com/cloudflare-customer-dpa/)

**Authoritative — Apple Health / Oura:**
24. [`apple-health-parser` on PyPI](https://pypi.org/project/apple-health-parser/) — March 2026 release
25. [GitHub alxdrcirilo/apple-health-parser](https://github.com/alxdrcirilo/apple-health-parser) — active 2026 maintenance
26. [Oura API docs (root)](https://support.ouraring.com/hc/en-us/articles/4415266939155-The-Oura-API)
27. [Oura error-handling docs](https://cloud.ouraring.com/docs/error-handling) — 5000 req / 5 min rate limit
28. [Pinta365/oura_api SDK](https://github.com/Pinta365/oura_api) — confirms PAT deprecated, OAuth2 only

**Authoritative — OCR / Encryption / Hosting / Vaultwarden:**
29. [Tesseract OCR guide (Unstract, 2026)](https://unstract.com/blog/guide-to-optical-character-recognition-with-tesseract-ocr/)
30. [LLM-Aided OCR (Dicklesworthstone)](https://github.com/Dicklesworthstone/llm_aided_ocr) — Tesseract + LLM postprocess pattern
31. [validated-table-extractor (vision LLM validator)](https://github.com/2dogsandanerd/validated-table-extractor)
32. [Azure Document Intelligence pricing](https://azure.microsoft.com/en-us/pricing/details/document-intelligence/) — $1.50/1000 read + $10/1000 prebuilt
33. [Hetzner CX22 plans](https://www.hetzner.com/cloud/regular-performance) — €3.79/mo, 2 vCPU / 4 GB / 40 GB
34. [OneUptime — How to Encrypt Docker Volumes at Rest (2026-02)](https://oneuptime.com/blog/post/2026-02-08-how-to-encrypt-docker-volumes-at-rest/view)
35. [Docker Docs — manage sensitive data](https://docs.docker.com/engine/swarm/secrets/) — BitLocker recommendation for Windows hosts
36. [Vaultwarden Docker Secrets Discussion #3462](https://github.com/dani-garcia/vaultwarden/discussions/3462) — confirms no Secrets Manager API
37. [Bitwarden Secrets Manager CLI docs](https://bitwarden.com/help/secrets-manager-cli/) — `bws` is NOT supported by Vaultwarden
38. [age vs gpg (Filo's blog)](https://age-encryption.org/) and [Switching from GPG to age (Luke Hsiao)](https://luke.hsiao.dev/blog/gpg-to-age/)
39. [PostgreSQL pgcrypto docs](https://www.postgresql.org/docs/current/pgcrypto.html)

**Internal references:**
40. `c:/ANDREJ/Claude/Projects/aios/.planning/research/STACK.md` — format reference (NOT content reuse)
41. `c:/ANDREJ/Claude/Projects/health/.planning/PROJECT.md` — project constraints
42. `c:/ANDREJ/Claude/Projects/health/BOOTSTRAP.md` — handoff decisions
43. `c:/ANDREJ/Claude/Projects/health/CLAUDE.md` — PII Tier 1 + cross-aware isolation rules

---
*Stack research for: Health — Fasten Health Aggregator + SaaS Pivot Path*
*Researched: 2026-05-09*
