# Watchly

<div align="center">

<!-- Premium Badge Collection -->
[![Version](https://img.shields.io/github/v/release/timilsinabimal/watchly?style=for-the-badge&logo=semver&color=6366f1)](https://github.com/timilsinabimal/watchly/releases)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/timilsinabimal/watchly?style=for-the-badge&color=f59e0b&logo=github)](https://github.com/timilsinabimal/watchly/stargazers)

</div>
<br/>

**Watchly** is a Stremio catalog addon that fills your Stremio home with personalized movie and series recommendations built from your own watch history. It reads what you've watched, rated, and loved — from **Stremio, Trakt, or Simkl** — builds a numerical taste profile from it, and serves a set of recommendation rows ("Top Picks for You", "Because you watched …", genre and keyword catalogs, and more) using metadata from [TMDB](https://www.themoviedb.org/).

Everything is configured through a web page; you paste the resulting manifest URL into Stremio once, and the catalogs keep refreshing in the background.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Catalogs](#catalogs)
- [Watch history sources](#watch-history-sources)
- [Personalization](#personalization)
- [Screenshots](#screenshots)
- [Installation (Docker)](#installation-docker)
- [Configuration reference](#configuration-reference)
- [Optional integrations](#optional-integrations)
- [Development](#development)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Funding & support](#funding--support)
- [Acknowledgements](#acknowledgements)

## Features

- **Personalized recommendations** — a taste profile (top genres, keywords, directors, cast, eras, countries, runtime) is built from your history and drives every catalog row.
- **Three history sources** — use your **Stremio** library, your **Trakt** account, or your **Simkl** account. Ratings, watches, loves, and rewatches are all understood.
- **Multiple catalog types** — Top Picks, "Because you watched/loved", dynamic genre & keyword rows, recommendations from your recurring directors and actors, and "based on everything you loved/liked".
- **Fine-grained personalization** — discovery style (mainstream → hidden gems), release-year window, excluded genres (separately for movies and series), display language, and per-catalog enable/rename/shuffle controls.
- **Poster ratings overlay** — optionally overlay IMDb/TMDb-style ratings on posters via [RatingPosterDB](https://ratingposterdb.com/), Top Posters, or a custom template.
- **Bring your own keys** — supply your own TMDB, Simkl, or Gemini API keys, or rely on the server's.
- **Secure by design** — credentials are encrypted at rest in Redis and never appear in the manifest URL, which carries only a short opaque token.
- **Background sync** — catalogs are refreshed on a schedule so your home page is ready before you open it.
- **Fast** — aggressive Redis caching of profiles, libraries, and rendered catalogs keeps responses quick.

## How it works

1. You open the `/configure` page and connect a history source (Stremio login, or Trakt/Simkl via OAuth). Your credentials are encrypted and stored in Redis under a short opaque **token**. That token is embedded in your personal manifest URL.
2. Watchly fetches your watch history from the configured source and converts it into a source-agnostic library — ratings ≥ 9 count as *loved*, 7–8.9 as *liked*, the rest as *watched*.
3. From that library it builds a **taste profile**: a numerical fingerprint of your preferences across genres, keywords, people, eras, countries, and runtime.
4. When Stremio requests a catalog, Watchly routes the request to the matching recommendation engine, pulls candidates from TMDB (and Simkl where available), scores them against your profile, caps them for diversity, enriches them with metadata and (optionally) poster ratings, translates titles to your language, and returns a standard Stremio catalog.

Each user's state is keyed entirely on their token. You can switch history sources at any time; the library and profile are rebuilt from the new source.

## Catalogs

You choose which of these to enable on the configure page. Each can be toggled per content type (movies / series), renamed, hidden from the home page, or shuffled.

| Catalog | ID | What it shows |
| --- | --- | --- |
| **Top Picks for You** | `watchly.rec` | Your strongest personalized recommendations, combining profile-driven TMDB discovery with picks seeded from your library. |
| **Because you watched / loved** | `watchly.item` | Titles similar to one recent item. The seed is chosen at random from your 3 most-recent loved + 3 most-recent watched items; the row title becomes "Because you loved *X*" or "Because you watched *X*" accordingly. |
| **Genre & Keyword Catalogs** | `watchly.theme` | Dynamic, Netflix-style rows built from your favorite genres, keywords, and countries (e.g. "American Horror", "Based on a Novel"). Up to ~4 rows each for movies and series, varying with your history. |
| **From your favourite Creators** | `watchly.creators` | Recommendations from directors and lead actors who recur across multiple items in your library — not one-offs. |
| **Based on what you loved** | `watchly.all.loved` | Recommendations drawn from your entire set of loved items. |
| **Based on what you liked** | `watchly.liked.all` | Recommendations drawn from your entire set of liked items. |

## Watch history sources

Watchly works for users who keep their library in different places. Pick one source per install:

- **Stremio** — uses your Stremio library directly (requires a Stremio email/password or auth key).
- **Trakt** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.
- **Simkl** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.

A single install uses exactly one source at a time. Switching sources rebuilds your library and profile from the new account.

## Personalization

All of these are set on the configure page and stored with your token:

- **Discovery style** — `mainstream`, `balanced`, `gems` (highly rated, less popular), or `all`. Controls the quality/popularity band candidates must fall in.
- **Release-year range** — restrict recommendations to a year window (default 1970–present).
- **Excluded genres** — hide genres you don't want, configured separately for movies and series.
- **Display language** — catalog titles and metadata are translated to your chosen language.
- **Sorting order** — show movies first, series first, or the default interleaving.
- **Poster ratings** — overlay ratings on posters via RPDB, Top Posters, or a custom URL template.
- **Per-catalog controls** — enable/disable, movie-only or series-only, hide from home, shuffle, and rename most catalogs.

## Screenshots

<img src="./app/static/screenshots/homepage.png" alt="Top Picks" width="800"/>

Find more screenshots [here](./app/static/screenshots/).

## Installation (Docker)

Docker is the recommended way to self-host. Watchly requires a **Redis** instance and a **TMDB API key**.

1. **Create a `docker-compose.yml`:**

   ```yaml
   services:
     redis:
       image: redis:7-alpine
       container_name: watchly-redis
       restart: unless-stopped
       volumes:
         - redis_data:/data

     watchly:
       image: ghcr.io/timilsinabimal/watchly:latest
       container_name: watchly
       restart: unless-stopped
       ports:
         - "8000:8000"
       env_file:
         - .env
       depends_on:
         - redis

   volumes:
     redis_data:
   ```

2. **Create a `.env` file** (see the [configuration reference](#configuration-reference) for all options):

   ```env
   # Required
   TMDB_API_KEY=your_tmdb_api_key_here
   TOKEN_SALT=generate_a_long_random_secret
   HOST_NAME=https://your-public-addon-url

   # Redis (matches the compose service name)
   REDIS_URL=redis://redis:6379/0

   # Optional — enable Trakt / Simkl / AI naming (see "Optional integrations")
   # TRAKT_CLIENT_ID=
   # TRAKT_CLIENT_SECRET=
   # SIMKL_CLIENT_ID=
   # SIMKL_CLIENT_SECRET=
   # GEMINI_API_KEY=
   ```

   `HOST_NAME` must be the public URL where the addon is reachable. It is used to build OAuth callback URLs and the manifest URL, so it has to match what Stremio (and Trakt/Simkl) will see.

3. **Start it:**

   ```bash
   docker-compose up -d
   ```

4. **Configure and install:**
   Open `http://localhost:8000/configure` (or your `HOST_NAME`), connect a history source, pick your catalogs, and paste the generated manifest URL into Stremio.

## Configuration reference

All settings are environment variables. Only the first three are strictly required.

### Required

| Variable | Description |
| --- | --- |
| `TMDB_API_KEY` | TMDB API key used for metadata and discovery. Users may also supply their own key on the configure page. |
| `TOKEN_SALT` | Secret used to derive the encryption key for stored credentials. **Set a long random value** — the default `change-me` is insecure. |
| `HOST_NAME` | Public base URL of the addon (used for manifest and OAuth callback URLs). |

### Redis

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL. Redis is required. |
| `REDIS_MAX_CONNECTIONS` | `20` | Max Redis connections per process. |
| `REDIS_CONNECTIONS_THRESHOLD` | `100` | Background Redis-heavy jobs back off above this many total clients. |
| `REDIS_TOKEN_KEY` | `watchly:token:` | Key prefix for stored user tokens. |

### Optional integrations

| Variable | Default | Description |
| --- | --- | --- |
| `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET` | — | Trakt OAuth app credentials; enable Trakt as a history source. |
| `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET` | — | Simkl OAuth app credentials; enable Simkl as a history source. |
| `GEMINI_API_KEY` | — | Enables AI-generated, Netflix-style names for the dynamic genre/keyword rows. |
| `DEFAULT_GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Gemini model used for row naming. |

### Tuning & behavior

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port. |
| `ADDON_ID` | `com.bimal.watchly` | Stremio addon ID in the manifest. |
| `ADDON_NAME` | `Watchly` | Display name in the manifest. |
| `APP_ENV` | `production` | `development`, `production`, or `vercel`. |
| `TOKEN_TTL_SECONDS` | `0` | Token expiry in seconds; `0` = never expire. |
| `AUTO_UPDATE_CATALOGS` | `true` | Refresh dynamic catalogs in the background on a schedule. |
| `CATALOG_REFRESH_INTERVAL_SECONDS` | `86400` | Background refresh interval (24 h). |
| `CATALOG_CACHE_TTL` | `43200` | Rendered-catalog cache TTL (12 h). |
| `CATALOG_STALE_TTL` | `604800` | Soft-expiration fallback for cached catalogs (7 d). |
| `RECOMMENDATION_SOURCE_ITEMS_LIMIT` | `10` | Number of library items used to seed recommendations. |
| `LIBRARY_ITEMS_LIMIT` | `20` | Library item cap used in parts of the pipeline. |
| `ANNOUNCEMENT_HTML` | `""` | Optional HTML banner shown on the configure page. |

## Optional integrations

These are only needed if you want the corresponding feature; Watchly runs fine with just TMDB + Redis.

- **Trakt** — create an API app at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications). Set the redirect URI to `HOST_NAME/auth/trakt/callback` and put the client ID/secret in `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET`.
- **Simkl** — create an app at [simkl.com/settings/developer](https://simkl.com/settings/developer). Set the redirect URI to `HOST_NAME/auth/simkl/callback` and put the credentials in `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET`.
- **Gemini** — get a key from [Google AI Studio](https://aistudio.google.com/) and set `GEMINI_API_KEY` to enable AI-named dynamic rows. Without it, rows fall back to deterministic names.
- **Poster ratings (RPDB)** — users enter their own [RatingPosterDB](https://ratingposterdb.com/) key on the configure page; no server config required.

## Development

Dependencies are managed with [uv](https://github.com/astral-sh/uv); a `requirements.txt` is kept in sync for non-uv environments. **Python 3.12+** is required, and a running Redis is needed for most functionality.

```bash
# Clone
git clone https://github.com/TimilsinaBimal/Watchly.git
cd Watchly

# Install dependencies
uv sync

# Run the dev server (auto-reload)
uv run main.py --dev
# or
uvicorn app.core.app:app --reload
```

Create a `.env` with at least `TMDB_API_KEY`, `TOKEN_SALT`, `HOST_NAME`, and `REDIS_URL` before running. The configure UI is served at `/configure`.

### Tests, linting, formatting

```bash
# Tests (pytest is installed into the venv on demand)
PYTHONPATH=. uv run --with pytest pytest tests/
PYTHONPATH=. uv run --with pytest pytest tests/test_catalog_endpoint.py -v

# Lint / format (also enforced by pre-commit on commit)
pre-commit run --all-files
black .      # line length 120, py312
isort .      # black profile
flake8 .     # config in setup.cfg
```

## Architecture

Watchly is a FastAPI service that speaks the Stremio addon protocol. The request flow for every authenticated endpoint is:

1. **`app/services/context.py:load_user_context`** — decrypts the token, parses settings, resolves auth, and builds the `LibraryCollection` from the configured `watch_history_source`.
2. **`app/services/recommendation/catalog_service.py`** — routes the catalog ID to a recommendation engine (Top Picks, theme, item, creators, all-loved/liked).
3. The engine's results pass through metadata enrichment, poster-ratings overlay, translation, and serialization into a Stremio catalog.

The taste-profile pipeline lives in `app/services/profile/`, all external HTTP goes through `app/core/base_client.py:BaseClient` (retries, timeouts, structured errors), and Redis (`app/services/user_cache.py`, `app/services/redis_service.py`) is the source of truth for user state.

### Project layout

```
app/
  api/            # FastAPI routers: manifest, catalog, tokens, oauth, dashboard, validation, health …
  core/           # app setup, config/settings, base HTTP client, security, constants
  models/         # Pydantic models (library, profile, …)
  services/
    profile/      # taste-profile builder
    recommendation/ # catalog routing + per-type engines, scoring, diversity, filtering
    poster_ratings/ # RPDB / Top Posters / custom overlays
    stremio/      # Stremio library + auth
    tmdb/         # TMDB client, genres, countries
    …             # trakt, simkl, gemini, translation, caching, catalog updater
  static/, templates/  # the configure UI and dashboard
```

### Key endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /configure` | Web UI for setup and catalog selection. |
| `GET /{token}/manifest.json` | Per-user Stremio manifest. |
| `GET /{token}/catalog/{type}/{id}.json` | Catalog data for a content type and catalog ID. |
| `POST /tokens/` | Create a token from submitted credentials/settings. |
| `GET /auth/trakt`, `GET /auth/simkl` | OAuth start; `/callback` variants complete the flow. |
| `GET /{token}/dashboard/data` | User dashboard data. |
| `GET /health`, `GET /stats` | Readiness probe and usage stats. |

## Contributing

Contributions of all sizes are welcome!

- **Small bug fixes & improvements** — open a Pull Request directly.
- **Major features & refactors** — please [open an issue](https://github.com/TimilsinaBimal/Watchly/issues) first to discuss the approach. This keeps your work aligned with the project's direction and saves you time.

## Funding & support

If you find Watchly useful, please consider supporting the project:
- [Buy me Mo:Mo](https://buymemomo.com/timilsinabimal)

## Bug reports

Found a bug or have a feature request? Please [open an issue](https://github.com/TimilsinaBimal/Watchly/issues) on GitHub.

## Contributors

Thank you to everyone who has contributed to the project!

<a href="https://github.com/TimilsinaBimal/watchly/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=TimilsinaBimal/watchly" />
</a>

## Acknowledgements

Special thanks to **[The Movie Database (TMDB)](https://www.themoviedb.org/)** for the rich metadata that powers Watchly's recommendations, and to **Trakt** and **Simkl** for their history APIs.
