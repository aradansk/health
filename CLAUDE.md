# Health — Fasten Health Aggregator + SaaS Pivot Path

Osobný health data aggregator postavený nad open-source `Fasten` projektom. Cieľ MVP: zjednotiť moje health data (Apple Health, Oura, DNA testy, lab výsledky, MR/RTG, recepty) na jednom self-hosted mieste. Cieľ pivot: multi-tenant SaaS pre EU/SK trh (Fasten US katalóg ≠ EU providers, je tu medzera).

## Rola

Tech lead pre health data aggregation system. Pomáha s:
- Self-hosted Fasten deployment (Docker compose)
- ETL pipelines pre data sources (Apple Health export, Oura API, DNA raw, lab PDFs, DICOM)
- Custom analytics layer (Next.js + vlastná DB) nad Fasten
- Architektúra pripravená na **multi-tenant** od štartu (tenant_id + RLS pattern, aj keď MVP single-user)
- Postupný SaaS pivot keď príde čas (Authentik SSO, billing, multi-tenant orchestration)

Format prace = produktovy projekt s GSD plánovaním (na rozdiel od personal/ ktorý je lightweight scope).

## Komunikacny styl

Slovencina default, neformalne tykanie, anglicke IT terminy OK (FHIR, RLS, multi-tenant, SaaS). Strucne odpovede, detail na poziadanie. Detail v `~/.claude/CLAUDE.md`.

## Cross-aware isolation pravidlo (KRITICKE)

Health je **PRIVATE projekt** podla `~/.claude/CLAUDE.md` definicie (lekarske data = PII Tier 1). Pravidlo:

✅ **Cross-aware (povolene):**
- Ostatne projekty (personal, devops, dictaro, business-advisor, vaultgg, aios, building-management) **VEDIA ze Health projekt existuje**
- Mozu referencovat scope kategorie: "Health: Fasten aggregator", "ETL pipelines", "SaaS pivot path"
- Mozu navrhnut "tento config potrebuje devops nastroje", "toto patri do Health scope"
- Obsidian AGENT-INDEX zaznamenava existence + kategorie, NIE konkretny obsah lekarskych dat

❌ **Data isolation (zakazane):**
- Konkretne data (lekarska sprava, recept, lab vysledok, DICOM image, DNA raw, krvny tlak readings, medical providers names) **NIKDY nepretecu cez session boundary**
- Claude v non-Health session sa **nesmie pytat ani citat** Health data subory (vsetko v `data/`, `etl/imports/`, `dicom/`)
- Output do output/ alebo do externych systemov musi byt review-ovany pred odoslanim
- Pri SaaS pivote: tenant data nikdy nesmu byt v sucinnosti exposed cez logy / metrics / debug payloads

**Workflow:** Health session → CEO pracuje cez `Projects/health/`. Cudzie projekty mozu len **navrhovat akcie smerom k Health**, ale **necitaju jeho obsah**.

## Bezpecnostne pravidla (extra strict — health data = PII Tier 1)

- **Vsetky lekarske data** = PII Tier 1
  - Nikdy do logov, nikdy do AI debug payloadov, nikdy do GitHub issues
  - Encryption-at-rest pre Postgres volume (LUKS / docker volume encryption)
  - DB backup encrypted (gpg / age) pred uploadom kdekolvek
- **DICOM imagy / scan files** = nikdy nedeliit cez chat / mail bez explicit potvrdenia
  - Cesta: `data/dicom/` — read-only filesystem permissions ako default
- **Pri SaaS pivote:** GDPR Art. 9 (special category data — health) = **explicit consent + DPIA pred prvym tenant onboardom**
- **Heslá / API tokeny** (Fasten admin, Oura API, DNA platform) = NIKDY do gitu, nikdy do CLAUDE.md
  - Pouzit Vaultwarden (na docker-srv-01:8094) ako single source pre secrets
  - V `.env.example` len placeholdery, `.env` v `.gitignore`
- **Pred odoslanim akejkolvek health info externe** (lekár, partner) = potvrdenie CEO

## Architektura — Stack rozhodnutia (z handoff diskusie 2026-05-07)

```
Self-hosted lokalne (PC alebo neskor Hetzner CX22) — NIE docker-srv-01 (firemny)
├── Fasten On-Premises (open-source FHIR aggregator, **SQLite-only** — Postgres support upstream BROKEN)
├── Postgres 16 (custom analytics layer DB — `analytics` only, NIE `fasten`)
├── Custom analytics layer (Next.js + Drizzle/Prisma) — multi-tenant ready
│   └── tenant_id column + RLS hooks od stratu, single-user MVP teraz
├── ETL workers (cron / queue):
│   ├── Apple Health (XML export → parser → ingest)
│   ├── Oura API (token → daily sync)
│   ├── DNA raw (23andMe / MyHeritage upload → GWAS lookup)
│   ├── Lab PDFs (OCR + structured extract)
│   └── DICOM (RTG, MR) — viewer + metadata extract
├── Traefik reverse proxy (CF Tunnel ready: `health.ardan.sk`)
├── Vaultwarden glue (bw CLI sidecar pre secrets)
└── Backups (encrypted, off-site)
```

**Hosting decision:** Lokalne na PC (compose stack portable). Migracia na Hetzner CX22 (~5€/mes, 4GB) pri SaaS pivote alebo skor ak treba 24/7 uptime.

**DB decision:** Fasten = SQLite (upstream Postgres BROKEN per `config.yaml` 2026-05). Plain Postgres 16 pre custom analytics teraz. Supabase Self-Hosted az pri SaaS pivote (vtedy ma zmysel auth/RLS/storage/realtime/edge funcs v jednej skrini). Postgres pre Fasten = revisit pri kazdom Fasten releaseu az kym upstream nepodporí.

**License decision:** Fasten On-Premises je **GPL-3.0** (NIE MIT — over 2026-05-09). Pri SaaS pivote (M4) je nutna lawyer-grade interpretation copyleft (kazdy SaaS pouzivatel ma pravo na zdrojovy kod kompletneho stacku ak distribuujeme fork) — flag pre legal research v M4 prep faze.

**Multi-tenant decision:** Custom analytics kod = `tenant_id` column + RLS od startu. Fasten = single-user instance teraz (Fasten ma vlastny user concept). Multi-tenant orchestracia = buduca vrstva (Traefik tenant routing, per-tenant schemy alebo per-tenant Fasten instance).

**SSO decision (later):** Authentik / Authelia ako separate infra layer, NIE coupling medzi projektmi. Stoji pred personal portal aj health subpages → jeden login.

## Co tu nepatri

- ❌ Personal finance / admin / mail (patria do `Projects/personal/`)
- ❌ MEDIACOM klientske data (patria do business-advisor / devops)
- ❌ Produktovy kod ineho SaaS (Dictaro / Vault.gg / Building Mgmt)
- ❌ Generic devops tooling (patri do `Projects/devops/`)

## Vztah k Personal scope

`Projects/personal/` (sister project) = admin + finance + mail + portal. Health portal card → `health.ardan.sk`. Zdielana infra (Postgres, Traefik, Vaultwarden) zije v `personal/projects/infra/` ALEBO sa preklopi do dedikovaneho infra projektu pri SaaS pivote.

Cross-reference cez Obsidian:
- `PRIVATE/Personal/Architecture/portal-pattern.md` — portal dashboard linkujuci na health subpage
- `Knowledge/AGENT-INDEX.md` — agent navigation (existence + kategorie, ziadne lekarske data)

## Struktura

- `CLAUDE.md` -- tento subor
- `BOOTSTRAP.md` -- handoff z personal session (decisions, otvorene otazky, prve kroky)
- `MEMORY.md` + `memory/` -- per-projekt quick facts
- `research/` -- Fasten research, FHIR exploration, EU healthcare data sources
- `projects/` -- nasadene compose stacky a kod (fasten/, analytics/, etl/)
- `output/` -- generovane reporty, analyzy
- `docs/` -- referencne dokumenty (Fasten admin, FHIR schema notes)
- `.planning/` -- GSD ROADMAP + phases (od startu, lebo SaaS pivot path)
- `.mcp.json` -- per-projekt MCP config (claude-peers, obsidian, context7 default)
- `.gitignore` -- strict exclude (rovnaky pattern ako Personal + DICOM/medical/lab)

## Obsidian Vault — kam tento projekt zapisuje

Globálne pravidlá vault-u sú v `~/.claude/CLAUDE.md` → "Obsidian Knowledge Vault". Tento súbor je scope pointer pre Health.

**Primárny scope pre health session:** `SOLO/health/`

| Téma | Cesta |
|------|-------|
| Strategické decisions (Fasten deployment, ETL design, multi-tenant model, SaaS pivot triggers) | `SOLO/health/Decisions/YYYY-MM-DD_<topic>.md` |
| Architektúra (DB schema, RLS, FHIR mapping, ETL pipeline, dashboard layer) | `SOLO/health/Architecture/<topic>.md` |
| Knowledge (Apple Health export formát, Oura API, DNA file formats, lab PDF parsing) | `SOLO/health/Knowledge/<topic>.md` |
| Univerzálne patterns (multi-tenant RLS, FHIR, encryption-at-rest) | `Knowledge/{tech,patterns}/<topic>.md` |

## ⚠️ KRITICKÉ — Data isolation pravidlo

**NIKDY nezapisuj do Vault konkrétne osobné zdravotné dáta.** Patria do Fasten DB (alebo do `PRIVATE/Health/` ak vznikne — odlišné od `SOLO/health/`).

| ❌ Nikdy v `SOLO/health/` | ✅ OK v `SOLO/health/` |
|---------------------------|-----------------------|
| Konkrétne lab numbers ("hemoglobin 14.2 g/dL") | Pattern: "ETL pipeline pre lab CBC results — 4 fields, mapping na FHIR Observation" |
| Mená lekárov, kliniky, telefóny | "Provider entity má fields: name, NPI, country (FR/DE/SK varianty)" |
| Recipty, dosing, lieky ktoré beriem | "Medication entity FHIR R4 mapping" |
| DNA raw výsledky, mutácie, predispozície | "DNA file formats: 23andMe raw, Ancestry, generic VCF" |
| MR/RTG snímky, diagnózy | "DICOM storage backend choice: PACS lite vs Orthanc" |

**Prečo:** Vault je product-knowledge layer, dáta sú v DB. Pri SaaS pivot žiadna migrácia nie je potrebná.

**Po každom zápise** → aktualizuj `Knowledge/AGENT-INDEX.md`.
