# CLAUDE.md

Watchly — a Stremio catalog addon: a FastAPI service speaking the Stremio addon protocol (manifest + catalog endpoints) that serves personalised movie/series rows built from a user's watch history. Per-user state is keyed on an opaque token in the manifest URL; credentials are encrypted at rest in Redis. App code in `app/`.

Read the code for anything structural. This file is rules, not documentation.

## Principles

- Do not preserve backward compatibility, except where an installed Stremio client depends on the old shape. Remove obsolete paths instead of adding fallbacks.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Repeat yourself twice before extracting. A six-parameter helper with one caller is worse than the duplication. A readable 40 lines beats a clever 12.
- Mistakes are cheap. Don't armour against what can't happen — no handling for impossible inputs, no shims unless an installed client depends on the old shape.
- Prefer established libraries over reimplementing common functionality, and lean on the dependencies already here before adding one.
- Make architectural decisions for the long term. Don't accept a stopgap meant to be replaced later.

Changing what an installed client already requests — a manifest field, a catalog id, the semantics of a cached value — needs a compat shim carrying a comment naming the client that depends on it and what would make it removable.

## Working rules

- Open a feature or bug by reading the relevant files, then asking one batch of AskUserQuestion questions pinning down goals and acceptance criteria. Skip it only when the request is unambiguous and self-contained, like a rename or a one-line change. Plan non-trivial work in `*.local.md` at the repo root (git-ignored).
- Reproduce a bug before fixing it. Fix the root cause, then check the other call sites for the same bug.
- Change only what the task needs. Don't reformat or rename adjacent code. Delete dead code your change creates; mention unrelated dead code rather than removing it as a drive-by.
- **No workflow runs the tests** — `ci.yml` only builds Docker, `linter.yml` only runs pre-commit. Run them yourself: `uv run --with pytest python -m pytest tests/ -q`.
- Tests are plain `def` + `asyncio.run(...)`. There is no `conftest.py`, no pytest config and no `pytest-asyncio` — don't add `@pytest.mark.asyncio` without first adding the config. A fixture that accepts any credential proves nothing; make fakes reject what the real provider rejects.

## Write code like a human

A reviewer must not be able to tell the diff was AI-written.

- try/except only where you can act on the failure. Endpoints don't wrap service calls — `register_exception_handlers` in `app/core/errors.py` logs the cause and builds the response. Log once, at the layer that can act; never `logger.exception(...)` then `raise`.
- Comments only for a non-obvious WHY — a hidden constraint, a workaround, an invariant. No happy-path narration, no `# added for X`, no section banners.
- Inline single-use logic. Extract on the second real caller. No base class with one subclass.
- Trust the types. No `getattr`/`hasattr` on a pydantic field that declares a default; don't re-validate what a model validated. `LibraryCollection` is always truthy — use `.is_empty()`, never `if not library`.
- Validate params with types (`Literal`, `Path(pattern=…)`, `Field(ge=…)`), not `if` statements in the handler. Never validate the same thing twice.
- Don't declare a function `async` unless it awaits. Imports at module top — one real cycle exists (`recommendation.catalog_service` ↔ `warmup`); name it in a comment if you must import locally.
- Before adding a helper, grep for the concept. ID normalisation, era bucketing, ISO date parsing and TMDB feature extraction each already exist somewhere.
- No emojis, ASCII art, "Done!" prints, or marketing-style log messages.

## Conventions

### Data and caching — break these and the app serves wrong data, not just slower data

- The token is the tenant. Validate every `{token}` against `TOKEN_PATTERN` before touching Redis. Key templates live in `app/core/constants.py`, never as inline f-strings; wildcard patterns derive from the same template.
- Never `SCAN` or `delete_by_pattern` on a request path — keep a per-token index. Read a key at most once per request and pass the value on. Refresh a TTL with `GETEX`, not `GET` then `EXPIRE`. Don't persist what's a pure function of another cached value. `resolve_alias` once, at the edge.
- One source per `LibraryCollection` — never mix Stremio items with Trakt or Simkl items. On a source switch, drop library, profile, watched sets, buckets, catalogs and manifest together.
- Never cache a degraded result, and never cache a fallback under the wrong source. Return `None` and let the caller skip the write.
- The catalog cache is keyed on the slot id, not the definition. When a slot's definition changes, invalidate that slot's catalog in the same step.
- `get_user_data()` returns a shared, decrypted, process-cached dict. Treat it as read-only: deep-copy before mutating, and never hand it to `store_user_data`.
- Serialise every `get_user_data → mutate → update_user_data` with a Redis lock, and dedup across workers with `SET NX`, never an in-process set. Stremio requests every row concurrently, so these paths always race.
- Values written through `user_cache` pass through `cache_codec`; values written through `redis_service` do not. Don't mix on one key. `redis_service.get`/`set` return `None`/`False` on a connection error — in an auth path that is a 503, not a 401.
- Bump `PROFILE_SCORING_VERSION` when scoring maths or `TasteProfile` field semantics change. Adding a field is safe; changing what a number means is not.

### Secrets and logging

- Never log a raw token. Use `redact_token()` from `app/core/security.py` as a leading `[{redact_token(token)}]` — not `token[:8]`, no trailing `...`. Redis keys embed the token, and so does `request.url.path` on every authenticated route.
- Never interpolate an httpx exception into a log line — `str(HTTPStatusError)` carries the full URL, and TMDB and Simkl put the user's key in the query string. Log method, relative path and status code.
- Never log a pydantic error payload — `errors()[*].input` echoes the rejected value, which can be a password. Log `loc` and `type`. Never re-enable loguru's `diagnose=True`; it prints frame locals.
- Never put a secret in a URL path or query string. A saved secret leaving the server is the `STORED_SECRET_SENTINEL` marker, never the value.
- A new user secret is declared once in `_SECRET_SETTINGS_FIELDS`/`_SECRET_NESTED_FIELDS` and added to **both** the encrypt and decrypt paths in `token_store` — encrypted on write but not decrypted on read sends ciphertext to an external API.
- Derive the Fernet key once per process; `PBKDF2HMAC(iterations=200_000)` is ~55 ms of blocking CPU per call.
- One INFO line per catalog row per request, maximum — per-stage counts are debug. Errors a counter can summarise get counted and logged once. `logger.exception` only where the traceback is actionable; a handled fallback is a warning, and `error` means work was lost. Every silent fallback needs a line, or the only symptom is a blank shelf.
- f-strings, not loguru brace args. No `[MODULE]` banners — `LOG_FORMAT` already prints `{name}:{function}:{line}`.

### HTTP

- All outbound HTTP goes through `BaseClient` in `app/core/base_client.py` via the provider singletons. A raw `httpx.AsyncClient` silently opts out of retries, `Retry-After` handling and structured errors.
- Close a short-lived client in a `finally` — the error path is where the leak happens. Anything owning an httpx client must be closed; inside an `lru_cache`, eviction leaks sockets.
- Don't `@alru_cache` an instance method unless the instance is a process singleton: `self` is in the cache key, so a per-request instance means a 0% hit rate plus a retained reference.
- `BaseClient.get/post` is annotated `dict`, but Trakt list endpoints decode to `list`. Keep the `_safe_list` guards; don't tighten the annotation.
- Clear a stored Trakt/Simkl credential only on an explicit 401/403 or `invalid_grant` — never on a network error, a 5xx, or a lost refresh race. Single-flight the Trakt refresh per account token; Trakt rotates refresh tokens.
- Never `await` a network call inside the loop that builds an `asyncio.gather` list. Resolve ids in their own gather first.

### Recommendations

- Scoring runs before enrichment. TMDB `/discover`, `/recommendations` and `/similar` return the compact shape, so any scoring term reading `credits`, `keywords` or `production_countries` is silently zero.
- `watched_tmdb` is effectively empty for Trakt/Simkl users — exclusion must test `watched_imdb` too, before enrichment.
- Truncate to the row limit **before** `fetch_batch`; it is two TMDB round trips per candidate with no internal cap.
- Size diversity caps against the visible row length (`DEFAULT_CATALOG_LIMIT`), never the over-fetch target.
- One Bayesian prior per media type, from a single helper — never a literal at a call site. Terms combined with blend weights must both be on `[0, 1]` first, and `normalize` needs the value's realistic band.
- Never add a hard cap to an accumulating profile score — normalise by share of total mass. Write-side and read-side must agree on feature windows.
- Apply user genre exclusions once, centrally, after sources merge; TMDB `without_genres` alone leaks excluded genres back in via Simkl and `/recommendations`.
- Seed library-driven engines with `sample_items`, never a raw list slice. Use `simkl_service.get_recommendations_batch`, and filter Simkl candidates with `apply_quality_band=False`.
- Never emit two theme axes with the same `(role, axis)` pair — pass a list to `build_row_id`. Give each row its own axis, and prefer signals already computed.
- Re-raise `HTTPException` before any catch-all in the catalog path — `CreatorsService` uses a 404 to tell Stremio to hide a row. Don't wrap `calculate_final_score` in a per-item try/except; a raise there is a bug to surface.

### Frontend

- Never write a Stremio password or auth key to `localStorage`/`sessionStorage`. In-memory for the configure flow only.
- Every `window` `message` listener starts with `if (event.origin !== window.location.origin) return;`.
- Strip credentials from the URL with `history.replaceState` the moment they are read, before any `await` — not only on success.
- A saved secret arrives as the opaque `window.STORED_SECRET` marker. Round-trip it verbatim, never send it to a validation endpoint, and never let it overwrite a live credential — it identifies nobody, so submitting it as one fails identity verification.
- Untrusted or server-supplied text goes in with `textContent` or `escapeHtml()` from `ui.js`; `innerHTML` only for markup literals in the file. Don't override Jinja's `tojson`.
- Self-host front-end dependencies. No third-party script may share an origin with credential-bearing state.
- Catalog defaults live in `get_default_settings()` and reach the page via `get_default_catalogs_for_frontend()`. Never restate a default in a template or as a `|| {…}` fallback in JS.
- The configure page must not call live `/{token}/catalog` endpoints for previews; they run the full pipeline.

### Repo

- Every env var is declared in `app/core/config.py` **and** `.env.example` — `Settings` uses `extra="allow"`, so an undeclared var fails silently. Every setting has a reader; delete unused ones rather than leaving tuning comments for behaviour that no longer exists.
- `requirements.txt` is generated. After changing `pyproject.toml` deps: `uv lock`, then `uv pip compile pyproject.toml -o requirements.txt`, and commit both.
- The project is virtual (`source = { virtual = "." }`). Read the version from `app/core/version.py`, never `importlib.metadata`.
- Pin CI Python with `python-version-file: .python-version`, not a literal. Never interpolate `${{ }}` into a workflow `run:` when the value derives from commit messages or model output — pass it via `env:` and quote.
- A version bump ships with a matching `## <version>` section in `CHANGELOG.md` (move the `Unreleased` items into it). The release workflow publishes that section as the GitHub release body; without one it falls back to grouped commit subjects via `scripts/generate_release_notes.py`.
- Don't hand-format. Line length 120, black/isort/flake8 aligned and enforced by pre-commit.

## Never

- Never add a `Co-Authored-By` trailer or a "Generated with" line. Commits are authored by the human.
- Never `git add -A` or `git add .` — stage only the files for that commit with explicit paths. One fix per commit, so either can be reverted independently. Prefix with the area: `fix(library): …`, `refactor(catalogs): …`, `feat(trakt): …`.
- Never bump `app/core/version.py` or `pyproject.toml` as a drive-by. On `main` that triggers the release chain: GHCR push, tag, GitHub release.
- Never commit or push unless asked. Read-only git is always fine.
