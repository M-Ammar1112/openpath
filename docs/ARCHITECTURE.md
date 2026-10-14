# OpenPath — Architecture

> Scholarships, Universities & Career Opportunity Intelligence Platform.
> Local-first, single-user (auth-ready), configurable across fields.

Records requirements analysis and architecture decisions (AD-1 … AD-12).
Implementation roadmap: [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

---

## 1. Requirements Analysis (summary)

### 1.1 Functional

| # | Requirement | Architectural impact |
|---|-------------|----------------------|
| R1 | 12+ opportunity categories | `OpportunityType` enum + data-driven taxonomy, not hard-coded UI |
| R2 | Rich schema (40+ fields, provenance) | Normalized relational model; raw payload snapshot kept |
| R3 | Configurable profile (seeded with ECE/RTL interests) | Single-row profile + taxonomy tables, fully editable via API/UI |
| R4 | Explainable 0–100 relevance score + reasons | `ranking/` deterministic strategy, `ScoreReason` list persisted |
| R5 | Connectors: API/RSS/HTML/sitemap/manual behind one interface | `SourceConnector` ABC + registry + YAML source definitions |
| R6 | Lawful collection: robots.txt, ToS, rate limits, UA, cache, provenance | Central `HttpClient` (cache + rate limit + robots gate); `SourceFetch` audit table |
| R7 | Normalization keeping original + normalized values | `normalize/` module; `raw_payload` per record |
| R8 | Dedup preserving provenance | Dedup service: canonical URL key + similarity; `OpportunitySourceLink` join table |
| R9 | Freshness lifecycle (discovered/updated/verified/expired/stale) | `freshness_status` + `last_verified_at`; archive, never delete |
| R10 | Powerful search/filter/sort | Query service → SQLAlchemy; indexes on hot columns |
| R11 | Application tracker, no stored credentials | `Application` table; explicit "no secrets" rule (SECURITY.md) |
| R12 | Watchlists/alerts, pluggable notifiers | `Watchlist` + `Notification` tables; `Notifier` interface (dashboard first) |
| R13 | Analytics | Aggregation queries in `services/analytics.py` |
| R14 | Generic across fields | Taxonomy YAML (synonyms/skills/fields) + profile-driven scoring |

### 1.2 Non-functional

- **Local-first**: `./scripts/setup.sh && ./scripts/dev.sh` on one machine, SQLite.
- **Deployment-ready**: Docker Compose; `DATABASE_URL` switchable to PostgreSQL.
- **Boring technology**: no Celery/Redis/cloud lock-in; APScheduler in-process.
- **Lawful collection**: public APIs/feeds/robots-allowed pages only; no bypassing controls.
- **Explainability**: every score ships with human-readable reasons.

---

## 2. Technology Decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | Python 3.12+ (works on 3.14), FastAPI, Pydantic v2 | Spec preference; async HTTP; validation |
| ORM/migrations | SQLAlchemy 2.0 (typed ORM) + Alembic | Postgres-portable, industry standard |
| DB | SQLite (WAL) initially | Zero-setup local-first; URL-swappable |
| HTTP | httpx, BeautifulSoup/lxml, feedparser | Testable transports; fixtures for tests |
| Scheduler | APScheduler `AsyncIOScheduler` in FastAPI lifespan | Lightweight, no broker (AD-5) |
| Frontend | **React 18 + TypeScript (strict) + Vite + Ant Design 5 + TanStack Query + React Router + Recharts** | See AD-1/AD-4 |
| C++ | **Not used initially** (reserved `cpp/` slot) | Spec forbids gratuitous C++ (AD-8) |
| Scripts | Bash (+ documented manual steps for non-Linux) | Spec preference |
| Quality | ruff, mypy, pytest; ESLint, tsc, Vitest | Spec requirement |

---

## 3. System Architecture

```
              +-------------------------------+
              |   Frontend (React SPA :5173)  |
              |  pages - filters - charts     |
              +--------------+----------------+
                             | REST/JSON  /api/v1
              +--------------v----------------+
              |       FastAPI (:8000)         |
              |  api/        routers (HTTP)   |
              |  services/   domain logic     |
              |  ranking/    scoring          |
              |  jobs/       APScheduler      |
              +-------------------------------+
              | connectors/  SourceConnector  |
              |   fetch -> parse -> normalize |
              |  core/http   cache, robots,   |
              |              rate-limit       |
              +-------------------------------+
              |  persistence/  SQLAlchemy     |
              |  SQLite  -- or --  PostgreSQL |
              +-------------------------------+
```

Layering rule: `api -> services -> (connectors | ranking | persistence)`.
`connectors` and `ranking` never import from `api`. No circular imports;
`core/` holds only configuration, logging, and shared primitives.

---

## 4. Data Model (entities)

- **Profile** — single row: fields, skills, degrees, GPA, experience, countries
  (preferred/excluded), funding preference, max tuition, desired salary,
  keywords (preferred/excluded), nationality, languages, IELTS/TOEFL/GRE,
  graduation year, relocation/remote prefs.
- **TaxonomyTerm** — kind (`field` | `skill` | `synonym`), term, group,
  normalized token; seedable from YAML.
- **Source** — key, name, category (`scholarship_db` | `university` |
  `academic_jobs` | `research` | `industry_jobs` | `internships` | `manual`),
  connector type, endpoint URL, enabled flag, fetch interval, rate limit,
  robots policy, license/ToS notes.
- **SourceFetch** — run audit: status, http status, counts, error, duration.
- **Opportunity** — core record: title, organization, country, city, type,
  field, degree level, funding type (normalized + raw), tuition, stipend,
  salary, deadline, opens_at, eligibility/requirements (GPA, IELTS, TOEFL,
  GRE, experience, citizenship, age), research area, skills, tags,
  description, official URL, canonical URL, source name, discovered_at,
  last_verified_at, freshness_status (`discovered|updated|verified|expired|
  stale|archived`), relevance_score, score_reasons (JSON), confidence_score,
  is_saved, is_archived, notes, raw_payload.
- **OpportunitySourceLink** — opportunity ↔ source occurrences (provenance
  survives dedup merges).
- **Application** — opportunity_id, status (`discovered|interested|saved|
  preparing|applied|interview|offer|rejected|accepted|ignored`), applied_at,
  follow_up_at, documents_required, contact professor/email, notes.
- **Watchlist** — name, JSON filter, enabled, last_checked_at.
- **Notification** — watchlist_id, opportunity_id, message, read flag.

Dedup strategy: (1) exact canonical-URL match, (2) normalized
(org + title) key, (3) token-set similarity ≥ 0.9 with same country.
Merges attach the new source occurrence to the surviving row and update
`last_verified_at`.

---

## 5. Source Connector Design

```python
class SourceConnector(ABC):
    key: str
    async def fetch(self, ctx: FetchContext) -> list[FetchedRecord]: ...
    def parse(self, raw: RawPayload) -> list[ParsedItem]: ...
    def normalize(self, item: ParsedItem) -> NormalizedOpportunity: ...
    def validate(self, cand: NormalizedOpportunity) -> list[str]: ...  # errors
```

- Connector types: `rss`, `json_api`, `html`, `sitemap`, `manual_import`.
- Registry maps connector type → class; new sources are added by writing a
  connector + a `Source` row (or YAML seed) — central code unchanged.
- All network access goes through `core/http.HttpClient`:
  identification UA, per-host rate limit, response cache, robots.txt gate,
  timeout, payload size cap, provenance capture.
- Pipeline service (`services/ingest.py`): fetch → parse → normalize →
  validate → dedup → upsert → per-source audit row. One connector failure
  is caught and logged; refresh continues with remaining sources.

Initial sources (evaluated in `docs/SOURCES.md`): arXiv cs.AR/eess.SP JSON
API (research/RA), EU Academia academic-jobs JSON API, higherdegreejobs.edu
JSON listing (funded programs), Careers semiconductor RSS (industry jobs),
plus a fixture-backed manual import for scholarships until an official
scholarship feed is verified.

---

## 6. Ranking Architecture

- Deterministic weighted model, 0–100, fully explainable:

| Signal | Weight |
|--------|--------|
| Keyword/skill/research similarity (synonym-expanded token overlap) | 35 |
| Field similarity | 15 |
| Degree/eligibility feasibility | 15 |
| Funding preference fit | 10 |
| Location preference | 10 |
| Deadline availability / recency | 10 |
| Constraints (citizenship, language, tuition, salary) | up to −15 penalty |

- Every signal appends a `ScoreReason(text, signal, points)`; top reasons are
  stored on the opportunity and shown as "WHY IT MATCHES".
- Hard ineligibility (closed deadline, excluded country) caps the score and
  is stated explicitly.
- `RankingStrategy` protocol allows an optional future semantic
  (embedding/LLM) strategy behind the same interface — no paid API required
  for the default path.
- Scoring runs after each ingest and whenever the profile changes.

---

## 7. Background Jobs

- APScheduler `AsyncIOScheduler` started in the FastAPI lifespan.
- Jobs: `refresh_sources` (per-source interval), `score_opportunities`
  (after refresh / profile change), `freshness_sweep` (mark expired/stale),
  `watchlist_check` (emit notifications), `cache_cleanup`.
- Failures are isolated: each job logs structured events; the refresh job
  isolates per-connector errors so one bad source cannot kill the run.
- Rationale vs Celery/Redis: local-first, single process, no broker (AD-5).

---

## 8. Frontend Architecture

- Vite SPA; React Router pages: Dashboard, Discover, Scholarships,
  Universities, Research, Jobs, Saved, Applications, Watchlists, Sources,
  Profile, Settings.
- TanStack Query for server state; no global store beyond lightweight context.
- Ant Design 5 component system (Table with filters/sort, detail Drawer/page,
  Statistic cards, Form for profile), Recharts for analytics.
- Detail view: MATCH SCORE → WHY IT MATCHES → DEADLINE → FUNDING/SALARY →
  ELIGIBILITY → REQUIREMENTS → SOURCE → **OPEN OFFICIAL PAGE** button
  (external link labelled with destination domain, `rel="noopener noreferrer"`).
- Vite dev proxy `/api → :8000`; production build served by FastAPI
  StaticFiles.

---

## 9. Testing Strategy

- **Backend (pytest)**: unit tests for normalize, ranking, dedup, freshness;
  parser tests using stored HTML/JSON fixtures (no live network — httpx
  MockTransport); API tests via `TestClient`; DB tests on temp SQLite with
  migrated schema.
- **Frontend (Vitest + React Testing Library)**: query/filter builders, key
  components (OpportunityTable, MatchScoreBadge), API client typing.
- **Smoke**: `scripts/smoke.sh` starts backend, runs one fixture ingest,
  asserts the API returns the record.
- One command for everything: `./scripts/test.sh` → lint + typecheck + tests.

---

## 10. Security Considerations

- All input validated by Pydantic; ORM parameterization (no SQL strings).
- External descriptions rendered as plain text (React escaping) — never
  `dangerouslySetInnerHTML`; URL validation (http/https only) for official
  links.
- Secrets only via environment (`.env` gitignored, `.env.example` committed).
- Rate limits, timeouts, size caps on fetched payloads; fetched content is
  never executed (no headless browser needed for initial sources).
- Dependency lock files for pip and npm; `pip check` / `npm audit` documented.
- No authentication initially (localhost single-user), but the API is
  versioned (`/api/v1`) and a middleware slot exists for adding auth before
  public deployment (see `docs/SECURITY.md`).

---

## 11. Deployment Strategy

- Local: `scripts/dev.sh` runs API (reload) + Vite concurrently.
- Docker: `docker/backend.Dockerfile`, `docker/frontend.Dockerfile`
  (multi-stage), `docker-compose.yml` with volumes for SQLite/data and env
  injection. Portable to any VPS/home server/cloud VM — no proprietary
  services.
- Postgres path: set `DATABASE_URL=postgresql+psycopg://…`, run
  `alembic upgrade head`.

---

## 12. Repository Layout

```
openpath/
├── backend/app/
│   ├── main.py              # FastAPI app, lifespan (scheduler), static mount
│   ├── config.py            # pydantic-settings, .env
│   ├── logging_config.py    # structured JSON logging
│   ├── api/                 # routers: health, opportunities, profile,
│   │   │                    #   applications, watchlists, sources, analytics
│   │   └── deps.py
│   ├── services/            # ingest, query, dedup, freshness, scoring,
│   │                        #   analytics, watchlists, seed
│   ├── connectors/          # base, registry, rss, json_api, html, manual
│   ├── normalize/           # taxonomy, text, funding, degree, dates
│   ├── ranking/             # strategy, lexical, reasons, scoring pipeline
│   ├── core/                # http client, robots, rate limit, cache, urls
│   ├── persistence/         # db.py, models.py, repositories/
│   ├── jobs/                # scheduler + job definitions
│   ├── schemas/             # Pydantic request/response models
│   └── taxonomy/            # seed YAML: fields, skills, synonyms
├── alembic/                 # migrations
├── frontend/                # Vite React TS app
├── cpp/                     # reserved (unused — see AD-8)
├── scripts/                 # setup.sh dev.sh test.sh lint.sh db.sh smoke.sh
├── tests/                   # fixtures/ + unit/api/parser tests
├── docs/                    # ARCHITECTURE DATA_MODEL SOURCES DEVELOPMENT
│                            #   DEPLOYMENT SECURITY IMPLEMENTATION_PLAN
├── config/                  # source definitions YAML
├── data/                    # runtime sqlite + cache (gitignored)
├── docker/                  # Dockerfiles + compose
└── README.md
```

---

## 13. Architecture Decisions (AD log)

- **AD-1 — React+Vite SPA over Next.js.** The app is a local, API-centric
  single-user tool; SSR adds complexity with no benefit offline. Simpler
  build/dev story.
- **AD-2 — SQLite first, Postgres-ready.** Single-user local-first; SQLAlchemy
  + Alembic keep the Postgres migration to a URL change.
- **AD-3 — Monolith FastAPI with strict internal layering** (api/services/
  connectors) over microservices: one process to run, boundaries still allow
  later extraction.
- **AD-4 — Ant Design component system.** Mature, dense, data-heavy UI;
  avoids building a custom design system (over-engineering risk).
- **AD-5 — APScheduler in-process** instead of Celery/Redis: job volume is
  low (minutes-level intervals, one user); a broker would double ops burden.
- **AD-6 — Deterministic lexical ranking first**, behind a `RankingStrategy`
  interface so embeddings/LLM matching can be added without paid APIs and
  without touching callers.
- **AD-7 — Central HTTP client with robots.txt, rate limits, cache, UA** to
  make lawful collection the default; connectors cannot bypass it.
- **AD-8 — No C++ initially.** Spec forbids adding it to satisfy the language
  requirement; `cpp/` is reserved for future high-performance matching with a
  pybind11 boundary if profiling justifies it.
- **AD-9 — Archive, never delete** historical opportunities; freshness is a
  status, not a delete operation.
- **AD-10 — Provenance as a join table**, so dedup merges never lose source
  occurrences.
- **AD-11 — Taxonomy as YAML seed data**, making the platform field-agnostic:
  another user swaps taxonomy + profile, not the code.
- **AD-12 — Fixture-first collector tests**: parsers are tested against
  stored payloads; live network never gates CI.