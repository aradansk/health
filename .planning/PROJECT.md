# Health — Personal Health Data Aggregator (Fasten + ETL + SaaS pivot path)

## What This Is

Self-hosted aggregator pre osobne zdravotne data postaveny nad open-source [Fasten On-Premises](https://github.com/fastenhealth/fasten-onprem) (FHIR-based). Zjednocuje moje data zo wearables, lab vysledkov, recepty a zdravotneho rekordu na jednom mieste. Architektura je **multi-tenant ready od prveho dna** — single-user MVP teraz, pripravene na **SaaS pivot pre EU/SK trh** (Fasten US katalog 30k+ providers nepokryva EU healthcare → manual import niche).

Pouzivatel teraz: Andrej (single-user). Pouzivatel pri pivote: health-conscious enthusiasts (kvantyfikacia self), sukromne kliniky pre patient-side self-host, B2C "moja zdravotna zlozka" platforma pre EU/SK obcanov.

## Core Value

**Vsetky moje zdravotne data na jednom mieste, vyhladatelne a vlastne ovladane.** Ked dnes potrebujem najst lab vysledok z minulych 5 rokov, recept z dvoch lekarov alebo zmeranie spanku z Oura korelovat s krvnym tlakom, hladam to v 4-5 silos. Ciel: jeden self-hosted UI, jeden FHIR-spravidlovany kanon dat, vlastnictvo + suverenita nad svojimi datami.

## Requirements

### Validated

(None yet — ship to validate)

### Active

**M1 — MVP Self-Hosted (single-user, "co najskor"):**

- [ ] Fasten On-Premises beziaci v Docker compose stacku (PC docker desktop)
- [ ] Apple Health export import (XML → FHIR ingest)
- [ ] Oura API daily sync (OAuth token → daily ETL job)
- [ ] Lab PDF parser (OCR + structured extract → FHIR Observation resources)
- [ ] Custom analytics layer (Next.js + Postgres `analytics` DB, `tenant_id` + RLS od startu)
- [ ] Reverse proxy (Traefik) pripraveny pre `health.ardan.sk` cez CF Tunnel (deploy az v dalsich fazach)
- [ ] Encryption-at-rest pre Postgres volume (LUKS / docker volume encryption)
- [ ] Secrets cez Vaultwarden lookup (manualne v M1, automaticky `bw` sidecar v M2+)

### Out of Scope

**M1 OOS (presunute do dalsich milestonov):**

- DNA raw upload + GWAS lookup (23andMe / MyHeritage) — M2 (komplexne, nie kazdodenne pouzitie)
- DICOM viewer pre RTG / MR / CT — M2 (vyzaduje samostatny komponent ako OHIF Viewer / Orthanc, nestoji v ceste M1 hodnote)
- Authentik / Authelia SSO — M4 SaaS pivot prep (M1 single-user, Fasten ma vlastny auth)
- Hetzner CX22 cloud deploy — pri raste alebo SaaS pivote (M1 lokalne na PC docker desktop)
- Mobile native app — postacuje responsive web v M1, native by stal $$$ + maintenance
- Realtime data streaming (kafka, websockets) — daily sync je dost pre wearable / lab data
- AI / LLM analyzy zdravotnych dat — explicitne mimo MVP scope (PII Tier 1, regulacny aspekt)

**Permanentne OOS (nie pre tento projekt):**

- Doctor portal / clinic-side workflow — Fasten je patient-side, ostatne riesenia (athenahealth, EpicCare) su iny trh
- Insurance billing automation — mimo scope, slozite regulacne
- Telemedicina / video calls — nie je core value (data aggregation, NIE diagnostika)

## Context

**Technicky ekosystem:**

- Self-hosted lokalne (PC docker desktop pri vyvoji), mozna migracia na Hetzner CX22 (~5€/mes, 4GB RAM) pri SaaS pivote alebo skor ak treba 24/7 uptime
- Stack: Docker Compose + Postgres 16 (multi-DB: `fasten`, `analytics`) + Fasten On-Premises + Next.js + Traefik + Vaultwarden glue
- Postgres 16 plain teraz, prechod na Supabase Self-Hosted az pri SaaS pivote (auth/RLS/storage/realtime/edge funcs v jednej skrini)
- Multi-tenant: `tenant_id` column + RLS hooks v custom kode od dna 1, Fasten = single-user instance teraz, pri SaaS = per-tenant Fasten instance ALEBO Fasten Multi-User (treba research)

**Prior work:**

- Handoff z Personal session 2026-05-07 (BOOTSTRAP.md — strategicke rozhodnutia, preco samostatny projekt, 2-fazovy plan)
- Discord diskusia 2026-05-06 az 2026-05-07 v Personal kanali (8+ sprav, decisions zachytene v BOOTSTRAP.md)
- Personal scope (`Projects/personal/`) je sister projekt — admin/finance/mail/portal, lightweight bez GSD overhead

**User feedback / motivation:**

- CEO osobna potreba: aktualne data v silos (Apple Health, Oura, lab faktury, recepty od 2 lekarov), neda sa korelovat
- Trh pozorovany: Fasten = US-first, EU healthcare ekosystem (eHealth SK, ePZP, EU Health Data Space) ma medzeru
- Distinkcia od MEDIACOM: NIE klientsky IT outsourcing, JE B2C/B2B SaaS produkt po pivote

**Znamene issues / risks:**

- PII Tier 1 = lekarske data, encryption + access control kritical od dna 1
- GDPR Art. 9 (special category data — health) = explicit consent + DPIA pred prvym tenant onboardom (pri SaaS pivote)
- Fasten US providers katalog ne-aplikovatelny na EU → manual data import workflow je core differentiator a zaroven biggest engineering risk

## Constraints

- **Tech stack:** Docker Compose + Postgres 16 + Fasten On-Premises + Next.js + Traefik. Nie ine DB / nie iny FHIR backend. Ration: Fasten je open-source FHIR aggregator s aktivnou komunitou, Postgres je default volba pre data layer, Next.js je defaultny full-stack framework pre custom analytics.
- **Hosting (M1):** PC docker desktop. Ration: zero-cost, full control, real PII data v cloude vyzaduje DPIA prep (M4 prep), pred tym lokalne.
- **Hosting (M4+):** Hetzner CX22 (~5€/mes, 4GB) ako SaaS-ready target. Ration: EU jurisdikcia (GDPR Art. 28 jednoduchsie), CF Tunnel ready, IPv4 + dostatok RAM.
- **Multi-tenant readiness:** od dna 1. Ration: SaaS pivot path je realny (5 milestones M1→M5), refactor "single-user → multi-tenant" by si vyzadal velky rebuild ak nie je `tenant_id` v schema od startu.
- **Security:** PII Tier 1 = encryption-at-rest, encrypted backups (gpg / age), no PII v logoch / debug payload, no PII v gite (.gitignore strict pattern). Pri SaaS pivote: GDPR Art. 9 + DPIA + Art. 32 technical measures.
- **Timeline (M1):** "co najskor" — ciel ~1 mesiac od plan-phase 1 (subject to research findings + plan complexity).
- **Budget:** 0 € pre M1 (lokalny PC, free open-source), ~5 €/mes od M4+ (Hetzner). SaaS pivot revenue ciel definovany az v M5.
- **Dependencies:** Fasten On-Premises (open-source, MIT license). Oura API token (osobny). Apple Health iOS export (manual). Vaultwarden (uz nasadeny v `docker-srv-01:8094` ale pre Personal/Health vlastny copy lokalne).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 2 separate projekty (Health + Personal) | Finance NIE je realny SaaS produkt (B2C trh saturovany YNAB/Monarch); Health JE realna SaaS pivot path (EU healthcare medzera). GSD overhead opravneny len pre produktovy projekt. | — Pending |
| Fasten On-Premises ako FHIR backend | Open-source, aktivny vyvoj, MIT license, FHIR R4 spravne, US katalog providers (zaklad), vlastnictvo dat | — Pending |
| Plain Postgres 16 v M1 (NIE Supabase) | Multi-DB v jednom containeri staci pre single-user, Supabase Self-Hosted ma zmysel az pri SaaS pivote (auth/RLS/storage v jednej skrini) | — Pending |
| Multi-tenant readiness od dna 1 (`tenant_id` + RLS) | Refactor single→multi by stal velky rebuild, schema-level pripravenost je lacna teraz | — Pending |
| Lokalny PC docker desktop v M1 (NIE Hetzner) | Zero-cost, no PII v cloude pred DPIA prep, vyvoj rychlejsi lokalne | — Pending |
| Traefik + CF Tunnel ready (deploy v M2+) | Tunel cez `health.ardan.sk` az ked je lokal stable; lokalny development LAN-only | — Pending |
| Apple Health + Oura + Lab PDF + Custom analytics v M1 | Najjednoduchsie data pipelines + najvacsi user value (denne data); DNA + DICOM v M2 (komplexne, nie kazdodenne) | — Pending |
| `Projects/health/` je PRIVATE projekt (cross-aware isolation) | Lekarske data = PII Tier 1, ostatne projekty smu vediet ze Health existuje ale nesmu citat data | — Pending |
| Encryption-at-rest pre Postgres volume od dna 1 | PII Tier 1 + multi-tenant ready = nemoze byt afterthought | — Pending |
| Secrets cez Vaultwarden (manualne v M1, `bw` sidecar v M2+) | Konzistentne s personal portfolio (Vaultwarden je nasadeny), automatizacia ked >10 secretov | — Pending |

## Open Research Items

(Tieto sa vyriesia v `.planning/research/` faze pred planom Phase 1.)

1. **Fasten verzia:** stable release vs. nightly? (overit `github.com/fastenhealth/fasten-onprem/releases`, najnovsi stable je default odporucanie)
2. **Multi-tenant Fasten:** existuje natively (Multi-User mode) alebo treba per-tenant instance? Ak per-tenant: Traefik routing pattern, shared Postgres / per-tenant DB, resource implications
3. **EU FHIR providers landscape:** ake datove zdroje su v EU/SK dostupne (eHealth, ZdravotnaKarta SK, ePZP, EU Health Data Space)? Co bude manual import workflow pre v1?
4. **Lab PDF OCR pipeline:** existujuce OSS riesenia (Tesseract + structured extract via LLM, alebo dedikovane medical OCR)? Cost trade-off cloud vs lokalny LLM
5. **Apple Health XML schema:** kompatibilita s FHIR R4, mapper alebo ETL transformacia
6. **Oura API:** OAuth flow + rate limits + pripadne webhook support pre realtime daily sync

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-07 after initialization (handoff from Personal session)*
