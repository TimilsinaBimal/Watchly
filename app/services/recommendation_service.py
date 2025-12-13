import asyncio
import hashlib
from urllib.parse import unquote

from cachetools import TTLCache
from loguru import logger

from app.core.settings import UserSettings
from app.services.discovery import DiscoveryEngine
from app.services.rpdb import RPDBService
from app.services.scoring import ScoringService
from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService
from app.services.user_profile import TOP_GENRE_WHITELIST_LIMIT, UserProfileService


def normalize(value, min_v=0, max_v=10):
    """
    Normalize popularity / rating when blending.
    """
    if max_v == min_v:
        return 0
    return (value - min_v) / (max_v - min_v)


def _parse_identifier(identifier: str) -> tuple[str | None, int | None]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID."""
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: str | None = None
    tmdb_id: int | None = None

    for token in decoded.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("tt") and imdb_id is None:
            imdb_id = token
        elif token.startswith("tmdb:") and tmdb_id is None:
            try:
                tmdb_id = int(token.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
        if imdb_id and tmdb_id is not None:
            break

    return imdb_id, tmdb_id


class RecommendationService:
    """
    Service for generating recommendations based on user's Stremio library.
    Implements a Hybrid Recommendation System (Similarity + Discovery).
    """

    def __init__(
        self,
        stremio_service: StremioService | None = None,
        language: str = "en-US",
        user_settings: UserSettings | None = None,
        token: str | None = None,
    ):
        if stremio_service is None:
            raise ValueError("StremioService instance is required for personalized recommendations")
        self.tmdb_service = TMDBService(language=language)
        self.stremio_service = stremio_service
        self.scoring_service = ScoringService()
        self.user_profile_service = UserProfileService()
        self.discovery_engine = DiscoveryEngine()
        self.per_item_limit = 20
        self.user_settings = user_settings
        # Stable seed for tie-breaking and per-token caching
        self.stable_seed = token or ""
        # Short-TTL in-memory cache per process
        # key: tuple -> value: list[dict]
        if not hasattr(RecommendationService, "_cache"):
            RecommendationService._cache = TTLCache(maxsize=1000, ttl=300)
        self._cache: TTLCache = RecommendationService._cache

    def _stable_epsilon(self, tmdb_id: int) -> float:
        if not self.stable_seed:
            return 0.0
        h = hashlib.md5(f"{self.stable_seed}:{tmdb_id}".encode()).hexdigest()
        # Use last 6 hex digits for tiny epsilon
        eps = int(h[-6:], 16) % 1000
        return eps / 1_000_000.0

    @staticmethod
    def _normalize(value: float, min_v: float = 0.0, max_v: float = 10.0) -> float:
        if max_v == min_v:
            return 0.0
        return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))

    @staticmethod
    def _weighted_rating(vote_avg: float | None, vote_count: int | None, C: float = 6.8, m: int = 300) -> float:
        """
        IMDb-style weighted rating. Returns value on 0-10 scale.
        C = global mean; m = minimum votes for full weight.
        """
        try:
            R = float(vote_avg or 0.0)
            v = int(vote_count or 0)
        except Exception:
            R, v = 0.0, 0
        return ((v / (v + m)) * R) + ((m / (v + m)) * C)

    def _cache_get(self, key):
        try:
            return self._cache.get(key)
        except Exception:
            return None

    def _cache_set(self, key, value):
        try:
            self._cache[key] = value
        except Exception:
            pass

    async def _get_exclusion_sets(self, content_type: str | None = None) -> tuple[set[str], set[int]]:
        """
        Fetch library items and build strict exclusion sets for watched content.
        Excludes watched and loved items (and items user explicitly removed).
        Note: We no longer exclude 'added' items to avoid over-thinning the pool.
        Returns (watched_imdb_ids, watched_tmdb_ids)
        """
        # Always fetch fresh library to ensure we don't recommend what was just watched
        library_data = await self.stremio_service.get_library_items()
        # Combine loved, watched, added, and removed (added/removed treated as exclude-only)
        all_items = library_data.get("loved", []) + library_data.get("watched", []) + library_data.get("removed", [])

        imdb_ids = set()
        tmdb_ids = set()

        for item in all_items:
            # Optional: filter by type if provided, but safer to exclude all types to avoid cross-contamination
            # if content_type and item.get("type") != content_type: continue

            item_id = item.get("_id", "")
            imdb_id, tmdb_id = _parse_identifier(item_id)

            if imdb_id:
                imdb_ids.add(imdb_id)
            if tmdb_id:
                tmdb_ids.add(tmdb_id)

            # Also handle raw IDs if parse failed but it looks like one
            if item_id.startswith("tt"):
                imdb_ids.add(item_id)
            elif item_id.startswith("tmdb:"):
                try:
                    tmdb_ids.add(int(item_id.split(":")[1]))
                except Exception:
                    pass

        return imdb_ids, tmdb_ids

    async def _filter_candidates(
        self, candidates: list[dict], watched_imdb_ids: set[str], watched_tmdb_ids: set[int]
    ) -> list[dict]:
        """
        Filter candidates against watched sets using TMDB ID first, then IMDB ID (if available).
        """
        filtered = []
        for item in candidates:
            tmdb_id = item.get("id")
            # 1. Check TMDB ID (Fast)
            if tmdb_id and tmdb_id in watched_tmdb_ids:
                continue

            # 2. Check external IDs (if present in candidate)
            external_ids = item.get("external_ids", {})
            imdb_id = external_ids.get("imdb_id")
            if imdb_id and imdb_id in watched_imdb_ids:
                continue

            filtered.append(item)
        return filtered

    async def _fetch_metadata_for_items(
        self, items: list[dict], media_type: str, target_count: int | None = None, batch_size: int = 20
    ) -> list[dict]:
        """
        Fetch detailed metadata for items directly from TMDB API and format for Stremio.
        """
        final_results = []
        # Ensure media_type is correct
        query_media_type = "movie" if media_type == "movie" else "tv"

        sem = asyncio.Semaphore(30)

        async def _fetch_details(tmdb_id: int):
            try:
                async with sem:
                    if query_media_type == "movie":
                        return await self.tmdb_service.get_movie_details(tmdb_id)
                    else:
                        return await self.tmdb_service.get_tv_details(tmdb_id)
            except Exception as e:
                logger.warning(f"Failed to fetch details for TMDB ID {tmdb_id}: {e}")
                return None

        # Filter out items without ID and process in batches for early stop
        valid_items = [item for item in items if item.get("id")]
        if not valid_items:
            return []

        # Decide target_count if not provided
        if target_count is None:
            # Aim to collect up to 2x of typical need but not exceed total
            target_count = min(len(valid_items), 40)

        for i in range(0, len(valid_items), batch_size):
            if len(final_results) >= target_count:
                break
            chunk = valid_items[i : i + batch_size]  # noqa
            tasks = [_fetch_details(item["id"]) for item in chunk]
            details_results = await asyncio.gather(*tasks)
            for details in details_results:
                if not details:
                    continue

                # Extract IMDB ID from external_ids
                external_ids = details.get("external_ids", {})
                imdb_id = external_ids.get("imdb_id")

                # Prefer IMDB ID, fallback to TMDB ID (as stremio:tmdb:<id>) to avoid losing candidates
                if imdb_id:
                    stremio_id = imdb_id
                else:
                    tmdb_fallback = details.get("id")
                    if tmdb_fallback:
                        stremio_id = f"tmdb:{tmdb_fallback}"
                    else:
                        continue

                # Construct Stremio meta object
                title = details.get("title") or details.get("name")
                if not title:
                    continue

                # Image paths
                poster_path = details.get("poster_path")
                backdrop_path = details.get("backdrop_path")

                release_date = details.get("release_date") or details.get("first_air_date") or ""
                year = release_date[:4] if release_date else None

                if self.user_settings and self.user_settings.rpdb_key:
                    poster_url = RPDBService.get_poster_url(self.user_settings.rpdb_key, stremio_id)
                else:
                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

                genres_full = details.get("genres", []) or []
                genre_ids = [g.get("id") for g in genres_full if isinstance(g, dict) and g.get("id") is not None]

                meta_data = {
                    "id": stremio_id,
                    "imdb_id": imdb_id,
                    "type": "series" if media_type in ["tv", "series"] else "movie",
                    "name": title,
                    "poster": poster_url,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
                    "description": details.get("overview"),
                    "releaseInfo": year,
                    "imdbRating": str(details.get("vote_average", "")),
                    # Display genres (names) but keep full ids separately
                    "genres": [g.get("name") for g in genres_full],
                    # Keep fields for ranking and post-processing
                    "vote_average": details.get("vote_average"),
                    "vote_count": details.get("vote_count"),
                    "popularity": details.get("popularity"),
                    "original_language": details.get("original_language"),
                    # pass internal external_ids for post-filtering if needed
                    "_external_ids": external_ids,
                    # internal fields for suppression/rerank
                    "_tmdb_id": details.get("id"),
                    "genre_ids": genre_ids,
                }

                # Add runtime if available (Movie) or episode run time (TV)
                runtime = details.get("runtime")
                if not runtime and details.get("episode_run_time"):
                    runtime = details.get("episode_run_time")[0]

                if runtime:
                    meta_data["runtime"] = f"{runtime} min"

                # internal fields for collection and cast (movies only for collection)
                if query_media_type == "movie":
                    coll = details.get("belongs_to_collection") or {}
                    if isinstance(coll, dict):
                        meta_data["_collection_id"] = coll.get("id")

                # top 3 cast ids
                cast = details.get("credits", {}).get("cast", []) or []
                meta_data["_top_cast_ids"] = [c.get("id") for c in cast[:3] if c.get("id") is not None]

                # Attach minimal structures for similarity to use keywords/credits later
                if details.get("keywords"):
                    meta_data["keywords"] = details.get("keywords")
                if details.get("credits"):
                    meta_data["credits"] = details.get("credits")

                final_results.append(meta_data)

                if len(final_results) >= target_count:
                    break

        return final_results

    async def get_recommendations_for_item(self, item_id: str) -> list[dict]:
        """
        Get recommendations for a specific item by IMDB ID.
        STRICT FILTERING: Excludes watched items.
        """
        # Fetch Exclusion Sets first
        watched_imdb, watched_tmdb = await self._get_exclusion_sets()

        # Ensure the source item itself is excluded
        if item_id.startswith("tt"):
            watched_imdb.add(item_id)
        elif item_id.startswith("tmdb:"):
            watched_tmdb.add(int(item_id.split(":")[1]))

        # Convert IMDB ID to TMDB ID
        if item_id.startswith("tt"):
            tmdb_id, media_type = await self.tmdb_service.find_by_imdb_id(item_id)
            if not tmdb_id:
                logger.warning(f"No TMDB ID found for {item_id}")
                return []
        else:
            tmdb_id = item_id.split(":")[1]
            media_type = "movie"  # Default

        if not media_type:
            media_type = "movie"

        # Build user profile (for genre whitelist)
        try:
            library_data = await self.stremio_service.get_library_items()
            all_items = library_data.get("loved", []) + library_data.get("watched", []) + library_data.get("added", [])
            # Filter by type
            typed = [it for it in all_items if it.get("type") == ("tv" if media_type in ("tv", "series") else "movie")]
            # score and pick some recent top
            unique_items = {it["_id"]: it for it in typed}
            scored_objects = []
            sorted_history = sorted(
                unique_items.values(), key=lambda x: x.get("state", {}).get("lastWatched"), reverse=True
            )
            for it in sorted_history[:10]:
                scored_objects.append(self.scoring_service.process_item(it))
            user_profile = await self.user_profile_service.build_user_profile(
                scored_objects, content_type=("tv" if media_type in ("tv", "series") else "movie")
            )
            top_gen_pairs = user_profile.get_top_genres(limit=TOP_GENRE_WHITELIST_LIMIT)
            top_genre_whitelist: set[int] = {int(gid) for gid, _ in top_gen_pairs}
        except Exception:
            top_genre_whitelist = set()

        def _passes_top_genre(item_genre_ids: list[int] | None) -> bool:
            if not top_genre_whitelist:
                return True
            gids = set(item_genre_ids or [])
            if not gids:
                return True
            if 16 in gids and 16 not in top_genre_whitelist:
                return False
            return bool(gids & top_genre_whitelist)

        # Fetch more candidates to account for filtering
        # We want 20 final, so fetch 40
        buffer_limit = self.per_item_limit * 2
        recommendations = await self._fetch_recommendations_from_tmdb(str(tmdb_id), media_type, buffer_limit)

        if not recommendations:
            return []

        # 1. Filter by TMDB ID
        recommendations = await self._filter_candidates(recommendations, watched_imdb, watched_tmdb)

        # 1.5 Filter by Excluded Genres
        # We need to detect content_type from item_id or media_type to know which exclusion list to use.
        # media_type is already resolved above.
        excluded_ids = set(self._get_excluded_genre_ids(media_type))

        if excluded_ids:
            recommendations = [
                item for item in recommendations if not excluded_ids.intersection(item.get("genre_ids") or [])
            ]
        # Top-genre whitelist filter
        recommendations = [it for it in recommendations if _passes_top_genre(it.get("genre_ids"))]

        # 1.6 Freshness: inject trending/top-rated within whitelist to expand pool
        try:
            if len(recommendations) < buffer_limit:
                mtype = "tv" if media_type in ("tv", "series") else "movie"
                fresh_added = 0
                trending_resp = await self.tmdb_service.get_trending(mtype, time_window="week")
                trending = trending_resp.get("results", []) if trending_resp else []
                top_rated_resp = await self.tmdb_service.get_top_rated(mtype)
                top_rated = top_rated_resp.get("results", []) if top_rated_resp else []
                fresh_pool = []
                fresh_pool.extend(trending[:40])
                fresh_pool.extend(top_rated[:40])
                seen_ids = {it.get("id") for it in recommendations if it.get("id") is not None}
                for it in fresh_pool:
                    tid = it.get("id")
                    if not tid or tid in seen_ids:
                        continue
                    if tid in watched_tmdb:
                        continue
                    gids = it.get("genre_ids") or []
                    if excluded_ids and excluded_ids.intersection(set(gids)):
                        continue
                    if not _passes_top_genre(gids):
                        continue
                    # quality gate
                    va = float(it.get("vote_average") or 0.0)
                    vc = int(it.get("vote_count") or 0)
                    if vc < 300 or va < 7.0:
                        continue
                    recommendations.append(it)
                    seen_ids.add(tid)
                    fresh_added += 1
                    if len(recommendations) >= buffer_limit:
                        break
                if fresh_added:
                    logger.info(f"Item-rec freshness injection added {fresh_added} items")
        except Exception as e:
            logger.warning(f"Item-rec freshness injection failed: {e}")

        # 2. Fetch Metadata (gets IMDB IDs)
        meta_items = await self._fetch_metadata_for_items(
            recommendations, media_type, target_count=self.per_item_limit * 2
        )

        # 3. Strict Filter by IMDB ID (using metadata)
        final_items = []
        for item in meta_items:
            # check ID (stremio_id) which is usually imdb_id
            if item["id"] in watched_imdb:
                continue
            # check hidden external_ids if available
            ext_ids = item.get("_external_ids", {})
            if ext_ids.get("imdb_id") in watched_imdb:
                continue
            # Apply top-genre whitelist with enriched genre_ids
            if not _passes_top_genre(item.get("genre_ids")):
                continue

            # Clean up internal fields
            item.pop("_external_ids", None)
            final_items.append(item)

            if len(final_items) >= self.per_item_limit:
                break

        logger.info(f"Found {len(final_items)} valid recommendations for {item_id}")
        return final_items

    def _get_excluded_genre_ids(self, content_type: str) -> list[int]:
        if not self.user_settings:
            return []
        if content_type == "movie":
            return [int(g) for g in self.user_settings.excluded_movie_genres]
        elif content_type in ["series", "tv"]:
            return [int(g) for g in self.user_settings.excluded_series_genres]
        return []

    async def get_recommendations_for_theme(self, theme_id: str, content_type: str, limit: int = 20) -> list[dict]:
        """
        Parse a dynamic theme ID and fetch recommendations.
        Format: watchly.theme.g<id>[-<id>].k<id>[-<id>].ct<code].y<year>...
        """
        # Parse params from ID
        params = {}
        parts = theme_id.replace("watchly.theme.", "").split(".")

        for part in parts:
            if part.startswith("g"):
                # Genres: g878-53 -> 878,53
                genre_str = part[1:].replace("-", ",")
                params["with_genres"] = genre_str.replace(",", "|")
            elif part.startswith("k"):
                # Keywords: k123-456
                kw_str = part[1:].replace("-", "|")
                params["with_keywords"] = kw_str
            elif part.startswith("ct"):
                # Country: ctUS
                params["with_origin_country"] = part[2:]
            elif part.startswith("y"):
                # Year/Decade: y1990 -> 1990-01-01 to 1999-12-31
                try:
                    year = int(part[1:])
                    params["primary_release_date.gte"] = f"{year}-01-01"
                    params["primary_release_date.lte"] = f"{year+9}-12-31"
                except ValueError:
                    pass
            elif part == "sort-vote":
                params["sort_by"] = "vote_average.desc"
                params["vote_count.gte"] = 200

        # Default Sort
        if "sort_by" not in params:
            params["sort_by"] = "popularity.desc"

        # Apply Excluded Genres but don't conflict with explicit with_genres from theme
        excluded_ids = self._get_excluded_genre_ids(content_type)
        if excluded_ids:
            try:
                with_ids = {
                    int(g)
                    for g in (
                        params.get("with_genres", "").replace("|", ",").split(",") if params.get("with_genres") else []
                    )
                    if g
                }
            except Exception:
                with_ids = set()
            final_without = [g for g in excluded_ids if g not in with_ids]
            if final_without:
                params["without_genres"] = "|".join(str(g) for g in final_without)

        # Build user profile to derive top-genre whitelist
        try:
            library_data = await self.stremio_service.get_library_items()
            all_items = library_data.get("loved", []) + library_data.get("watched", []) + library_data.get("added", [])
            typed = [it for it in all_items if it.get("type") == content_type]
            unique_items = {it["_id"]: it for it in typed}
            scored_objects = []
            sorted_history = sorted(
                unique_items.values(), key=lambda x: x.get("state", {}).get("lastWatched"), reverse=True
            )
            for it in sorted_history[:10]:
                scored_objects.append(self.scoring_service.process_item(it))
            user_profile = await self.user_profile_service.build_user_profile(
                scored_objects, content_type=content_type
            )
            top_gen_pairs = user_profile.get_top_genres(limit=TOP_GENRE_WHITELIST_LIMIT)
            top_genre_whitelist: set[int] = {int(gid) for gid, _ in top_gen_pairs}
        except Exception:
            top_genre_whitelist = set()

        def _passes_top_genre(item_genre_ids: list[int] | None) -> bool:
            if not top_genre_whitelist:
                return True
            gids = set(item_genre_ids or [])
            if not gids:
                return True
            if 16 in gids and 16 not in top_genre_whitelist:
                return False
            return bool(gids & top_genre_whitelist)

        # Fetch (with simple multi-page fallback to increase pool)
        candidates: list[dict] = []
        try:
            first = await self.tmdb_service.get_discover(content_type, **params)
            candidates.extend(first.get("results", []))
            # If we have too few, try page 2 (and 3) to increase pool size
            if len(candidates) < limit * 2:
                second = await self.tmdb_service.get_discover(content_type, page=2, **params)
                candidates.extend(second.get("results", []))
            if len(candidates) < limit * 2:
                third = await self.tmdb_service.get_discover(content_type, page=3, **params)
                candidates.extend(third.get("results", []))
        except Exception:
            candidates = []

        # Apply top-genre whitelist on raw candidates
        if candidates:
            candidates = [it for it in candidates if _passes_top_genre(it.get("genre_ids"))]

        # Strict Filtering
        watched_imdb, watched_tmdb = await self._get_exclusion_sets()
        filtered = await self._filter_candidates(candidates, watched_imdb, watched_tmdb)

        # Freshness injection: add trending/top-rated (within whitelist) if pool thin
        try:
            if len(filtered) < limit * 2:
                mtype = "tv" if content_type in ("tv", "series") else "movie"
                trending_resp = await self.tmdb_service.get_trending(mtype, time_window="week")
                trending = trending_resp.get("results", []) if trending_resp else []
                top_rated_resp = await self.tmdb_service.get_top_rated(mtype)
                top_rated = top_rated_resp.get("results", []) if top_rated_resp else []
                fresh_pool = []
                fresh_pool.extend(trending[:40])
                fresh_pool.extend(top_rated[:40])
                existing_ids = {it.get("id") for it in filtered if it.get("id") is not None}
                fresh_added = 0
                for it in fresh_pool:
                    tid = it.get("id")
                    if not tid or tid in existing_ids:
                        continue
                    if tid in watched_tmdb:
                        continue
                    gids = it.get("genre_ids") or []
                    # Exclude by user excluded genre list
                    if excluded_ids and set(gids) & set(excluded_ids):
                        continue
                    # Apply top-genre whitelist
                    if not _passes_top_genre(gids):
                        continue
                    va = float(it.get("vote_average") or 0.0)
                    vc = int(it.get("vote_count") or 0)
                    if vc < 300 or va < 7.0:
                        continue
                    filtered.append(it)
                    existing_ids.add(tid)
                    fresh_added += 1
                    if len(filtered) >= limit * 3:
                        break
                if fresh_added:
                    logger.info(f"Theme freshness injection added {fresh_added} items")
        except Exception as e:
            logger.warning(f"Theme freshness injection failed: {e}")

        # Meta
        meta_items = await self._fetch_metadata_for_items(filtered, content_type, target_count=limit * 3)

        final_items = []
        for item in meta_items:
            if item["id"] in watched_imdb:
                continue
            if item.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue
            # Apply whitelist again on enriched metadata
            if not _passes_top_genre(item.get("genre_ids")):
                continue
            item.pop("_external_ids", None)
            final_items.append(item)

        # Enforce limit
        if len(final_items) > limit:
            final_items = final_items[:limit]

        return final_items

    async def _fetch_recommendations_from_tmdb(self, item_id: str, media_type: str, limit: int) -> list[dict]:
        """
        Fetch recommendations from TMDB for a given TMDB ID.
        """
        if isinstance(item_id, int):
            item_id = str(item_id)

        if item_id.startswith("tt"):
            tmdb_id, detected_type = await self.tmdb_service.find_by_imdb_id(item_id)
            if not tmdb_id:
                return []
            if detected_type:
                media_type = detected_type
        elif item_id.startswith("tmdb:"):
            tmdb_id = int(item_id.split(":")[1])
            # Detect media_type if unknown or invalid
            if media_type not in ("movie", "tv", "series"):
                detected_type = None
                try:
                    details = await self.tmdb_service.get_movie_details(tmdb_id)
                    if details:
                        detected_type = "movie"
                except Exception:
                    pass
                if not detected_type:
                    try:
                        details = await self.tmdb_service.get_tv_details(tmdb_id)
                        if details:
                            detected_type = "tv"
                    except Exception:
                        pass
                if detected_type:
                    media_type = detected_type
        else:
            tmdb_id = item_id

        # Normalize series alias
        mtype = "tv" if media_type in ("tv", "series") else "movie"
        # Try multiple pages to increase pool
        combined: dict[int, dict] = {}
        try:
            rec1 = await self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1)
            for it in rec1.get("results", []):
                if it.get("id") is not None:
                    combined[it["id"]] = it
            if len(combined) < limit:
                rec2 = await self.tmdb_service.get_recommendations(tmdb_id, mtype, page=2)
                for it in rec2.get("results", []):
                    if it.get("id") is not None:
                        combined[it["id"]] = it
            if len(combined) < limit:
                rec3 = await self.tmdb_service.get_recommendations(tmdb_id, mtype, page=3)
                for it in rec3.get("results", []):
                    if it.get("id") is not None:
                        combined[it["id"]] = it
        except Exception:
            pass

        # If still thin, use similar as fallback
        if len(combined) < max(20, limit // 2):
            try:
                sim1 = await self.tmdb_service.get_similar(tmdb_id, mtype, page=1)
                for it in sim1.get("results", []):
                    if it.get("id") is not None:
                        combined[it["id"]] = it
                if len(combined) < limit:
                    sim2 = await self.tmdb_service.get_similar(tmdb_id, mtype, page=2)
                    for it in sim2.get("results", []):
                        if it.get("id") is not None:
                            combined[it["id"]] = it
            except Exception:
                pass

        return list(combined.values())

    async def get_recommendations(
        self,
        content_type: str | None = None,
        source_items_limit: int = 5,
        max_results: int = 20,
    ) -> list[dict]:
        """
        Get Smart Hybrid Recommendations.
        """
        if not content_type:
            logger.warning("content_type must be specified (movie or series)")
            return []

        logger.info(f"Starting Hybrid Recommendation Pipeline for {content_type}")

        # Step 1: Fetch & Score User Library
        library_data = await self.stremio_service.get_library_items()
        all_items = library_data.get("loved", []) + library_data.get("watched", []) + library_data.get("added", [])
        logger.info(f"processing {len(all_items)} Items.")
        # Cold-start fallback remains (redundant safety)
        if not all_items:
            all_items = library_data.get("added", [])

        # Build Exclusion Sets explicitly
        watched_imdb_ids, watched_tmdb_ids = await self._get_exclusion_sets()

        # Deduplicate and Filter by Type
        unique_items = {item["_id"]: item for item in all_items if item.get("type") == content_type}
        processed_items = []
        scored_objects = []

        sorted_history = sorted(
            unique_items.values(), key=lambda x: x.get("state", {}).get("lastWatched"), reverse=True
        )
        recent_history = sorted_history[:source_items_limit]

        for item_data in recent_history:
            scored_obj = self.scoring_service.process_item(item_data)
            scored_objects.append(scored_obj)
            item_data["_interest_score"] = scored_obj.score
            processed_items.append(item_data)

        processed_items.sort(key=lambda x: x["_interest_score"], reverse=True)
        top_source_items = processed_items[:source_items_limit]

        # --- Candidate Set A: Item-based Similarity ---
        tasks_a = []
        for source in top_source_items:
            tasks_a.append(self._fetch_recommendations_from_tmdb(source.get("_id"), source.get("type"), limit=10))
        similarity_candidates = []
        similarity_recommendations = await asyncio.gather(*tasks_a, return_exceptions=True)

        excluded_ids = set(self._get_excluded_genre_ids(content_type))

        similarity_recommendations = [item for item in similarity_recommendations if not isinstance(item, Exception)]
        # Apply excluded-genre filter for similarity candidates (whitelist will be applied after profile build)
        for batch in similarity_recommendations:
            for item in batch:
                gids = item.get("genre_ids") or []
                if excluded_ids.intersection(gids):
                    continue
                similarity_candidates.append(item)

        # Quality gate for similarity candidates: keep higher-quality when we have enough
        def _qual(item: dict) -> bool:
            try:
                vc = int(item.get("vote_count") or 0)
                va = float(item.get("vote_average") or 0.0)
                wr = self._weighted_rating(va, vc)
                return (vc >= 150 and wr >= 6.0) or (vc >= 500 and wr >= 5.6)
            except Exception:
                return False

        # filtered_sim = [it for it in similarity_candidates if _qual(it)]
        # if len(filtered_sim) >= 40:
        #     similarity_candidates = filtered_sim

        # --- Candidate Set B: Profile-based Discovery ---
        # Extract excluded genres
        excluded_genres = list(excluded_ids)  # Convert back to list for consistency

        # Use typed profile based on content_type
        user_profile = await self.user_profile_service.build_user_profile(
            scored_objects, content_type=content_type, excluded_genres=excluded_genres
        )
        # Build per-user top-genre whitelist
        try:
            top_gen_pairs = user_profile.get_top_genres(limit=TOP_GENRE_WHITELIST_LIMIT)
            top_genre_whitelist: set[int] = {int(gid) for gid, _ in top_gen_pairs}
        except Exception:
            top_genre_whitelist = set()

        def _passes_top_genre(item_genre_ids: list[int] | None) -> bool:
            if not top_genre_whitelist:
                return True
            gids = set(item_genre_ids or [])
            if not gids:
                return True
            if 16 in gids and 16 not in top_genre_whitelist:
                return False
            return bool(gids & top_genre_whitelist)

        # Always include discovery, but bias to keywords/cast (avoid genre-heavy discovery)
        try:
            discovery_candidates = await self.discovery_engine.discover_recommendations(
                user_profile,
                content_type,
                limit=max_results * 3,
                excluded_genres=excluded_genres,
                use_genres=False,
                use_keywords=True,
                use_cast=True,
                use_director=True,
                use_countries=False,
                use_year=False,
            )
        except Exception as e:
            logger.warning(f"Discovery fetch failed: {e}")
            discovery_candidates = []

        # --- Combine & Deduplicate ---
        candidate_pool = {}  # tmdb_id -> item_dict

        for item in discovery_candidates:
            gids = item.get("genre_ids") or []
            if not _passes_top_genre(gids):
                continue
            candidate_pool[item["id"]] = item

        for item in similarity_candidates:
            # add score to boost similarity candidates
            item["_ranked_candidate"] = True
            candidate_pool[item["id"]] = item

        logger.info(f"Similarity candidates collected: {len(similarity_candidates)}; pool size: {len(candidate_pool)}")

        # Freshness injection: trending/highly rated items to broaden taste
        try:
            fresh_added = 0
            mtype = "tv" if content_type in ("tv", "series") else "movie"
            trending_resp = await self.tmdb_service.get_trending(mtype, time_window="week")
            trending = trending_resp.get("results", []) if trending_resp else []
            # Optionally mix in top-rated first page
            top_rated_resp = await self.tmdb_service.get_top_rated(mtype)
            top_rated = top_rated_resp.get("results", []) if top_rated_resp else []
            fresh_pool = []
            fresh_pool.extend(trending[:40])
            fresh_pool.extend(top_rated[:40])
            # Filter by excluded genres and quality threshold
            for it in fresh_pool:
                tid = it.get("id")
                if not tid or tid in candidate_pool:
                    continue
                # Exclude already watched by TMDB id
                if tid in watched_tmdb_ids:
                    continue
                # Excluded genres
                gids = it.get("genre_ids") or []
                if excluded_ids and excluded_ids.intersection(set(gids)):
                    continue
                # Respect top-genre whitelist
                if not _passes_top_genre(gids):
                    continue
                # Quality: prefer strong audience signal
                va = float(it.get("vote_average") or 0.0)
                vc = int(it.get("vote_count") or 0)
                if vc < 300 or va < 7.0:
                    continue
                # Mark as freshness candidate
                it["_fresh_boost"] = True
                candidate_pool[tid] = it
                fresh_added += 1
                if fresh_added >= max_results:
                    break
            if fresh_added:
                logger.info(f"Freshness injection added {fresh_added} trending/top-rated candidates")
        except Exception as e:
            logger.warning(f"Freshness injection failed: {e}")

        # --- Re-Ranking & Filtering ---
        ranked_candidates = []

        for tmdb_id, item in candidate_pool.items():
            # 1. Strict Filter by TMDB ID
            if tmdb_id in watched_tmdb_ids or f"tmdb:{tmdb_id}" in watched_imdb_ids:
                continue

            # Use simple overlap similarity (Jaccard on tokens/genres/keywords)
            try:
                sim_score, sim_breakdown = self.user_profile_service.calculate_simple_overlap_with_breakdown(
                    user_profile, item
                )
            except Exception:
                sim_score = 0.0
                sim_breakdown = {}
            # attach breakdown to item for later inspection
            item["_sim_breakdown"] = sim_breakdown

            # If we only matched on genres (topics/keywords near zero), slightly penalize
            try:
                non_gen_relevance = float(sim_breakdown.get("topics_jaccard", 0.0)) + float(
                    sim_breakdown.get("keywords_jaccard", 0.0)
                )
                if non_gen_relevance <= 0.0001:
                    sim_score *= 0.8
                    item["_sim_penalty"] = True
                    item["_sim_penalty_reason"] = "genre_only_match"
            except Exception:
                pass
            vote_avg = item.get("vote_average", 0.0)
            vote_count = item.get("vote_count", 0)
            popularity = float(item.get("popularity", 0.0))

            # Weighted rating then normalize to 0-1
            wr = self._weighted_rating(vote_avg, vote_count)
            vote_score = self._normalize(wr, 0.0, 10.0)
            pop_score = self._normalize(popularity, 0.0, 1000.0)

            # Increase weight on quality to avoid low-rated picks
            final_score = (sim_score * 0.55) + (vote_score * 0.35) + (pop_score * 0.10)
            # Stable tiny epsilon to break ties deterministically
            final_score += self._stable_epsilon(tmdb_id)

            # Quality-aware multiplicative adjustments
            q_mult = 1.0
            if vote_count < 50:
                q_mult *= 0.6
            elif vote_count < 150:
                q_mult *= 0.85
            if wr < 5.5:
                q_mult *= 0.5
            elif wr < 6.0:
                q_mult *= 0.7
            elif wr >= 7.0 and vote_count >= 500:
                q_mult *= 1.10

            # Boost candidate if from TMDB collaborative recommendations, but only if quality is decent
            if item.get("_ranked_candidate"):
                if wr >= 6.5 and vote_count >= 200:
                    q_mult *= 1.25
                elif wr >= 6.0 and vote_count >= 100:
                    q_mult *= 1.10
                # else no boost

            # Mild boost for freshness-injected trending/top-rated picks to keep feed fresh
            if item.get("_fresh_boost") and wr >= 7.0 and vote_count >= 300:
                q_mult *= 1.10

            final_score *= q_mult
            ranked_candidates.append((final_score, item))

        # Sort by Final Score and cache score on item for diversification
        ranked_candidates.sort(key=lambda x: x[0], reverse=True)
        for score, item in ranked_candidates:
            item["_final_score"] = score

        # Lightweight logging: show top 5 ranked candidates with similarity breakdown
        try:
            top_n = ranked_candidates[:5]
            if top_n:
                logger.info("Top similarity-ranked candidates (pre-meta):")
                for sc, it in top_n:
                    name = it.get("title") or it.get("name") or it.get("original_title") or it.get("id")
                    bd = it.get("_sim_breakdown") or {}
                    logger.info(f"- {name} (tmdb:{it.get('id')}): score={sc:.4f} breakdown={bd}")
        except Exception:
            pass

        # Simplified selection: take top-ranked items directly (no MMR diversification)
        top_ranked_items = [item for _, item in ranked_candidates]
        # Buffer selection size is 2x requested results to allow final filtering
        buffer_selection = top_ranked_items[: max_results * 2]

        # Fetch Full Metadata
        meta_items = await self._fetch_metadata_for_items(buffer_selection, content_type, target_count=max_results * 2)

        # Recompute similarity with enriched metadata (keywords, credits)
        final_items = []
        used_collections: set[int] = set()
        used_cast: set[int] = set()
        for item in meta_items:
            if item["id"] in watched_imdb_ids:
                continue
            ext_ids = item.get("_external_ids", {})
            if ext_ids.get("imdb_id") in watched_imdb_ids:
                continue
            # Apply top-genre whitelist again using enriched genre_ids if present
            if not _passes_top_genre(item.get("genre_ids")):
                continue

            try:
                sim_score, sim_breakdown = self.user_profile_service.calculate_simple_overlap_with_breakdown(
                    user_profile, item
                )
            except Exception:
                sim_score = 0.0
                sim_breakdown = {}
            item["_sim_breakdown"] = sim_breakdown
            wr = self._weighted_rating(item.get("vote_average"), item.get("vote_count"))
            vote_score = self._normalize(wr, 0.0, 10.0)
            pop_score = self._normalize(float(item.get("popularity") or 0.0), 0.0, 1000.0)

            base = (sim_score * 0.55) + (vote_score * 0.35) + (pop_score * 0.10)
            base += self._stable_epsilon(item.get("_tmdb_id") or 0)

            # Quality-aware adjustment
            vc = int(item.get("vote_count") or 0)
            q_mult = 1.0
            if vc < 50:
                q_mult *= 0.6
            elif vc < 150:
                q_mult *= 0.85
            if wr < 5.5:
                q_mult *= 0.5
            elif wr < 6.0:
                q_mult *= 0.7
            elif wr >= 7.0 and vc >= 500:
                q_mult *= 1.10

            score = base * q_mult

            # Collection/cast suppression
            penalty = 0.0
            coll_id = item.get("_collection_id")
            if isinstance(coll_id, int) and coll_id in used_collections:
                penalty += 0.05
            cast_ids = set(item.get("_top_cast_ids", []) or [])
            overlap = len(cast_ids & used_cast)
            if overlap:
                penalty += min(0.03 * overlap, 0.09)
            score *= 1.0 - penalty
            item["_adjusted_score"] = score
            final_items.append(item)

        # Sort by adjusted score descending
        final_items.sort(key=lambda x: x.get("_adjusted_score", 0.0), reverse=True)

        # Update used sets for next requests (implicit) and cleanup internal fields
        ordered = []
        for it in final_items:
            coll = it.pop("_collection_id", None)
            if isinstance(coll, int):
                used_collections.add(coll)
            for cid in it.pop("_top_cast_ids", []) or []:
                try:
                    used_cast.add(int(cid))
                except Exception:
                    pass
            it.pop("_external_ids", None)
            it.pop("_tmdb_id", None)
            it.pop("_adjusted_score", None)
            ordered.append(it)

        # Enforce max_results limit
        if len(ordered) > max_results:
            ordered = ordered[:max_results]

        return ordered
