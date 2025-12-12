import asyncio
import random
from urllib.parse import unquote

from loguru import logger

from app.core.settings import UserSettings
from app.services.discovery import DiscoveryEngine
from app.services.rpdb import RPDBService
from app.services.scoring import ScoringService
from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService
from app.services.user_profile import UserProfileService


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

    async def _get_exclusion_sets(self, content_type: str | None = None) -> tuple[set[str], set[int]]:
        """
        Fetch library items and build strict exclusion sets for watched content.
        Also exclude items the user has added to library to avoid recommending duplicates.
        Returns (watched_imdb_ids, watched_tmdb_ids)
        """
        # Always fetch fresh library to ensure we don't recommend what was just watched
        library_data = await self.stremio_service.get_library_items()
        # Combine loved, watched, added, and removed (added/removed treated as exclude-only)
        all_items = (
            library_data.get("loved", [])
            + library_data.get("watched", [])
            + library_data.get("added", [])
            + library_data.get("removed", [])
        )

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

    async def _fetch_metadata_for_items(self, items: list[dict], media_type: str) -> list[dict]:
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

        # Create tasks for all items to fetch details (needed for IMDB ID and full meta)
        # Filter out items without ID
        valid_items = [item for item in items if item.get("id")]
        tasks = [_fetch_details(item["id"]) for item in valid_items]

        if not tasks:
            return []

        details_results = await asyncio.gather(*tasks)

        for details in details_results:
            if not details:
                continue

            # Extract IMDB ID from external_ids
            external_ids = details.get("external_ids", {})
            imdb_id = external_ids.get("imdb_id")
            # tmdb_id = details.get("id")

            # Prefer IMDB ID, fallback to TMDB ID
            if imdb_id:
                stremio_id = imdb_id
            else:  # skip content if imdb id is not available
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

            meta_data = {
                "id": stremio_id,
                "imdb_id": stremio_id,
                "type": "series" if media_type in ["tv", "series"] else "movie",
                "name": title,
                "poster": poster_url,
                "background": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
                "description": details.get("overview"),
                "releaseInfo": year,
                "imdbRating": str(details.get("vote_average", "")),
                "genres": [g.get("name") for g in details.get("genres", [])],
                # pass internal external_ids for post-filtering if needed
                "_external_ids": external_ids,
            }

            # Add runtime if available (Movie) or episode run time (TV)
            runtime = details.get("runtime")
            if not runtime and details.get("episode_run_time"):
                runtime = details.get("episode_run_time")[0]

            if runtime:
                meta_data["runtime"] = f"{runtime} min"

            final_results.append(meta_data)

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

        # 2. Fetch Metadata (gets IMDB IDs)
        meta_items = await self._fetch_metadata_for_items(recommendations, media_type)

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

        # Apply Excluded Genres
        excluded_ids = self._get_excluded_genre_ids(content_type)
        if excluded_ids:
            params["without_genres"] = "|".join(str(g) for g in excluded_ids)

        # Fetch
        recommendations = await self.tmdb_service.get_discover(content_type, **params)
        candidates = recommendations.get("results", [])

        # Strict Filtering
        watched_imdb, watched_tmdb = await self._get_exclusion_sets()
        filtered = await self._filter_candidates(candidates, watched_imdb, watched_tmdb)

        # Meta
        meta_items = await self._fetch_metadata_for_items(filtered[: limit * 2], content_type)

        final_items = []
        for item in meta_items:
            if item["id"] in watched_imdb:
                continue
            if item.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue
            item.pop("_external_ids", None)
            final_items.append(item)

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
        recommendation_response = await self.tmdb_service.get_recommendations(tmdb_id, mtype)
        recommended_items = recommendation_response.get("results", [])
        if not recommended_items:
            return []
        return recommended_items

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
        for batch in similarity_recommendations:
            similarity_candidates.extend(
                item for item in batch if not excluded_ids.intersection(item.get("genre_ids") or [])
            )

        # --- Candidate Set B: Profile-based Discovery ---
        # Extract excluded genres
        excluded_genres = list(excluded_ids)  # Convert back to list for consistency

        # Use typed profile based on content_type
        user_profile = await self.user_profile_service.build_user_profile(
            scored_objects, content_type=content_type, excluded_genres=excluded_genres
        )
        discovery_candidates = await self.discovery_engine.discover_recommendations(
            user_profile, content_type, limit=20, excluded_genres=excluded_genres
        )

        # --- Combine & Deduplicate ---
        candidate_pool = {}  # tmdb_id -> item_dict

        for item in discovery_candidates:
            candidate_pool[item["id"]] = item

        for item in similarity_candidates:
            # add score to boost similarity candidates
            item["_ranked_candidate"] = True
            candidate_pool[item["id"]] = item

        # --- Re-Ranking & Filtering ---
        ranked_candidates = []

        for tmdb_id, item in candidate_pool.items():
            # 1. Strict Filter by TMDB ID
            if tmdb_id in watched_tmdb_ids or f"tmdb:{tmdb_id}" in watched_imdb_ids:
                continue

            sim_score = self.user_profile_service.calculate_similarity(user_profile, item)
            vote_average = item.get("vote_average", 0)
            popularity = item.get("popularity", 0)

            pop_score = normalize(popularity, 0, 1000)
            vote_score = normalize(vote_average, 0, 10)

            final_score = (sim_score * 0.6) + (vote_score * 0.3) + (pop_score * 0.1)

            # Add tiny jitter to promote freshness and avoid static ordering
            jitter = random.uniform(-0.02, 0.02)  # +/-2%
            final_score = final_score * (1 + jitter)

            # Boost candidate if its from tmdb collaborative recommendations
            if item.get("_ranked_candidate"):
                final_score *= 1.25
            ranked_candidates.append((final_score, item))

        # Sort by Final Score and cache score on item for diversification
        ranked_candidates.sort(key=lambda x: x[0], reverse=True)
        for score, item in ranked_candidates:
            item["_final_score"] = score

        # Diversify with MMR to avoid shallow, repetitive picks
        def _jaccard(a: set, b: set) -> float:
            if not a and not b:
                return 0.0
            inter = len(a & b)
            union = len(a | b)
            return inter / union if union else 0.0

        def _candidate_similarity(x: dict, y: dict) -> float:
            gx = set(x.get("genre_ids") or [])
            gy = set(y.get("genre_ids") or [])
            s = _jaccard(gx, gy)
            # Mild penalty if same language to encourage variety
            lx = x.get("original_language")
            ly = y.get("original_language")
            if lx and ly and lx == ly:
                s += 0.05
            return min(s, 1.0)

        def _mmr_select(cands: list[dict], k: int, lamb: float = 0.75) -> list[dict]:
            selected: list[dict] = []
            remaining = cands[:]
            while remaining and len(selected) < k:
                if not selected:
                    best = remaining.pop(0)
                    selected.append(best)
                    continue
                best_item = None
                best_score = float("-inf")
                for cand in remaining[:50]:  # evaluate a window for speed
                    rel = cand.get("_final_score", 0.0)
                    div = 0.0
                    for s in selected:
                        div = max(div, _candidate_similarity(cand, s))
                    mmr = lamb * rel - (1 - lamb) * div
                    if mmr > best_score:
                        best_score = mmr
                        best_item = cand
                if best_item is None:
                    break
                selected.append(best_item)
                try:
                    remaining.remove(best_item)
                except ValueError:
                    pass
            return selected

        top_ranked_items = [item for _, item in ranked_candidates]
        diversified = _mmr_select(top_ranked_items, k=max_results * 2, lamb=0.75)
        # Select with buffer for final IMDB filtering after diversification
        buffer_selection = diversified

        # Fetch Full Metadata
        meta_items = await self._fetch_metadata_for_items(buffer_selection, content_type)

        # Final Strict Filter by IMDB ID
        final_items = []
        for item in meta_items:
            if item["id"] in watched_imdb_ids:
                continue
            ext_ids = item.get("_external_ids", {})
            if ext_ids.get("imdb_id") in watched_imdb_ids:
                continue

            item.pop("_external_ids", None)
            final_items.append(item)

        return final_items
