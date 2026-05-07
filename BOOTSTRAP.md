# Bootstrap — Handoff z Personal session 2026-05-07

Tento dokument je **prvy kontext** pre novu Claude Code session v `Projects/health/`. Sumarizuje vsetky decisions zo strategickej diskusie cez Discord (kanal Personal) ktora sa odohrala 2026-05-06 az 2026-05-07. Po precitani by mala nova session vediet:
- preco Health vznikol ako samostatny projekt (oddeleny od Personal)
- ake su jeho dve fazy (single-user MVP → multi-tenant SaaS pivot)
- aku architekturu sme zvolili a preco
- ake otvorene otazky este caju na rozhodnutie
- co je prvy konkretny krok

## TL;DR

Health = **2. SOLO/PRIVATE produktovy projekt** v Andreho portfoliu (vedla Dictaro, Vault.gg, Building Mgmt). Zaciname **single-user MVP self-hosted Fasten** + ETL pipelines pre vlastne data, **architektura od startu multi-tenant ready**, SaaS pivot path = EU/SK health aggregator nika (Fasten US katalog ≠ EU providers).

## Preco samostatny projekt (nie sub-modul Personal)

**Diskusia 2026-05-07:** CEO sa pytal "1 GSD projekt s milestones / 2 separate projekty / GSD workstreams?". Po analyze:

1. **Finance NIE je realny SaaS produkt** (5-10% pravdepodobnost). Trh personal finance B2C saturovany (YNAB/Monarch/Mint/Spendee), banky dominuju, network effects. Ostane single-user forever.

2. **Fasten Health JE realny SaaS pivot path:**
   - EU/SK trh: Fasten US katalog 30k+ providers nepokryva EU healthcare → manual import niche
   - Cieloskupina: health-conscious enthusiasts (kvantyfikacia self), sukromne kliniky pre patient-side self-host, B2C "moja zdravotna zlozka" platforma
   - Distinkcia od MEDIACOM: NIE klientsky IT outsourcing, JE B2C/B2B SaaS produkt

3. **Verdikt:** 2 projekty.
   - `Projects/personal/` = admin + finance + mail + portal (lightweight, bez GSD overhead)
   - `Projects/health/` = Fasten + GSD od startu (SaaS pivot path = produktove planovanie ma zmysel)

**Pri SaaS pivote** = `Projects/health/` premenovat na `Projects/fasten/` (alebo rovno separate company), Obsidian scope migrovat z `PRIVATE/Personal/` do `SOLO/health/` alebo vlastneho scope. Refactor = 5 minut, lebo architektura uz bude multi-tenant ready.

## Dve linie celkoveho personal portfolia (kontext)

CEO definoval 2026-05-07:

**Linia 1 — Health (TENTO PROJEKT):**
- Self-hosted Fasten On-Premises (FHIR aggregator)
- Apple Health import (CDA/XML export)
- Oura API daily sync
- DNA testy (23andMe/MyHeritage raw + GWAS)
- Lab vysledky (PDF OCR + structured)
- MR / RTG (DICOM viewer + metadata)
- Dlhodoby cielh: SaaS pre EU (multi-tenant)

**Linia 2 — Finance (`Projects/personal/`, NIE TU):**
- Self-hosted finance app (Firefly III / Maybe / Actual — TBD)
- Faktury, vypisy uctov, danovy kalendar, vypocty
- Single-user forever

## Architektura — Stack decisions

### Hosting
- **Teraz:** Lokalne na PC (PC1 alebo PC2 — TBD), Docker compose stack
- **Neodporucame:** docker-srv-01 = firemny server, Personal/Health = strict isolation
- **Pri raste / SaaS:** Hetzner CX22 (~5€/mes, 4GB RAM, dosta pre Fasten + Postgres + analytics)

### DB
- **Teraz:** Plain Postgres 16, jeden container, multi-DB (`fasten`, `analytics`)
- **Pri SaaS pivote:** Supabase Self-Hosted (auth/RLS/storage/realtime/edge funcs v jednej skrini)

### Multi-tenant readiness
- Custom analytics kod = `tenant_id` column + RLS od startu (single-user MVP, ale schema pripravena)
- Fasten = single-user instance teraz (Fasten ma vlastny user concept)
- Pri SaaS = per-tenant Fasten instance ALEBO Fasten Multi-User mode (treba overit, github.com/fastenhealth)

### Reverse proxy + domeny
- Traefik v compose stacku
- CF Tunnel ready: `health.ardan.sk` (CEO si CF zonu presunie sam, "az v dalsich fazach")
- LAN-only mode pre lokalny development

### Secrets / Vaultwarden glue
- `bw` CLI cez sidecar container, login session v shared volume
- Init container pred app startom: fetch secrets → inject ako env vars
- **Pre teraz:** Vaultwarden manualne (lookup na popozadi). Automatizacia keď bude >10 secretov.

### SSO (later concern)
- Authentik / Authelia ako separate infra layer
- Stoji pred personal portal + health subpages → jeden login
- NIE coupling medzi projektmi

### Prepojenie Personal ↔ Health (portal pattern)
- `personal.ardan.sk` (alebo root) = Personal dashboard s kartami
- Card "Health" → `health.ardan.sk` (Fasten UI + custom analytics)
- ZIADNY tight integration / cross-API fetcher (kratky overhead, krehke pri zmenach upstream schem)

## Otvorene otazky pre prvu Health session

1. **Lokalny host:** PC1 alebo PC2? Ktory je 24/7? Alebo rovno Hetzner CX22 (5€/mes, verejna IP, CF Tunnel ready, vyssia HA)?
2. **GSD startup:** spustit `/gsd:new-project` s kontextom z tohto BOOTSTRAP.md? Ja by som odporucil ano — produktovy projekt s SaaS pivot path = GSD workflow je primerany.
3. **Fasten verzia:** stable release alebo nightly? (overit github.com/fastenhealth/fasten-onprem releases)
4. **EU providers research:** zacat s `research/2026-05-XX_eu-fhir-providers.md` — ake datove zdroje su v EU dostupne (eHealth, ZdravotnaKarta SK, ePZP, EU Health Data Space)?
5. **Fasten Multi-User mode:** existuje natívne, alebo treba per-tenant instance? (technical research before MVP architecture lock-in)

## Prve konkretne kroky (navrh poradia)

1. **`/gsd:new-project`** v `Projects/health/` — vytvorit PROJECT.md, ROADMAP.md s milestones:
   - **M1: MVP Self-Hosted (single-user)** — Fasten + Postgres + Traefik + manual data import
   - **M2: ETL Pipelines** — Apple Health, Oura, DNA, Lab PDFs, DICOM
   - **M3: Custom Analytics Layer** — Next.js + Drizzle, multi-tenant ready schema
   - **M4: SaaS Pivot Prep** — Authentik SSO, billing prep, multi-tenant orchestration, GDPR/DPIA dokumenty
   - **M5: SaaS Soft Launch** — prvy paying tenant (klinika alebo enthusiast pilot)

2. **Research fáza** (parallelne s M1):
   - `research/fasten-onprem-deployment.md` — Docker compose, requirements, gotchas
   - `research/eu-fhir-providers.md` — co je v EU dostupne, co bude manual import
   - `research/multi-tenant-fasten.md` — multi-user mode review, alternatives

3. **First commit:** `git init`, `.gitignore`, README.md, scaffolding empty subfolders

## Zdielana infra s Personal scope

V navrhu architektury som spomenul ze shared Postgres / Traefik / Vaultwarden glue **moze zit v `personal/projects/infra/`** alebo dedikovany infra repo. Health Claude Code session si moze tieto sluzby z nej **referencovat** ale **nesmie modifikovat** mimo session boundary.

**Praktickejsie odporucanie:** Health ma vlastnu compose stack copy (Postgres + Traefik) v `Projects/health/projects/infra/`. Pri SaaS pivote alebo migracii na Hetzner sa to oddeli ako standalone deployment. Personal Finance ma svoju copy. Duplicate je male (compose YAML), zato isolation je cista.

## Cross-references

- **Personal scope (sister project):** `Projects/personal/` — admin/finance/mail/portal, viď jeho `CLAUDE.md` a `memory/project_split_2026-05-07.md`
- **Discord channel:** kanal Personal (id: 1501221137156411588) — pôvodný diskusiá BOLA tam, ALE odteraz Health má vlastnú session v tomto adresári. Discord odpovede z tohto adresára by mali ist do nového Discord kanálu (ak CEO vytvori) alebo zostat v terminali.
- **Obsidian vault scope:**
  - Teraz (single-user): `PRIVATE/Personal/Architecture/health-system.md`
  - Po SaaS pivote: `SOLO/health/` alebo vlastny scope
- **BA / cross-research:** `Projects/business-advisor/research/2026-04-15_abdaal-lifestyle-business-roadmap-research.md` — Abdaal 6P framework použiteľný ako META-rámec pre validáciu Fasten SaaS pivota (offer sheet → 10 discovery calls → až potom multi-tenant rebuild)

## Bezpecnostne reminders pre prvu session

- **PII Tier 1:** vsetky lekarske data, DICOM, lab vysledky, recepty
- **Encryption-at-rest:** Postgres volume (LUKS / docker volume encryption) — setup od dna 1
- **Backup encryption:** gpg / age pred uploadom kdekolvek
- **Pri SaaS pivote:** GDPR Art. 9 special category data + DPIA pred prvym tenant onboardom

---

**Vytvorene:** 2026-05-07
**Z session:** Personal scope (`Projects/personal/`)
**Discord kontext:** kanal Personal, message_id 1501459530712612895 → 1501898104574574772 (8 sprav, plus celych 4-5 round-trip diskusie 2026-05-06 az 2026-05-07)
