# OpenPath — Implementation Plan

Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md). Phased roadmap with exit
criteria; every phase ends with passing tests.

## Phase 2 — Project Foundation
- [ ] Repo layout, `.gitignore`, `.env.example`, dependency manifests
      (`pyproject.toml`, `frontend/package.json`)
- [ ] `backend/app/config.py` (pydantic-settings), structured logging
- [ ] SQLAlchemy models + Alembic initial migration; `db.py` engine/session
- [ ] FastAPI app with `/api/v1/health`, error handlers, CORS, static mount
- [ ] Vite React TS skeleton with router, layout, Ant Design, dev proxy
- [ ] Scripts: `setup.sh`, `dev.sh`, `lint.sh`, `test.sh`, `db.sh`
- [ ] README quickstart; first pytest + frontend test pass
**Exit:** `./scripts/setup.sh && ./scripts/dev.sh` boots both apps;
`./scripts/test.sh` green.

## Phase 3 — First Complete Vertical Slice
- [ ] `core/http.py`: UA, timeout, rate limit, cache, robots gate
- [ ] `SourceConnector` ABC + registry + `services/ingest.py` pipeline
- [ ] First connector: arXiv API (JSON) → parse → normalize → validate
- [ ] Dedup + upsert with provenance (`OpportunitySourceLink`)
- [ ] Taxonomy seed (fields/skills/synonyms YAML) + default profile seed
- [ ] Deterministic ranking with persisted `score_reasons`
- [ ] API: `GET /opportunities` (list/filter/sort), `GET /opportunities/{id}`
- [ ] Frontend: Discover page (table + detail drawer + match score + reasons)
- [ ] Fixture-driven parser tests
**Exit:** run refresh once → record visible in UI with score and reasons.

## Phase 4 — Core Platform
- [ ] Profile API + Profile page (all fields editable)
- [ ] Full filter/sort surface (funding, country, deadline, score, source…)
- [ ] Favorites (`is_saved`) + Saved page; freshness sweep job (expired/stale)
- [ ] Application tracker API + page (states, notes, follow-up)
- [ ] Watchlists + notifications (dashboard channel) + page
- [ ] Sources management page (list, enable/disable, trigger refresh, history)
- [ ] Analytics endpoints + Dashboard page (charts)
- [ ] APScheduler wiring in lifespan with all jobs
**Exit:** all listed pages functional; jobs run.

## Phase 5 — Additional Sources (one at a time, each with fixtures + tests)
- [ ] EU Academia academic-jobs JSON API (`academic_jobs`)
- [ ] HigherDegreeJobs.edu JSON listing (`funded programs / universities`)
- [ ] Careers.com semiconductor RSS (`industry_jobs`)
- [ ] Manual-import connector for scholarship databases lacking permitted feeds
**Exit:** each source ingests, dedups, and appears in the UI; failures isolated.

## Phase 6 — Quality
- [ ] `pytest` full suite green (unit, parser, API, DB, dedup, ranking)
- [ ] `ruff check` + `ruff format --check` + `mypy` green
- [ ] Frontend: `tsc --noEmit`, ESLint, Vitest green, `vite build` succeeds
- [ ] `pip check`, `npm audit` reviewed
- [ ] Smoke script proves end-to-end ingest → API
**Exit:** `./scripts/test.sh` green end-to-end.

## Phase 7 — Review & Ship
- [ ] Repository-wide review: duplication, giant modules, dead code, hidden
      coupling, missing validation/tests, unsafe parsing, perf, stale docs
- [ ] Refactor only where justified
- [ ] Docs pass: README, DEVELOPMENT, DEPLOYMENT, SECURITY, DATA_MODEL,
      SOURCES current
- [ ] Docker files verified (`docker compose build`)
- [ ] Git history logical; push to `main`

---

## Initial Source Strategy (detail)

| Source | Category | Mechanism | Why chosen |
|--------|----------|-----------|------------|
| arXiv API (`export.arxiv.org`, cs.AR/eess.SP/eess.SY) | research / RA leads | public JSON/XML API, documented, ToS-permissive with rate limits | official API, structured, stable |
| EU Academia (academia.eu) job listings | academic jobs | public JSON API endpoint | structured API, no scraping needed |
| HigherDegreeJobs.edu | funded MSc/PhD listings | public JSON listing endpoint | structured feed of funded programs |
| Careers (careers.com) RSS | industry/semiconductor jobs | RSS feed | standard feed format |
| Scholarship DB (e.g. OpportunitiesCorner / scholarship portals) | scholarships | manual-import connector + fixtures until a permitted feed/API is verified | avoids ToS-unsafe scraping |

Evaluation criteria used: official API/feed availability, structured data,
automation permission (ToS/robots), stability, relevance to the profile.
See `docs/SOURCES.md` for the full evaluation and lawful-collection notes.

## Testing Strategy (summary)
- Parser tests run only on `tests/fixtures/**` payloads (no network).
- Ranking/dedup/normalization are pure-function unit tests with fixed seeds.
- API tests spin the FastAPI app on a temp SQLite DB via dependency override.
- Frontend tests cover filter/query building and key components.
- `scripts/test.sh` is the single entry point (lint + typecheck + tests).

## Blocking Questions / Assumptions
None blocking. Documented assumptions:
1. Single-user localhost now; auth middleware slot reserved (AD-3).
2. Scholarship sources without verified permitted feeds ship as a
   manual-import connector first (spec explicitly allows this).
3. C++ deferred until profiling justifies it (AD-8); `cpp/` reserved.
4. Notifications render in-dashboard initially; `Notifier` interface keeps
   email/Telegram pluggable later.