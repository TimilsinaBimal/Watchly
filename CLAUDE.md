# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Watchly is a Stremio catalog addon that generates personalized movie/series recommendations from a user's watch history. It is a FastAPI service that speaks the Stremio addon protocol (manifest + catalog endpoints). Recommendations come from a taste profile built off the user's history, then candidates are pulled from TMDB / Simkl, scored, capped for diversity, enriched, and returned as a Stremio catalog.

A user installs Watchly through its `/configure` web page: they paste a Stremio email/password (or auth_key), optionally connect Trakt and/or Simkl via OAuth, optionally provide their own TMDB / Gemini / Simkl / RPDB API keys, pick which catalogs they want, and get an addon manifest URL to paste into Stremio. From then on, every catalog row in their Stremio home — "Top Picks for You", "Because you loved …", "Genre & Keyword Catalogs", etc. — is served by this app. State per user is keyed on a short opaque token embedded in the manifest URL; credentials are encrypted at rest in Redis. The app must work for users who store their library in Stremio, in Trakt, or in Simkl, and for users with mixed signals (rated, watched, loved, rewatched). That source flexibility is the central architectural constraint.

## Commands

Dependencies are managed with [uv](https://github.com/astral-sh/uv); a `requirements.txt` is also kept in sync for non-uv environments. Python 3.12+.

```bash
# Install
uv sync

# Run dev server (auto-reload when APP_ENV=development)
uv run main.py --dev
# or directly
uvicorn app.core.app:app --reload

# Tests (pytest is not in requirements-dev.txt — install once into the venv)
pip install pytest pytest-asyncio
pytest tests/                                       # all tests
pytest tests/test_catalog_endpoint.py -v            # single file
pytest tests/test_catalog_endpoint.py::test_name    # single test

# Lint / format (also runs on commit via pre-commit)
pre-commit run --all-files
black .            # line length 120, py312
isort .            # black profile
flake8 .           # max-line-length 120, config in setup.cfg

# Docker
docker-compose up -d            # uses env_file .env
```

The configure UI is served at `/configure`. Required env vars: `TMDB_API_KEY`, `TOKEN_SALT`, `HOST_NAME`. Redis is required (`REDIS_URL`).

## Architecture

### Request flow

Every catalog request resolves through one path:

1. **`app/services/context.py:load_user_context`** is the entry point for every authenticated endpoint. It reads the encrypted token from Redis, decrypts credentials, parses `UserSettings`, resolves a Stremio `auth_key`, and builds the `LibraryCollection`. The library is sourced from `user_settings.watch_history_source` — `"stremio"`, `"trakt"`, or `"simkl"`. For external sources the WatchHistory is converted to a `LibraryCollection` (rating ≥ 9 → loved, 7–8.9 → liked, no-rating + rewatch → loved fallback, else watched) so downstream catalog code is source-agnostic. The `LibraryCollection.source` field drives cache invalidation when a user switches sources.
2. **`app/services/recommendation/catalog_service.py`** routes the catalog ID to one of the recommendation engines:
   - `watchly.rec` → `TopPicksService` (combines profile-driven Discover + library-seeded TMDB/Simkl recs)
   - `watchly.theme.*` → `ThemeBasedService` (genre/keyword/era driven)
   - `watchly.item.*` → `ItemBasedService` (seeded by a single library item — see "watchly.item" below)
   - `watchly.creators` → `CreatorsService` (directors/cast)
   - `watchly.all.loved`, `watchly.liked.all` → `AllBasedService`
3. The engine returns a list of items that are passed through metadata enrichment (`app/services/recommendation/metadata.py`), poster ratings overlay (`app/services/poster_ratings/`), translation, and serialization.

### Taste profile pipeline (`app/services/profile/`)

The `TasteProfile` is a numerical fingerprint of the user — top genres, keywords, directors, cast, eras, countries, runtime preference. It is built from the same source as the library: `ProfileService.build_and_cache_profile` checks the configured `watch_history_source` and feeds `WatchHistoryItem`s through the same vectorizer pipeline regardless of origin. Profiles are cached in Redis per-token-per-content-type and invalidated when the source field doesn't match. `_build_from_external_source` reuses the already-built `LibraryCollection` when its `source` matches the configured source, avoiding a duplicate Trakt/Simkl fetch.

### External API clients

All HTTP calls go through **`app/core/base_client.py:BaseClient`**, which provides retries (with jitter on 429/5xx), timeouts, structured error logging, and safe JSON parsing. `TraktService`, `SimklService`, and `TMDBService` are singletons that wrap `BaseClient`. The token-refresh + 401-revoke flow for Trakt/Simkl lives in `ProfileService.fetch_external_watch_history` and is shared between context loading and profile building.

### Caching (`app/services/user_cache.py`, `app/services/redis_service.py`)

Redis is the source of truth for user state. Per-token cached: encrypted credentials (`token_store`), library collection, taste profile (per content type), watched-id sets, library hash for incremental rebuilds. Many caches are TTL-bound (90d default for user data) and refresh on read so active users stay warm. **Invalidate library + profile on source switch**, not just on settings change — `load_user_context` and `build_and_cache_profile` both check the cached `source` field.

### Catalog config IDs

User catalog config IDs (in `UserSettings.catalogs`) and the IDs Stremio actually requests are different. Configs use the bare ID (`watchly.theme`, `watchly.item`); served catalogs append the seed (`watchly.theme.action`, `watchly.item.tt0468569`). `get_config_id` in `app/services/catalog_definitions.py` strips the suffix to look up settings.

**Legacy IDs**: the previously separate `watchly.loved` and `watchly.watched` were merged into a single `watchly.item` catalog. Routing in `catalog_service.py` and `get_config_id` still accept `watchly.loved.*` / `watchly.watched.*` prefixes because installed Stremio clients keep requesting them until the manifest refreshes; `_resolve_catalog_configs` synthesizes a `watchly.item` config from any legacy entries left in saved settings.

### Settings + catalog defaults

`app/core/settings.py:get_default_settings()` is the single source of truth for the default catalog list and shape. Frontend pulls these via `get_default_catalogs_for_frontend()` so the configure page and backend can't drift. When adding a new catalog: add the `CatalogConfig` to defaults, add a description to `CATALOG_DESCRIPTIONS`, register routing in `app/services/recommendation/catalog_service.py`, and emit it from `DynamicCatalogService.get_dynamic_catalogs` in `app/services/catalog_definitions.py`.

### Background work

`app/services/catalog_updater.py` runs on a schedule (`AUTO_UPDATE_CATALOGS=true` + `CATALOG_REFRESH_INTERVAL`) to refresh dynamic catalogs ahead of user requests. Background tasks created via `asyncio.create_task` must be retained (see `app/services/catalog_updater.py:125`) — bare creates are GC-eligible and silently swallow errors.

## Coding mindset

Your job here is almost always to change code, so this bar applies every turn — not only when asked.

- **Think before coding.** State your assumptions. If the request has more than one reasonable reading, say so and ask rather than guessing. For non-trivial work, write the simplest plan in a line or two, then build that.
- **Simplicity, then readability.** The right amount of code is the least that solves the task — no abstraction for single-use code, no configurability nobody asked for, no handling for inputs that can't occur. But fewer lines is not the goal; clarity is. A readable 40 lines beats a clever 12. The codebase aims for code that reads like prose: small functions, intention-revealing names, as little ceremony as possible. Code that is denser, more abstract, or more defensive than the files around it is a regression.
- **DRY / YAGNI / KISS, with judgment.** Repeat yourself two or three times before extracting — a six-parameter helper with one caller is worse than the duplication. Refactor when a function grows past ~40 lines or two responsibilities. Don't build for needs that don't exist yet. (In-repo examples: `_build_from_external_source` was split out of `build_and_cache_profile` only once dispatch logic appeared; `fetch_external_watch_history` was extracted once two call sites needed the same Trakt/Simkl flow.)
- **Mistakes are cheap, not catastrophic.** You don't need armor against every conceivable failure — humans don't write that. Lean on types, tests, and review; keep diffs small and reversible. Don't add error handling for cases that can't happen, don't validate input that's already typed, don't add backwards-compat shims unless an installed Stremio client depends on the old shape (manifest/catalog IDs are the main case — see legacy catalog ID handling). Defensive bloat is a worse outcome than the occasional honest bug.
- **Surgical.** Change only what the task needs. Don't reformat, rename, or refactor adjacent code; match surrounding style. Delete dead code your own change creates rather than leaving it `# unused`; but if you spot pre-existing unrelated dead code, mention it — don't delete it as a drive-by.
- **Verify.** For a bug fix, reproduce it first (a failing test for anything non-trivial), fix the root cause not the symptom, and check whether the same bug exists at other call sites. Caches are part of the contract: when you change the shape of something cached (`LibraryCollection`, `TasteProfile`, watched sets), think through invalidation or version the key — adding a field is safe (Pydantic defaults unknowns), changing semantics is not.

## Write code like a human

A reviewer should not be able to tell the diff was AI-written. Avoid the tells:

- **Follow the repo's idioms.** PEP 8 spacing/naming, type hints on every public function and dataclass field, `pydantic` for anything crossing an API boundary, `loguru` for logging (never import `logging`), `httpx` only through `app/core/base_client.py:BaseClient`, `async` end-to-end for I/O. No threads, no synchronous blocking calls inside async handlers.
- **Error handling where you can act on it.** Add a `try/except` only when you can translate the failure, fall back, or roll back — otherwise let it propagate. The endpoint layer turns errors into responses (log the detail, return a generic message — see `catalogs.py`); `BaseClient` owns retry/timeout. Don't scatter defensive catches through services and helpers.
- **Comments and docstrings: only when the WHY is non-obvious.** A name and signature should explain WHAT. Add a comment for a hidden constraint, a workaround, or a subtle invariant ("Trakt list endpoints decode to a `list` despite the dict type hint"; "drop the cached library on source switch or stale results are served"). Don't narrate happy-path code, don't write what-it-does docstrings, no `# added for X` rot, no section banners.
- **Trust the types.** No `hasattr`/None-guards on values the types prove, no re-validating what a Pydantic model already validated, no calling the same fetch twice to avoid a local.
- **Centralize, don't repeat.** TMDB / Trakt / Simkl calls go through their service classes, never raw `httpx`. Catalog defaults live in `get_default_settings`, not duplicated in templates. ID-prefix knowledge belongs in `get_config_id` and `_get_recommendations` routing, not scattered across modules.
- **No decorative output.** No emojis, ASCII art, "Done!" prints, or marketing-style log messages.
- **Line length 120** everywhere (black, isort, flake8 aligned in `setup.cfg` and `pyproject.toml`, enforced by pre-commit — don't hand-format or restate their rules).

## Commit conventions

- **Never add a `Co-Authored-By` trailer.** Commits are authored by the human, not by the assistant. No `🤖 Generated with` lines either.
- **Stage only the files relevant to the commit** — `git add <paths>`, never `git add -A`/`git add .`. Unrelated working-tree changes (e.g. local `.gitignore` tweaks, scratch files) stay unstaged.
- **One fix per commit.** If a session produces two logically separate fixes, ship two commits so either can be reverted independently. Prefix with the area in the existing repo style: `fix(library): …`, `refactor(catalogs): …`, `feat(trakt): …`, `chore(profile): …`.

## Domain conventions

- **One source, one library**: never mix Stremio library items with Trakt/Simkl items in the same `LibraryCollection`. The whole collection is tagged with a single `source`.
- **Item exclusion uses both ID kinds**: `watched_imdb` (set of `tt…`) and `watched_tmdb` (set of TMDB ints). External sources only populate `watched_imdb` reliably; don't assume `watched_tmdb` is populated for Trakt/Simkl users.
- **`BaseClient.get/post` returns `dict` typed**, but JSON list responses (Trakt) decode to `list`. Defensive `_safe_list` guards in service layers handle this — preserve the pattern rather than tightening the type.
