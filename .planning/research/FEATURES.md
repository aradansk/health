# Feature Research — Health Data Aggregator (Fasten + Custom Layer)

**Domain:** Self-hosted personal health record (PHR) aggregator with EU/SK SaaS pivot path
**Researched:** 2026-05-09
**Confidence:** MEDIUM-HIGH (Fasten OOTB capabilities verified via GitHub README + v1.0.0 release notes; EU healthcare landscape verified via EHDSI/HL7 EU sources; multi-user verdict has MEDIUM confidence — repository says "work in progress" with family-account workaround)

---

## Executive Summary

Three feature classes shape this project:

1. **What Fasten OnPrem provides OOTB** — FHIR-resource browsing, manual record entry, PDF/FHIR Bundle upload, encounter wizard, dashboard cards. **Single-user by default, multi-user is "work in progress"**, family scenarios solved by separate user accounts (verdict for M4 SaaS pivot: **per-tenant Fasten Docker instance + Traefik routing** — native Multi-User mode is NOT production-ready).
2. **What custom Next.js analytics layer must add** — cross-source correlation (Oura sleep × Apple HRV × lab cortisol on one timeline), tagging/notes, custom dashboards, search across all sources, encryption-at-rest hooks, multi-tenant `tenant_id`+RLS schema.
3. **What is the EU/SK differentiator** — Fasten US OAuth/Smart-on-FHIR catalog (~7,000 providers) is **inapplicable in EU**. EU citizens cannot programmatically pull data from eZdravie SK / ELGA AT / Gematik DE. Manual import (PDF OCR + structured extract) is the **only viable v1**, and pre-built lab templates for Slovak/Czech/German labs is the **defensible moat**.

EHDS regulation entered force March 2025; full citizen Health Data Access Service via MyHealth@EU portal scheduled for **March 2029**. Until then, manual export PDFs from doctor portals → OCR → FHIR Observation is the only realistic path.

---

## Feature Landscape

### Table Stakes (Users Expect These — Missing = Product Feels Broken)

| # | Feature | Why Expected | Complexity | M | OOTB / Custom | Notes |
|---|---------|--------------|------------|---|---------------|-------|
| T1 | **Single dashboard with all sources** | "All my health data in one place" is the core PHR promise | M | M1 | OOTB Fasten + Custom shell | Fasten dashboard shows meds/tests/allergies/encounters; custom layer adds cross-source views |
| T2 | **FHIR Bundle import (manual upload)** | Standard portability — patients export FHIR from US providers, expect to upload elsewhere | S | M1 | OOTB Fasten | v1.0.0 supports manual FHIR Bundle upload, RTF binary, PDF documents |
| T3 | **Manual record entry (encounters, observations)** | Patients without FHIR-export providers (most EU patients) need to type things in | M | M1 | OOTB Fasten | v1.0.0 has Manual Record Wizard with search-existing-records to avoid re-entry |
| T4 | **PDF document attachment per encounter** | Lab PDFs, imaging reports, discharge summaries — patients scan/save | S | M1 | OOTB Fasten | RTF + PDF binary support since v1.0.0 |
| T5 | **Apple Health import** | iOS users assume this works; XML export is the only reliable PHR ingest path | L | M1 | Custom ETL | Apple Health export.xml is huge (30-200MB), requires parser → FHIR Observation mapping. Use existing OSS converters (FHIR Converter for CDA, custom XML→FHIR for `<Record>` elements) |
| T6 | **Wearable daily sync (at least one device)** | Quantified-self users expect daily sleep/HRV/steps without manual export | M | M1 | Custom ETL | Oura API in M1, OAuth + cron daily fetch; expand to Withings/Garmin in M2 |
| T7 | **Search across all records** | "When did I last have hemoglobin checked?" — without search, aggregator is useless | M | M1 | Mostly OOTB Fasten | Fasten has explore page (with known issues per v1.0.0 release notes), reinforce with custom layer |
| T8 | **Time-series visualization (one observation over time)** | Lab values over years, weight, HR trends — table of numbers is not enough | M | M1 | Custom (Fasten weak here) | Fasten has FHIR cards/datatables but limited charts; Next.js + Recharts/Visx layer adds proper trends |
| T9 | **User authentication + session** | Even single-user mode needs login; PHR data is PII Tier 1 | S | M1 | OOTB Fasten | Fasten has built-in auth (single user); custom layer reuses session or has its own (M4 SSO consolidation) |
| T10 | **Backup + restore** | Self-hosted product without backup = users lose data, never come back | M | M1 | Custom (Fasten weak) | Fasten = SQLite file → backup is `cp` of file; encrypted with age/gpg before off-site upload. Custom analytics Postgres = `pg_dump` + age |
| T11 | **Encryption-at-rest** | Health data PII Tier 1; users expect "self-hosted" to mean "encrypted" | M | M1 | Custom infra | Docker volume on LUKS-mounted partition (Linux) or encrypted volume (Win/Mac) |
| T12 | **HTTPS / TLS** | Even on LAN, browsers/cookies need it; CF Tunnel will require it | S | M1 | OOTB Traefik | Traefik with self-signed (M1 LAN) or CF cert (M2+) |
| T13 | **Encounter / Provider / Practitioner records** | Standard FHIR concept, patients track "which doctor when for what" | S | M1 | OOTB Fasten | v1.0.0 added Encounter display model + Practitioner/Organization integration |
| T14 | **Conditions list (diagnoses)** | "What chronic conditions am I tracking?" — patient summary content | S | M1 | OOTB Fasten | FHIR Condition resource supported |
| T15 | **Medications list (current + historical)** | Patients on chronic meds need this for travel/emergencies | S | M1 | OOTB Fasten | FHIR MedicationRequest/Statement — Fasten v1.0.0 has medical history |
| T16 | **Immunizations / vaccinations record** | EHDS Patient Summary mandatory item; travel/school/work need | S | M1 | OOTB Fasten | FHIR Immunization resource |
| T17 | **Allergies list** | Critical safety info — patients expect this front-and-center | S | M1 | OOTB Fasten | FHIR AllergyIntolerance resource |
| T18 | **Lab results (Observation, structured)** | The most common health data; expected to be viewable + plottable | M | M1 | Custom + OOTB | Fasten shows raw FHIR Observation; custom layer adds LOINC-coded grouping + trends |

**Verdict on table stakes:** Fasten v1.0.0 covers 12/18 OOTB. Gaps the custom layer must fill: T5 (Apple Health ETL), T6 (Oura sync), T8 (proper time-series viz), T10 (backup tooling), T11 (encryption-at-rest). T7 (search) is half-OOTB but flagged unstable in Fasten.

---

### Differentiators (EU/SK Competitive Advantage)

These are where this product wins against Fasten-as-shipped (US-centric) and against generic PHR products.

| # | Feature | Value Proposition | Complexity | M | OOTB / Custom | Notes |
|---|---------|-------------------|------------|---|---------------|-------|
| D1 | **Slovak/Czech/German lab PDF templates** | Pre-built parsers for Alpha Medical / Unilabs SK / Synlab CZ / Limbach DE / Sonic DE — each has consistent PDF format. User uploads PDF → structured extract → FHIR Observation with LOINC codes. **Fasten cannot do this; manual entry is current alternative.** | XL | M2 (M1 = generic OCR, M2 = template library) | Custom | OCR engine = MinerU or Chandra 2 (open-source 2026, structured Markdown/JSON output, table reconstruction). LOINC mapping = post-OCR step using LOINC codes table. Each new lab format = ~1-2 days work after template framework |
| D2 | **Multi-language UI (SK/CZ/DE/EN)** | Fasten is English-only; EU patients expect their language for medical UI | M | M3 | Custom | Next.js i18n via `next-intl`; medical terms tricky (SK/CZ blood test names ≠ English LOINC) |
| D3 | **Apple Health ETL (deep, not shallow)** | Beyond steps/HR — sleep stages, workout types, HRV, audio exposure, mindfulness, ECG. Most aggregators only ingest 5-10 metrics; full XML has 50+ | L | M1 (basic) → M2 (deep) | Custom | Open Wearables (open-source Jan 2026) supports Apple Health via Flutter SDK; can leverage their normalizer or build own |
| D4 | **Cross-source correlation views** | "Show me Oura HRV + Apple sleep + lab cortisol over 6 months on one chart" — Fasten shows resources in silos, no correlation. **This is the core "single dashboard" promise.** | L | M2-M3 | Custom | Time-series alignment + multi-axis charts; analytics DB joins across `tenant_id` |
| D5 | **GDPR-first (DPIA template, Art. 9 consent flow, Art. 32 measures docs)** | EU patients/clinics asking "is this GDPR-compliant?" — pre-built artifacts answer instantly. Fasten US-centric, no GDPR docs | L | M4 (SaaS prep), M1 = baseline encryption | Custom | DPIA template per EDPB 2026 guidelines (consultation closes June 9, 2026); explicit consent flow on tenant onboard; encryption-at-rest + audit logs as Art. 32 evidence |
| D6 | **Tagging + notes on records** | "This lab was post-COVID", "this scan flagged for second opinion" — Fasten doesn't have user-applied tags | M | M2 | Custom | Stored in custom analytics DB (FHIR doesn't have great native tag mechanism); references Fasten resource by `id` |
| D7 | **Manual import workflow optimized for EU patients** | Workflow: "scan PDF → drop in inbox folder → automatic categorization → human review screen → confirm". Fasten manual entry wizard is form-based (slow); this is OCR-assisted | L | M2 | Custom | Inbox watcher (file system or web upload) → OCR pipeline → suggest FHIR resource type + values → user approves |
| D8 | **Self-hostable AND SaaS-able from same codebase** | M1 single-user self-host validates feature set; M4 SaaS reuses 90%+ code. Most competitors are one or the other | XL (cumulative) | M4 | Custom + arch decisions from M1 | `tenant_id` + RLS in custom layer from day 1; per-tenant Fasten container at SaaS time; secrets via env (Vaultwarden in M1 → per-tenant secrets in M4) |
| D9 | **DICOM viewer with metadata extraction** | Patients have RTG/MR CDs/discs from radiologists; want to view + index without dedicated PACS workstation. **Use Orthanc (PACS) + OHIF (viewer) Docker stack — proven, OSS.** | L | M2 | Composed (Orthanc + OHIF) | Orthanc DICOM server + OHIF zero-footprint viewer; metadata (study date, modality, body part) extracted to custom analytics DB |
| D10 | **DNA raw upload + GWAS lookup (privacy-preserving)** | 23andMe + MyHeritage downloadable raw files + ClinVar/SNPedia/PharmGKB lookup. **GenomeInsight model: process locally, never upload to cloud** | L | M2 | Custom | 23andMe still allows raw download in 2026 (post-bankruptcy TTAM acquisition); SNPedia text dump available; GWAS Catalog open data |
| D11 | **Per-tenant encrypted Fasten + Postgres instances (SaaS)** | Strongest data isolation: each tenant has own Fasten container + own analytics schema. **Compliance differentiator vs. shared-DB SaaS.** | XL | M4 | Custom orchestration | Per-tenant Docker compose stack + Traefik routing per subdomain; resource cost = ~150MB/tenant idle; supports ~30-50 tenants on Hetzner CX22 (4GB) |
| D12 | **Local-first encrypted backup with off-site replication** | `restic` or `borgbackup` to encrypted off-site (S3, Hetzner Storage Box) with rotation; user keeps own keys | M | M2 | Custom (restic Docker container) | Already pattern-validated for personal infra; `cron` daily, weekly, monthly retention |

---

### Anti-Features (Deliberately NOT Built — With Reasoning)

These are commonly-requested or "obvious" features that this product **must explicitly refuse** for regulatory, ethical, or scope-creep reasons.

| # | Anti-Feature | Why Requested | Why Problematic | Alternative |
|---|--------------|---------------|-----------------|-------------|
| A1 | **AI/LLM diagnostic suggestions** ("Your bloodwork suggests X") | Tempting because data is right there; LLMs can pattern-match | **EU AI Act (Reg. 2024/1689) classifies medical-device AI as high-risk** → Class IIa+ MDR conformity assessment, Notified Body, post-market monitoring, GDPR Art. 22 (automated decisions). Personal time/$ way out of reach. Liability if wrong = catastrophic. | "Show me my data, you draw conclusions with your doctor." Allow user to **export to ChatGPT/Claude themselves** if they want — not built-in. |
| A2 | **Doctor messaging / telemedicine** | "Wouldn't it be cool if I could DM my doctor?" | Different product (regulated telemedicine), GDPR-special-category data flow analysis, doctor onboarding = B2B sales motion entirely. Out of personal-aggregator scope. | Patients use existing channels (eZdravie SK has doctor messaging; ELGA AT has it; Doctolib in Western Europe). Aggregator doesn't replace this. |
| A3 | **Insurance claims automation / billing** | US PHR products do this; "save money on insurance" | EU healthcare = different (statutory + supplemental), not claim-driven for most cases. Engineering-heavy, regulatory-heavy, limited value for EU patient. | Out of scope. If user wants claim processing, use insurer's app. |
| A4 | **Clinical decision support (drug interactions, dosing alerts)** | Pharmacy products do this; "warn me if my new med interacts" | **Class IIa medical device** under MDR (Rule 11). Drug DB licensing fees ($$$). Liability + audit trail required. | Show medications list, link to **publicly available** drug-info pages (DailyMed, ZOK SK) — informational only, no alerts. |
| A5 | **Real-time data streaming (Kafka, websockets)** | "Live dashboard of my biometrics" | Wearables don't push real-time anyway (Oura batches daily, Apple Health writes locally). Architecture cost massive. | Daily sync at ~6am; pull-on-demand button for "refresh now". Sufficient for any non-emergency use. |
| A6 | **Mood tracking / mental health journaling with AI insight** | Trendy; users sometimes ask | PII Tier 1+ (mental health = special category data + extreme stigma), GDPR Art. 9 + ethical landmines. AI insight = same MDR/AI Act problem as A1. | Allow free-text notes on encounters. Separate mood-tracking apps exist (Daylio, Bearable) — do not duplicate. |
| A7 | **Family member sub-accounts (single deployment, multiple people)** | "I want to track kids and spouse too" | Fasten "supports" this only by creating separate user accounts, but **its multi-user mode is "work in progress"** — file ownership leaks possible. Better to defer. | M1: separate Fasten container per family member, shared via Traefik subdomain. M4 SaaS inherits same per-tenant pattern — natural fit. |
| A8 | **Native mobile app (iOS/Android)** | "I want it on my phone" | Cost: native iOS = $$$ + Apple Developer fees + App Store review. Maintenance ongoing. **Fasten itself doesn't have one.** | Responsive PWA — Next.js installable on iOS/Android home screen. Camera access for PDF scan. Push notifications limited but acceptable. |
| A9 | **EHR-direct OAuth/Smart-on-FHIR connections (US-style)** | Fasten Connect (commercial) does this; users assume open-source version does too | **Out of scope for EU** — no SK/CZ/DE EHR has Smart-on-FHIR for citizens. Fasten OnPrem README explicitly: "not able to import data from healthcare providers directly." | Manual import + lab PDF templates (D1) are the EU equivalent. When MyHealth@EU citizen portal lands (2029), revisit. |
| A10 | **Cloud-by-default deployment** | "Just give me a hosted version" | **GDPR Art. 9 + DPIA required pre-launch.** Personal data in cloud = legal liability without proper agreements. | Self-host first (M1-M3); SaaS launch only after M4 prep (DPIA, Art. 28 processor agreement, encryption controls). |
| A11 | **Imaging AI analysis (auto-flag suspicious findings)** | "Tell me if my MRI shows something" | **Same as A1 + A4 — Class III medical device, Notified Body, MDR + AI Act maximally regulated.** | DICOM viewer (D9) for self-viewing only. "Talk to a radiologist" is the answer. |
| A12 | **Fitness/coaching recommendations** ("Run 5km today, you slept well") | Apps like Whoop and Oura do this — feature parity expectation | Mild form of clinical decision support. Liability lower than drug interactions but still tricky. Scope creep: aggregator → coach. | Show data, user decides. Maybe link to user's existing coaching app. |

---

## Multi-Tenant Fasten — Concrete Verdict

**Question:** Does Fasten OnPrem support multi-user/multi-tenant natively, or do per-tenant instances win?

**Verdict: PER-TENANT FASTEN INSTANCES** (with Traefik subdomain routing)

**Evidence:**

1. **Fasten OnPrem README (verified 2026-05-09):** "Multi-user support is described as 'a work in progress'" — the project's own self-assessment. Family-member tracking explicit guidance: "create new user accounts for each person; be careful to not connect sources for different people to the same Fasten user account."
2. **Fasten v1.0.0 release notes (Issue #349):** No multi-user features in v1.0.0 changelog. Auth model = single-user with admin role.
3. **Fasten architecture:** SQLite-only DB (Postgres support broken upstream per project decisions doc 2026-05). SQLite + multi-tenant = poor fit for shared instance (no row-level security, locking issues with multiple writers).
4. **Self-hosted full-root caveat from docs:** "the person running the service will have full root access to all user records" — meaning Fasten's auth model is not designed for SaaS-tenant isolation.

**Recommended pattern for M4 SaaS pivot:**

```
Hetzner CX22 (or larger)
├── Traefik (1 instance, hostname-based routing)
│   ├── tenant1.health.ardan.sk → fasten-tenant1:8080 + analytics-tenant1
│   ├── tenant2.health.ardan.sk → fasten-tenant2:8080 + analytics-tenant2
│   └── ...
├── Per-tenant Fasten container (~150MB idle, isolated SQLite volume)
├── Per-tenant analytics schema in shared Postgres OR per-tenant Postgres
├── Per-tenant encrypted volume (LUKS / age-encrypted)
└── Custom orchestration layer (Next.js admin) — provisions new tenants, manages secrets
```

**Resource estimate:** ~30-50 tenants per Hetzner CX22 (4GB RAM) at idle; 5-10 active concurrent. Scale by adding nodes; per-tenant database isolation = stronger compliance story than shared-DB-with-RLS.

**Cost estimate:** 5€/mo CX22 supports ~30 tenants → 0.17€/tenant infra cost. Pricing ceiling = whatever differentiator pricing supports.

**Confidence: HIGH** that per-tenant pattern is correct for M4. **MEDIUM** that 30-50 tenants/CX22 is right number — depends on actual usage; would benchmark in M4 dev.

---

## EU/SK Healthcare Data Sources — 2026 Reality Check

**Top-line finding:** No automated programmatic access for citizens until **2029** (MyHealth@EU full citizen portal per EHDS). Until then, **manual export PDF → OCR → FHIR Observation is the only path.**

| Source | 2026 Status | Citizen Access Method | Format | Realistic for v1 |
|--------|-------------|------------------------|--------|------------------|
| **eZdravie SK (NCZI)** | Operational since 2018, citizen portal ezdravotnictvo.sk active. New national project 2026 to "open the system through API interface" — long timeline. | eID (občiansky preukaz s čipom) + BOK PIN → web portal, view-only | Web view; **PDF download not confirmed in research** | View-only manual transcription → unrealistic for v1; **flag for follow-up research** in M2 ETL phase |
| **MyHealth@EU (cross-border)** | EHDS regulation in force March 2025; **full citizen Health Data Access Service = March 2029** target. eHDSI cross-border services exist for ePrescription/Patient Summary in 2/3 of EU but **professional-to-professional**, not citizen access | None for citizen self-export in 2026 | FHIR (HL7 Europe Lab Report v9.1.0 published 2026-02; Austrian Patient Summary R4 published 2026-02) | **Not realistic until 2029** — defer to M5+ if SaaS still going |
| **ELGA (Austria)** | Operational nationwide; FHIR-based Austrian Patient Summary R4 v1.0.0 published 2026-02 | Citizen portal "Gesundheit.gv.at" with mobile signature | **PDF download confirmed** for ELGA documents (medical reports, lab results) | Manual PDF export → OCR → FHIR mapping = workable v1 path |
| **Gematik / E-Rezept (Germany)** | E-Rezept (ePrescription) live for all statutory insurance patients 2024+; Patient Summary integrating into MyHealth@EU 2025-2026 | "Gesundheits-ID" (eGK) + smartphone app | App view + PDF; **TI-Messenger** for prof exchange | PDF export from gematik App possible; OCR pipeline applicable |
| **Czech eRecept / IZIP** | Operational; citizen portal "Občanský zdravotní servis" | Bank-iD or NIA + eID | PDF download confirmed | OCR pipeline workable |
| **Slovak labs (Alpha Medical / Unilabs SK)** | Alpha Medical = Unilabs since 2021; Synlab SK acquired by Unilabs Feb 2026 → consolidating Slovak lab market under Unilabs Online portal | sk.unilabs.online citizen account | PDF lab reports (consistent template per Unilabs) | **Best v1 target** — single template covers ~70%+ Slovak lab market post-consolidation |
| **Slovak labs (Medirex)** | Medirex Group still independent (separate from Unilabs) | Patient web portal | PDF lab reports (different template) | Second template to support |
| **Apple Health (iOS)** | Stable since 2014; FHIR-based Records since iOS 11 (US patients) | Manual export.xml from Health app on iPhone | XML (Apple proprietary schema) + CDA Records (US only) | **Confirmed workable v1 path** — open-source converters exist |
| **Health Connect (Android)** | Replacing Google Fit APIs in 2026; Medical Records feature (Android 16) supports Immunization in FHIR format with more types planned | Native Android SDK (not OAuth API) | FHIR (medical records) + structured wearable data | M3+ if Android user base material |
| **Oura API** | Stable v2 API; OAuth + token refresh | OAuth grant in user's Oura account | JSON (custom Oura schema) | **Confirmed workable v1** — daily cron job |
| **Garmin / Whoop / Withings / Polar / Strava** | Each has OAuth API with rate limits; some gated (Garmin requires partner approval, Whoop requires application) | OAuth per provider | JSON each (provider-specific) | **Use Open Wearables (open-source Jan 2026, MIT license) to abstract** — covers Whoop, Garmin, Oura, Apple Health, Samsung Health Connect; OR Terra API if Open Wearables incomplete (Terra = 500+ providers but $399/mo SaaS — bad fit for self-hosted) |

**Verdict for M1:** Apple Health export + Oura API + lab PDF (Unilabs SK template first) cover >80% of CEO's actual data sources. Defer eZdravie/ELGA/Gematik until manual PDF export workflow is solid (M2-M3); rebuild as automated when MyHealth@EU citizen portal lands (2029).

---

## Competitor Feature Analysis

| Feature | Fasten OnPrem (current) | OpenEMR | OpenMRS | LibreHealth | Health Connect (Google) | Open Wearables | This Project (target M3) |
|---------|------------------------|---------|---------|-------------|-------------------------|----------------|--------------------------|
| **Type** | PHR (patient-side) | EHR (clinic-side) | EHR (enterprise/clinic) | EHR (modular) | OS-level health data hub | Wearable API abstraction | PHR + EU lab focus |
| **FHIR** | R4 viewer | R4 (ONC certified) | R4 modules | R4 | R4 (Medical Records, Android 16) | Normalized JSON (FHIR-mappable) | R4 viewer + custom analytics |
| **Multi-user** | "Work in progress" | Yes (clinic staff roles) | Yes (clinic) | Yes | Per-device (Android user) | Per-OAuth user | **Per-tenant container (M4)** |
| **Self-host** | Yes (Docker) | Yes (LAMP) | Yes (Java/Tomcat) | Yes | No (OS-bundled) | Yes | Yes (Docker) |
| **Wearables** | None | None | None | None | Native | Yes (multi-provider) | Custom ETL (Oura M1, Open Wearables M2+) |
| **Lab PDF OCR** | Manual entry | None native | None native | None native | Not applicable | Not applicable | **D1: Slovak/Czech/German templates** |
| **Multi-language** | English only | Multi (community) | Multi (community) | Multi | OS-native | English (API) | **D2: SK/CZ/DE/EN UI** |
| **GDPR docs** | None | Generic | Generic | Generic | Google handles | Self-host = your problem | **D5: pre-built DPIA + Art. 9 + Art. 32** |
| **DICOM** | None | Some plugins | Some plugins | Possible | None | None | Orthanc + OHIF (M2) |
| **DNA / GWAS** | None | None | None | None | None | None | M2 (privacy-local) |
| **License** | GPL-3.0 | GPL-3.0 | MPL-2.0 + Healthcare Disclaimer | GPL-3.0 | Apache-2.0 (SDK) | MIT | TBD (likely AGPL for SaaS protection) |

**Positioning takeaway:** This product is **not competing with EHRs** (OpenEMR/OpenMRS = clinic systems, different buyer). Direct comparison set is **PHRs**: Fasten OnPrem (US-centric) + Apple Health Records (iOS-only). EU/SK gap is real and unfilled.

---

## Feature Dependencies

```
[T1 Single dashboard]
    └── requires ── [T9 Auth] + [Fasten container deployed]
                       └── requires ── [Docker compose stack]
                                          └── requires ── [T11 Encryption-at-rest infra]

[T5 Apple Health import]
    └── requires ── [Custom ETL framework]
                       └── enhances ── [T8 Time-series viz]
                                          └── enhances ── [D4 Cross-source correlation]
                                                              └── requires ── [Custom analytics DB schema with tenant_id]

[T6 Oura sync]
    └── requires ── [Vaultwarden secret access (manual M1, sidecar M2+)]
                       └── enhances ── [D4 Cross-source correlation]

[D1 Lab PDF templates]
    └── requires ── [Generic OCR pipeline (M1 baseline)]
                       └── requires ── [Docker container with Tesseract/MinerU/Chandra-2]
    └── enhances ── [T18 Lab results]

[D9 DICOM viewer]
    └── requires ── [Orthanc DICOM server container]
                       └── requires ── [Separate volume (large files)]
    └── enhances ── [T1 Dashboard] (link to scans)

[D10 DNA upload]
    └── requires ── [GWAS reference DB (SNPedia dump, ClinVar)]
                       └── conflicts with ── [Cloud-only deployment] (must process locally per privacy)

[D8 Self-host AND SaaS]
    └── requires ── [Multi-tenant schema from M1] + [Per-tenant orchestration M4]
                       └── conflicts with ── [Shared single Fasten instance for SaaS] (avoid)

[D11 Per-tenant Fasten]
    └── requires ── [Traefik subdomain routing] + [Provisioning automation]
                       └── enhances ── [D5 GDPR-first] (data isolation = compliance story)

[D5 GDPR-first]
    └── requires ── [D11 Per-tenant isolation] + [Audit logging] + [DPIA template] + [Encryption-at-rest verified]
    └── conflicts with ── [A1 AI diagnostic suggestions] (would trigger AI Act + MDR)
```

### Dependency Notes

- **D4 (correlation views) is the keystone** of the differentiator stack — depends on T5/T6/D1 ETLs landing first. Without ETLs feeding the analytics DB, correlation has nothing to correlate.
- **D11 (per-tenant Fasten) requires architectural decisions in M1** (don't bake-in single-instance assumptions in custom layer) but full implementation only in M4. The cost of preparing-from-day-one is small (~tenant_id columns + RLS hooks) per existing project decisions.
- **A1 (AI suggestions) explicitly conflicts with D5 (GDPR-first)** — adding AI = becoming a Class IIa medical device, blowing up the compliance story this product is built on. Permanent OOS.

---

## MVP Definition (M1 Launch — Single-User Self-Hosted)

### Launch With (M1)

Bare minimum to validate "all my health data, one place, mine only":

- [x] **T1 Dashboard** (OOTB Fasten) — single landing page
- [x] **T2 FHIR Bundle import** (OOTB Fasten) — for any future US-style export
- [x] **T3 Manual record entry** (OOTB Fasten) — fallback for everything else
- [x] **T4 PDF attachment per encounter** (OOTB Fasten) — lab PDFs as binary, viewable
- [ ] **T5 Apple Health import** (Custom ETL) — XML parser → FHIR Observations (covers steps, HR, sleep, HRV minimally)
- [ ] **T6 Oura daily sync** (Custom ETL) — OAuth token + daily cron
- [ ] **T7 Search** (OOTB Fasten, with known v1.0.0 issues) — accept Fasten's current state
- [ ] **T8 Time-series viz (basic)** (Custom Next.js page) — pick 5 key metrics, plot trends
- [x] **T9 Auth** (OOTB Fasten) — single-user
- [ ] **T10 Backup script** (Custom) — encrypted SQLite + Postgres dump cron
- [ ] **T11 Encryption-at-rest** (Custom infra) — Docker volume on encrypted partition
- [x] **T12 HTTPS** (Traefik) — self-signed M1, real cert M2
- [x] **T13-T17 FHIR resources display** (OOTB Fasten v1.0.0) — encounters, providers, conditions, meds, immunizations, allergies
- [x] **T18 Lab results display** (OOTB Fasten + custom enhancement layer M2)
- [ ] **D1 Lab PDF — generic OCR baseline** (Custom — single template for Unilabs SK to start) — first slice of Slovak lab support
- [ ] **D8 Multi-tenant readiness in custom layer** (Architecture decision) — `tenant_id` + RLS hooks from day 1 (cheap now, expensive later)

**Deliverable:** Working Fasten + ETL + custom analytics on PC docker desktop, CEO can import last 5 years of his own data, search and graph it.

### Add After M1 Validation (M2)

- [ ] **D1 expanded** — Medirex SK template, then 1-2 Czech/German labs based on user demand
- [ ] **D3 Apple Health deep ETL** — workouts, audio exposure, mindfulness, ECG
- [ ] **D6 Tagging + notes** — annotate records
- [ ] **D7 OCR-assisted manual import inbox workflow** — scan→drop→categorize→approve
- [ ] **D9 DICOM viewer** (Orthanc + OHIF Docker)
- [ ] **D10 DNA upload + local GWAS** (SNPedia + ClinVar)
- [ ] **D12 Encrypted off-site backup** (restic to Hetzner Storage Box)
- [ ] **CF Tunnel deployment** — `health.ardan.sk` accessible from outside LAN (still single user)

### Add for SaaS Pivot (M3-M4)

- [ ] **D2 Multi-language UI** (SK/CZ/DE/EN) — i18n in Next.js layer
- [ ] **D4 Cross-source correlation views** — fully fleshed analytics dashboards
- [ ] **D5 GDPR-first artifacts** — DPIA template (per EDPB June 2026 publication), Art. 9 explicit consent flow on tenant onboard, Art. 32 evidence pack
- [ ] **D11 Per-tenant Fasten orchestration** — provisioning automation, Traefik subdomain routing, per-tenant secrets
- [ ] **Authentik / Authelia SSO** — single login fronting per-tenant Fasten + custom layer
- [ ] **Billing prep** — Stripe integration or invoice flow (M5)
- [ ] **DPIA execution + first paying tenant** (M5)

### Future Consideration (M5+)

- [ ] **MyHealth@EU citizen portal integration** (when 2029 timeline lands)
- [ ] **Health Connect (Android) integration** if user base material
- [ ] **Mobile PWA refinement** — installable on home screen (iOS/Android)
- [ ] **Patient Summary FHIR export** (HL7 Europe Patient Summary IPS) — share with EU doctor

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | M | Priority |
|---------|------------|---------------------|---|----------|
| T1 Dashboard | HIGH | LOW (OOTB) | M1 | P1 |
| T5 Apple Health import | HIGH | MEDIUM | M1 | P1 |
| T6 Oura daily sync | HIGH | MEDIUM | M1 | P1 |
| T8 Time-series viz | HIGH | MEDIUM | M1 | P1 |
| T10 Backup | HIGH | LOW | M1 | P1 |
| T11 Encryption-at-rest | HIGH (PII Tier 1) | MEDIUM | M1 | P1 |
| D1 Lab PDF (Unilabs SK) | HIGH (immediate user value) | HIGH | M1 (1 template) → M2 (library) | P1 first slice, P2 rest |
| D8 Multi-tenant ready arch | LOW (M1) → HIGH (M4) | LOW (now) → HIGH (later) | M1 (cheap prep) | P1 (deferral cost = rebuild) |
| D3 Apple Health deep ETL | MEDIUM | MEDIUM | M2 | P2 |
| D4 Cross-source correlation | HIGH | HIGH | M2-M3 | P2 |
| D6 Tagging + notes | MEDIUM | LOW | M2 | P2 |
| D7 OCR-assisted inbox | HIGH | HIGH | M2 | P2 |
| D9 DICOM viewer | MEDIUM (CEO has scans) | MEDIUM (compose stack) | M2 | P2 |
| D10 DNA upload | LOW (one-time use) | HIGH | M2 | P3 |
| D12 Off-site backup | HIGH | LOW | M2 | P2 |
| D2 Multi-language UI | LOW (M1, single user) → HIGH (SaaS) | MEDIUM | M3 | P2 (M3) |
| D5 GDPR-first artifacts | LOW (single-user) → CRITICAL (SaaS) | HIGH | M4 | P1 (when M4 starts) |
| D11 Per-tenant Fasten | LOW (M1) → CRITICAL (SaaS) | HIGH | M4 | P1 (when M4 starts) |
| All anti-features (A1-A12) | — | — | — | DO NOT BUILD |

---

## Healthcare-Specific Edge Cases (Called Out)

These are domain-specific gotchas the roadmap and architecture must handle.

### Terminology codes

- **LOINC** for lab observations — open license, downloadable from loinc.org. Slovak labs use SK names, must map to LOINC codes (~50-100 most common tests cover 80%+). One-time mapping table in custom analytics DB.
- **SNOMED CT** for conditions/diagnoses — **license required for production use** in some countries. SK has national license? Verify before SaaS launch. Free for personal/evaluation.
- **ICD-10** for diagnoses — public; SK uses MKCh-10 (Slovak ICD-10 variant).
- **ATC** for medications — WHO-public, simple to use. Map SK drug names to ATC codes.
- **RxNorm** is US-specific — **do not use** for EU; ATC is the EU equivalent.

### FHIR conformance

- Fasten R4 is generic; HL7 Europe / Austrian Patient Summary / MyHealth@EU IGs add EU-specific profiles. Custom layer must handle base R4 (Fasten data) + optional EU profiles when importing from those sources later.
- Lab PDF OCR → FHIR Observation: must include `code.coding[].system = "http://loinc.org"` + `valueQuantity` + `referenceRange` + `effectiveDateTime`. Don't half-fill.

### GDPR implications

- **Art. 6 + Art. 9(2)(a) explicit consent** required for processing health data **for any purpose other than the user's own use** (i.e., SaaS user processing their own data is fine on Art. 9(2)(h) "medical assistance" basis or 9(2)(a) explicit consent).
- **Art. 17 right to erasure** — must support full delete on tenant offboard (per-tenant Fasten = easy: drop container + volume).
- **Art. 20 portability** — must support FHIR Bundle export of all tenant data. Fasten OOTB has limited export; custom layer must add comprehensive FHIR Bundle generator.
- **Art. 28 processor agreement** — when paying customers exist, contracts required. Template needed in M4.
- **Art. 32 technical measures** — encryption-at-rest + in-transit + access control + audit logs. Documented evidence pack for compliance reviews.
- **Art. 33-34 breach notification** — 72-hour breach notification requirement. Need monitoring + incident response runbook.
- **EDPB DPIA template** — public consultation closes June 9, 2026; final version later 2026. Plan to use the official template for M4.

### Medical device classification (avoidance)

- Showing data ≠ medical device. Storing data ≠ medical device. Visualizing data ≠ medical device.
- **Suggesting diagnoses, recommending treatments, alerting on drug interactions, AI-flagging imaging = medical device** (Class IIa+ MDR Rule 11). All in anti-features (A1, A4, A11, A12).
- **Reference range coloring** ("hemoglobin in red because below normal range") = borderline. Reference ranges from lab PDFs themselves = reproducing what the lab said = OK. AI-derived ranges = not OK.

### Data sensitivity layers

- All health data = PII Tier 1 already.
- **Mental health, HIV, addiction, genetic** = "extra-sensitive" within special category. If user imports such data, treat the same as everything else but be aware of stigma+legal-discrimination consequences if exposed.
- **DICOM imaging** = often contains PHI in headers (patient name, ID, birthdate, hospital, doctor name). Anonymization tooling may be needed for SaaS export/share. M4+ concern.

---

## Sources

**Fasten OnPrem (verified 2026-05-09):**
- [Fasten OnPrem GitHub README](https://github.com/fastenhealth/fasten-onprem) — feature surface, single-user model, "multi-user is work in progress"
- [Fasten OnPrem v1.0.0 Release Notes (Issue #349)](https://github.com/fastenhealth/fasten-onprem/issues/349) — manual record wizard, ~7000 provider portals, Encounter/Observation/Practitioner support
- [Fasten Sources Platform List](https://github.com/fastenhealth/fasten-sources/blob/main/PLATFORM_LIST.md) — US-centric provider catalog (~30k providers)
- [Medevel.com Fasten review](https://medevel.com/fasten/) — feature summary

**EU Healthcare Standards (2026):**
- [European Health Data Space (EHDS) Regulation](https://health.ec.europa.eu/ehealth-digital-health-and-care/european-health-data-space-regulation-ehds_en) — in force March 2025; full citizen portal 2029
- [MyHealth@EU](https://about.hse.ie/our-work/technology/myhealtheu/) — current eHDSI status
- [HL7 Europe Laboratory Report v9.1.0 (MyHealth@EU)](https://fhir.ehdsi.eu/laboratory/) — EU lab FHIR IG, generated 2026-02-20
- [Austrian Patient Summary R4 v1.0.0](https://fhir.hl7.at/r4-ELGA-AustrianPatientSummary-main/index.html) — 2026-02-17 FHIR IG
- [eZdravie (NCZI Slovakia)](https://www.ezdravotnictvo.sk/en/electronic-health-book) — citizen access via eID portal; PDF export not confirmed in research
- [Slovensko.digital eZdravie discussion](https://platforma.slovensko.digital/t/ezdravie/9152) — current 2026 API project status
- [GDPR for Healthcare 2026 Guide (planbe.eco)](https://planbe.eco/en/blog/gdpr-for-the-healthcare-industry/) — Art. 9 + DPIA requirements
- [EDPB DPIA template (consultation through June 9, 2026)](https://www.ropesgray.com/en/insights/alerts/2026/04/the-european-data-protection-board-releases-new-guidelines-on-the-processing-of-personal-data)

**EU Medical Device & AI Regulation:**
- [EU AI Act for Medical Devices Compliance (mdxcro.com)](https://mdxcro.com/eu-ai-act-medical-devices-samd/) — 2026-2028 timeline, Class IIa+ implications
- [MDR/IVDR + AI Act for SaMD (EUCROF)](https://eucrof.eu/25-february-2026-mdr-ivdr-and-the-ai-act-what-they-mean-for-software-as-a-medical-device/) — anti-feature regulatory rationale

**ETL / Data Sources:**
- [Open Wearables (open-source 2026)](https://openwearables.io/) — multi-provider wearable abstraction, MIT license; Garmin/Whoop/Oura/Apple/Polar/Suunto support
- [Apple Health Export XML format reference](https://www.aihealthexport.com/guides/apple-health-xml-format)
- [Slovak labs market consolidation under Unilabs (Feb 2026)](https://www.investorsinhealthcare.com/articles/category/news/slovakia-unilabs-acquires-synlabs-activities-in-slovakia/)
- [DNA raw data tools 2026 (Genetic Lifehacks)](https://www.geneticlifehacks.com/23andme-raw-data/) — 23andMe still supports raw download post-bankruptcy

**Self-Hosted DICOM:**
- [Orthanc DICOM server](https://www.orthanc-server.com/) — open-source PACS lite
- [OHIF Viewer](https://ohif.org/) — zero-footprint DICOM viewer

**OCR / Document Extraction (2026):**
- [MinerU](https://github.com/opendatalab/mineru) — VLM+OCR PDF→Markdown/JSON, MinerU Open Source License
- [Chandra 2 (Datalab, March 2026)](https://themenonlab.blog/blog/chandra-2-ocr-model-structured-document-extraction) — clinical document focus, table reconstruction

**Multi-Tenant Patterns:**
- [Multi-Tenant Docker Architecture (oneuptime.com 2026)](https://oneuptime.com/blog/post/2026-02-08-how-to-design-a-multi-tenant-docker-architecture/view) — full-stack-per-tenant pattern with Traefik routing
- [Traefik in Multi-Tenant Kubernetes](https://doc.traefik.io/traefik/security/multi-tenant-kubernetes/) — isolation patterns

**Open-Source PHR/EHR landscape:**
- [Awesome Healthcare (kakoni)](https://github.com/kakoni/awesome-healthcare) — curated list

---

*Feature research for: self-hosted personal health data aggregator with EU/SK SaaS pivot path*
*Researched: 2026-05-09*
*Author: GSD researcher (project: health, milestone: M1)*
