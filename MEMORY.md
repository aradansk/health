# MEMORY INDEX — Health

## User
- (link na global user_profile)

## Projects
*(zatial prazdne — pridavaj konkretne podprojekty ked vzniknu, napr. fasten-deployment, etl-apple-health, analytics-layer)*

## Infrastructure
*(zatial prazdne — Postgres, Fasten, Traefik, Vaultwarden glue keď nasadené)*

## References
*(externe systemy odkazy — Fasten github, Oura API docs, FHIR R4 spec, EU eHealth)*

## Feedback
*(CEO pravidla pre Health scope, lessons learned z deploymentov)*

## Decisions
- [GSD Init Complete](C:/Users/andre/.claude/projects/C--ANDREJ-Claude-Projects-health/memory/project_gsd_init_complete.md) — 12-phase M1 roadmap, 75 REQs, 3 hard gates (RLS test, OCR ≥80% LOINC, restore drill), Fasten=GPL-3.0+SQLite-only, M1 estimate 5-7 weeks
- BOOTSTRAP.md — handoff decisions z 2026-05-07 (preco samostatny projekt, 2-fazovy plan, stack rozhodnutia)
- [Tasks Status](C:/Users/andre/.claude/projects/C--ANDREJ-Claude-Projects-health/memory/tasks_status.md) — DONE/PENDING/PLANNED stav uloh, autoritativny zdroj
- [Work Log](C:/Users/andre/.claude/projects/C--ANDREJ-Claude-Projects-health/memory/work_log.md) — interna historia prac per den (2026-05-07 az 2026-05-10)

---

**Pravidla pre tento index:**
- Cross-projekt session NEVIDI tieto subory (file system isolation cez per-projekt cwd)
- Konkretne lekarske data (lab vysledky, DICOM, recepty, mena lekarov, diagnozy) **NIKDY** nezapisat do tychto MD suborov
- Pre citlive data pouzit external trezor (Vaultwarden / encrypted volume) alebo vlastnu DB
- Memory je pre **kategorie a stavy**, nie pre **values**
- Pri SaaS pivote (multi-tenant): tenant-specific data **NIKDY** do memory, len abstrakcie a counts
