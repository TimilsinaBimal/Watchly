import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.settings import UserSettings
from app.services.discovery import DiscoveryEngine
from app.services.profile.service import UserProfileService
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.scoring import ScoringService
from app.services.stremio.service import StremioBundle as StremioService
from app.services.tmdb.service import get_tmdb_service

TOP_GENRE_WHITELIST_LIMIT = 5

PER_GENRE_MAX_SHARE = 0.4


class RecommendationEngine:
    """
    Main orchestration logic for generating hybrid recommendations.
    """

    def __init__(
        self,
        stremio_service: StremioService,
        language: str = "en-US",
        user_settings: UserSettings | None = None,
        token: str | None = None,
        library_data: dict | None = None,
        auth_key: str | None = None,
    ):
        self.tmdb_service = get_tmdb_service(language=language)
        self.stremio_service = stremio_service
        self.user_settings = user_settings
        self.stable_seed = token or ""
        self._library_data = library_data
        self.auth_key = auth_key

        self.scoring_service = ScoringService()
        self.user_profile_service = UserProfileService(language=language)
        self.discovery_engine = DiscoveryEngine(language=language)

        self.per_item_limit = 20
        self._whitelist_cache: dict[str, set[int]] = {}

    async def get_recommendations(
        self,
        content_type: str,
        source_items_limit: int = 5,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Smart Hybrid Recommendation Pipeline."""
        logger.info(f"Starting Hybrid Recommendation Pipeline for {content_type}")

        # 1. Fetch & Prep History (Use larger window for a stable profile)
        profile_history_limit = 20
        scored_objects, watched_tmdb, watched_imdb = await self._get_scored_library_items(
            content_type, limit=profile_history_limit
        )

        # 2. Candidate Generation (Discovery + Similarity)
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        candidate_pool, user_profile, whitelist = await self._collect_hybrid_candidates(
            content_type, scored_objects, set(excluded_ids), source_items_limit
        )

        # 3. Freshness Injection
        await self._inject_freshness(
            candidate_pool, content_type, watched_tmdb, set(excluded_ids), whitelist, max_results
        )

        # 4. Initial Ranking
        # Recency setup
        candidate_decades = {
            (RecommendationMetadata.extract_year(it) // 10) * 10
            for it in candidate_pool.values()
            if RecommendationMetadata.extract_year(it)
        }
        recency_fn, recency_alpha = RecommendationScoring.get_recency_multiplier_fn(user_profile, candidate_decades)

        ranked = self._rank_initial_pool(
            candidate_pool, content_type, user_profile, whitelist, watched_tmdb, recency_fn, recency_alpha
        )

        # 5. Metadata Enrichment (Top items)
        buffer = [it for _, it in ranked[: max_results * 2]]
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, buffer, content_type, max_results * 2, self.user_settings
        )

        # 6. Final Re-ranking and Diversification
        final_items = self._diversify(
            enriched, user_profile, whitelist, recency_fn, recency_alpha, watched_imdb, watched_tmdb, max_results
        )

        return final_items

    async def _get_scored_library_items(self, content_type: str, limit: int) -> tuple[list[Any], set[int], set[str]]:
        """Fetch library, compute exclusion sets, and score top history items."""
        if self._library_data is None:
            if not self.auth_key:
                raise ValueError("auth_key is required to fetch library data")
            self._library_data = await self.stremio_service.library.get_library_items(self.auth_key)

        lib = self._library_data
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            self.stremio_service, lib, self.auth_key
        )

        all_lib_items = lib.get("loved", []) + lib.get("watched", []) + lib.get("added", [])
        typed_items = {it["_id"]: it for it in all_lib_items if it.get("type") == content_type}

        sorted_history = sorted(
            typed_items.values(),
            key=lambda x: x.get("state", {}).get("lastWatched") or "",
            reverse=True,
        )

        scored_objects = []
        top_sources = []
        for it in sorted_history[:limit]:
            scored = self.scoring_service.process_item(it)
            scored_objects.append(scored)
            it["_interest_score"] = scored.score
            top_sources.append(it)

        top_sources.sort(key=lambda x: x["_interest_score"], reverse=True)
        # Store top sources in self if needed, but returning scored objects is enough for profile
        return scored_objects, watched_tmdb, watched_imdb

    async def _collect_hybrid_candidates(
        self, content_type: str, scored_objects: list, excluded_genres: set[int], max_results: int
    ) -> tuple[dict[int, dict], Any, set[int]]:
        """Run TMDB Similarity and Discovery in parallel to populate initial candidate pool."""
        # 1. Profile Building
        user_profile = await self.user_profile_service.build_user_profile(
            scored_objects, content_type=content_type, excluded_genres=list(excluded_genres)
        )

        # 2. Similarity Candidates (Candidate Set A)
        # Assuming we use top 5 scored items for similarity sources
        top_ids = [obj.item.id for obj in scored_objects[:5]]
        tasks = [self._fetch_raw_recommendations(tid, content_type, limit=10) for tid in top_ids]
        sim_batches = await asyncio.gather(*tasks, return_exceptions=True)

        sim_candidates = []
        for batch in sim_batches:
            if isinstance(batch, Exception):
                continue
            for it in batch:
                gids = it.get("genre_ids") or []
                if not excluded_genres.intersection(gids):
                    it["_ranked_candidate"] = True
                    sim_candidates.append(it)

        # 3. Discovery Candidates (Candidate Set B)
        whitelist = await self._get_genre_whitelist(content_type, scored_objects)
        discovery_candidates = await self.discovery_engine.discover_recommendations(
            user_profile,
            content_type,
            excluded_genres=list(excluded_genres),
            use_genres=False,
            use_keywords=True,
            use_cast=True,
            use_director=True,
            use_countries=False,
            use_year=False,
        )

        # 4. Merge (No hard filtering here, leave it for the ranker)
        candidate_pool = {}
        for it in discovery_candidates:
            candidate_pool[it["id"]] = it
        for it in sim_candidates:
            candidate_pool[it["id"]] = it

        return candidate_pool, user_profile, whitelist

    def _rank_initial_pool(
        self,
        pool: dict[int, dict],
        content_type: str,
        profile: Any,
        whitelist: set[int],
        watched_tmdb: set[int],
        recency_fn: Any,
        recency_alpha: float,
    ) -> list[tuple[float, dict]]:
        """Apply base ranking, similarity, and quality adjustments to the initial candidate pool."""
        ranked = []
        for tid, it in pool.items():
            if tid in watched_tmdb:
                continue

            sim_score, bd = self.user_profile_service.calculate_simple_overlap_with_breakdown(profile, it)
            if float(bd.get("topics_jaccard", 0.0)) + float(bd.get("keywords_jaccard", 0.0)) <= 0.0001:
                sim_score *= 0.8  # Penalty for genre-only match

            wr = RecommendationScoring.weighted_rating(
                it.get("vote_average"),
                it.get("vote_count"),
                C=7.2 if content_type in ("tv", "series") else 6.8,
            )
            v_score = RecommendationScoring.normalize(wr)
            p_score = RecommendationScoring.normalize(float(it.get("popularity") or 0.0), max_v=1000.0)

            final_score = (sim_score * 0.55) + (v_score * 0.35) + (p_score * 0.10)

            # Apply Genre Bias (Preference Boost/Penalty)
            final_score *= RecommendationFiltering.get_genre_multiplier(it.get("genre_ids"), whitelist)

            year = RecommendationMetadata.extract_year(it)
            final_score *= (1.0 - recency_alpha) + (recency_alpha * recency_fn(year))
            final_score += RecommendationScoring.stable_epsilon(tid, self.stable_seed)

            final_score = RecommendationScoring.apply_quality_adjustments(
                final_score,
                wr,
                int(it.get("vote_count") or 0),
                bool(it.get("_ranked_candidate")),
                bool(it.get("_fresh_boost")),
            )
            ranked.append((final_score, it))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    async def get_recommendations_for_item(self, item_id: str, media_type: str = "movie") -> list[dict[str, Any]]:
        """Get recommendations for a specific item, strictly excluding watched content."""
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            self.stremio_service, self._library_data, self.auth_key
        )

        # Explicitly exclude the source item
        if item_id.startswith("tt"):
            watched_imdb.add(item_id)
        elif item_id.startswith("tmdb:"):
            try:
                watched_tmdb.add(int(item_id.split(":")[1]))
            except Exception:
                pass

        # Use the provided media_type (series/movie -> tv/movie)
        mtype = "tv" if media_type in ("tv", "series") else "movie"

        # Fetch candidates using the known type
        candidates = await self._fetch_raw_recommendations(item_id, mtype, limit=40)

        # Build whitelist
        stremio_mtype = "series" if mtype == "tv" else "movie"
        whitelist = await self._get_genre_whitelist(stremio_mtype)

        # Process candidates
        filtered = []
        for it in candidates:
            if it.get("id") in watched_tmdb:
                continue
            gids = it.get("genre_ids") or []
            if not RecommendationFiltering.passes_top_genre_whitelist(gids, whitelist):
                continue
            filtered.append(it)

        # Freshness injection for related items (threshold 40)
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, stremio_mtype)
        if len(filtered) < 40:
            tmp_pool = {it["id"]: it for it in filtered}
            await self._inject_freshness(tmp_pool, mtype, watched_tmdb, set(excluded_ids), whitelist, 20)
            filtered = list(tmp_pool.values())

        # Enrichment
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, stremio_mtype, target_count=20, user_settings=self.user_settings
        )

        # Strict final filtering
        final = []
        for it in enriched:
            if it["id"] in watched_imdb:
                continue
            if it.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue
            it.pop("_external_ids", None)
            final.append(it)
            if len(final) >= 20:
                break

        return final

    async def _fetch_raw_recommendations(self, item_id: str, media_type: str, limit: int) -> list[dict[str, Any]]:
        """Fetch raw recommendations from TMDB (multiple pages)."""
        mtype = "tv" if media_type in ("tv", "series") else "movie"
        tmdb_id = None

        if item_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(item_id)
        elif item_id.startswith("tmdb:"):
            try:
                tmdb_id = int(item_id.split(":")[1])
            except Exception:
                pass
        else:
            try:
                tmdb_id = int(item_id)
            except Exception:
                pass

        if not tmdb_id:
            return []

        combined = {}
        # fetch two pages of data
        for action in ["recommendations", "similar"]:
            method = getattr(self.tmdb_service, f"get_{action}")
            results = await asyncio.gather(*[method(tmdb_id, mtype, page=p) for p in [1, 2]], return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"Error fetching {action} for {tmdb_id}: {res}")
                    continue
                for it in res.get("results", []):
                    if it.get("id"):
                        combined[it["id"]] = it

            if len(combined) >= max(20, limit // 2):
                break

        return list(combined.values())

    async def _get_genre_whitelist(self, content_type: str, scored_objects: list | None = None) -> set[int]:
        if content_type in self._whitelist_cache:
            return self._whitelist_cache[content_type]

        try:
            if scored_objects is None:
                if self._library_data is None:
                    if not self.auth_key:
                        return set()
                    self._library_data = await self.stremio_service.library.get_library_items(self.auth_key)

                all_lib = (
                    self._library_data.get("loved", [])
                    + self._library_data.get("watched", [])
                    + self._library_data.get("added", [])
                    + self._library_data.get("liked", [])
                )
                typed = [
                    it
                    for it in all_lib
                    if it.get("type") == content_type or (content_type == "series" and it.get("type") == "tv")
                ]
                sorted_hist = sorted(
                    {it["_id"]: it for it in typed}.values(),
                    key=lambda x: x.get("state", {}).get("lastWatched") or "",
                    reverse=True,
                )
                scored_objects = [
                    self.scoring_service.process_item(it) for it in sorted_hist[: settings.LIBRARY_ITEMS_LIMIT]
                ]

            prof_type = "series" if content_type in ("tv", "series") else "movie"
            temp_profile = await self.user_profile_service.build_user_profile(scored_objects, content_type=prof_type)
            top_pairs = temp_profile.get_top_genres(limit=TOP_GENRE_WHITELIST_LIMIT)
            whitelist = {int(gid) for gid, _ in top_pairs}
        except Exception as e:
            logger.warning(f"Failed to build whitelist for {content_type}: {e}")
            whitelist = set()

        self._whitelist_cache[content_type] = whitelist
        return whitelist

    async def _inject_freshness(
        self, pool: dict, media_type: str, watched_tmdb: set, excluded_ids: set, whitelist: set, max_results: int
    ):
        mtype = "tv" if media_type in ("tv", "series") else "movie"
        try:
            trending = (await self.tmdb_service.get_trending(mtype)).get("results", [])
            top_rated = (await self.tmdb_service.get_top_rated(mtype)).get("results", [])
            fresh_pool = trending[:40] + top_rated[:40]

            cap = max(1, int(max_results * PER_GENRE_MAX_SHARE))
            genre_counts = defaultdict(int)
            fresh_added = 0

            for it in fresh_pool:
                tid = it.get("id")
                if not tid or tid in pool or tid in watched_tmdb:
                    continue
                gids = it.get("genre_ids") or []
                if excluded_ids.intersection(gids):
                    continue
                if not RecommendationFiltering.passes_top_genre_whitelist(gids, whitelist):
                    continue

                wr = RecommendationScoring.weighted_rating(it.get("vote_average"), it.get("vote_count"))
                if int(it.get("vote_count") or 0) < 300 or wr < 7.0:
                    continue
                if any(genre_counts[g] >= cap for g in gids):
                    continue

                it["_fresh_boost"] = True
                pool[tid] = it
                for g in gids:
                    genre_counts[g] += 1
                fresh_added += 1
                if fresh_added >= max_results * 2:
                    break
        except Exception as e:
            logger.warning(f"Freshness injection failed: {e}")

    def _diversify(
        self,
        enriched: list,
        profile: Any,
        whitelist: set,
        rec_fn: callable,
        rec_alpha: float,
        watched_imdb: set,
        watched_tmdb: set,
        max_results: int,
    ) -> list:
        """Final re-ranking and diversification with strict filtering."""
        # 1. Filter and compute base scores
        pool = self._filter_and_re_rank_enriched(
            enriched, profile, whitelist, rec_fn, rec_alpha, watched_imdb, watched_tmdb
        )

        # 2. Compute Target Distribution (Decades)
        targets = self._compute_decade_targets(pool, profile, max_results)

        # 3. Final Selection with Diversity Constraints
        return self._apply_diversification(pool, targets, max_results)

    def _filter_and_re_rank_enriched(
        self,
        enriched: list,
        profile: Any,
        whitelist: set,
        rec_fn: callable,
        rec_alpha: float,
        watched_imdb: set,
        watched_tmdb: set,
    ) -> list:
        """Process enriched items, applying strict filters and final weighted scoring."""
        final_pool = []
        used_collections = set()
        used_cast = set()

        for it in enriched:
            # STRICT FILTER
            tid = it.get("_tmdb_id")
            if tid and tid in watched_tmdb:
                continue

            sid = it.get("id")
            if sid in watched_imdb:
                continue
            if sid and sid.startswith("tmdb:"):
                try:
                    if int(sid.split(":")[1]) in watched_tmdb:
                        continue
                except Exception:
                    pass

            external_imdb = it.get("_external_ids", {}).get("imdb_id")
            if external_imdb and external_imdb in watched_imdb:
                continue

            if not RecommendationFiltering.passes_top_genre_whitelist(it.get("genre_ids"), whitelist):
                continue

            sim_score, bd = self.user_profile_service.calculate_simple_overlap_with_breakdown(profile, it)
            it["_sim_breakdown"] = bd

            wr = RecommendationScoring.weighted_rating(
                it.get("vote_average"),
                it.get("vote_count"),
                C=7.2 if it.get("type") == "series" else 6.8,
            )
            v_score = RecommendationScoring.normalize(wr)
            p_score = RecommendationScoring.normalize(float(it.get("popularity") or 0.0), max_v=1000.0)

            base = (sim_score * 0.55) + (v_score * 0.35) + (p_score * 0.10)
            # Apply Genre Bias (Preference Boost/Penalty)
            base *= RecommendationFiltering.get_genre_multiplier(it.get("genre_ids"), whitelist)

            year = RecommendationMetadata.extract_year(it)
            q_mult = (1.0 - rec_alpha) + (rec_alpha * rec_fn(year))

            # Final Pass: Consistent quality adjustments (Enhanced: preserve source boosts)
            score = base + RecommendationScoring.stable_epsilon(it.get("_tmdb_id", 0), self.stable_seed)
            score = RecommendationScoring.apply_quality_adjustments(
                score * q_mult,
                wr,
                int(it.get("vote_count") or 0),
                is_ranked=bool(it.get("_ranked_candidate")),
                is_fresh=bool(it.get("_fresh_boost")),
            )

            # Simple static suppression
            penalty = 0.0
            if it.get("_collection_id") in used_collections:
                penalty += 0.05
            cast_overlap = len(set(it.get("_top_cast_ids", [])) & used_cast)
            if cast_overlap:
                penalty += min(0.03 * cast_overlap, 0.09)

            it["_adjusted_score"] = score * (1.0 - penalty)
            final_pool.append(it)

        final_pool.sort(key=lambda x: x.get("_adjusted_score", 0.0), reverse=True)
        return final_pool

    def _compute_decade_targets(self, pool: list, profile: Any, max_results: int) -> dict[int | None, int]:
        """Calculate how many slots each decade should occupy based on profile distribution."""
        decades_in_results = []
        for it in pool:
            y = RecommendationMetadata.extract_year(it)
            decades_in_results.append((int(y) // 10) * 10 if y else None)

        try:
            years_map = getattr(profile.years, "values", {}) or {}
            decade_weights = {int(k): float(v) for k, v in years_map.items() if isinstance(k, int)}
            total_w = sum(decade_weights.values())
        except Exception:
            decade_weights, total_w = {}, 0.0

        support = {d for d in decades_in_results if d is not None}
        if total_w > 0 and support:
            p_user = {d: (decade_weights.get(d, 0.0) / total_w) for d in support}
            s = sum(p_user.values())
            if s > 0:
                for d in p_user:
                    p_user[d] /= s
            else:
                p_user = {d: 1.0 / len(support) for d in support}
        else:
            p_user = {d: 1.0 / len(support) for d in support} if support else {}

        targets = defaultdict(int)
        remainders = []
        slots = max_results
        for d, p in p_user.items():
            tgt = p * slots
            base = int(tgt)
            targets[d] = base
            remainders.append((tgt - base, d))

        assigned = sum(targets.values())
        remaining = max(0, slots - assigned)
        if remaining > 0 and remainders:
            remainders.sort(key=lambda x: x[0], reverse=True)
            for _, d in remainders[:remaining]:
                targets[d] += 1
        return targets

    def _apply_diversification(self, pool: list, targets: dict, max_results: int) -> list:
        """Perform final selection loop ensuring genre caps and decade distribution are respected."""
        genre_counts = defaultdict(int)
        cap = max(1, int(max_results * PER_GENRE_MAX_SHARE))
        decade_counts = defaultdict(int)
        result = []

        for it in pool:
            if len(result) >= max_results:
                break

            gids = it.get("genre_ids") or []
            if any(genre_counts[g] >= cap for g in gids):
                continue

            y = RecommendationMetadata.extract_year(it)
            d = (int(y) // 10) * 10 if y else None
            # If d is None, we don't apply decade cap (acts as fallback)
            if d is not None and d in targets and decade_counts[d] >= targets[d]:
                continue

            result.append(it)
            for g in gids:
                genre_counts[g] += 1
            if d is not None:
                decade_counts[d] += 1

            # Clean internal fields
            it.pop("_external_ids", None)
            it.pop("_tmdb_id", None)
            it.pop("_adjusted_score", None)
            it.pop("_top_cast_ids", None)
            it.pop("_collection_id", None)

        return result

    def _filter_candidates_by_watched_and_genres(
        self, candidates: list[dict], watched_tmdb: set[int], whitelist: set[int], existing_ids: set[int] | None = None
    ) -> list[dict]:
        """
        Filter candidates by watched items and genre whitelist.

        Args:
            candidates: List of candidate items to filter
            watched_tmdb: Set of watched TMDB IDs to exclude
            whitelist: Set of preferred genre IDs
            existing_ids: Optional set of IDs to exclude (for deduplication)

        Returns:
            Filtered list of candidates
        """
        filtered = []
        existing = existing_ids or set()

        for it in candidates:
            item_id = it.get("id")
            if not item_id or item_id in existing:
                continue
            if item_id in watched_tmdb:
                continue
            if not RecommendationFiltering.passes_top_genre_whitelist(it.get("genre_ids"), whitelist):
                continue
            filtered.append(it)
            existing.add(item_id)

        return filtered

    async def get_recommendations_for_theme(self, theme_id: str, content_type: str, limit: int = 20) -> list[dict]:
        """Parse theme and fetch recommendations with strict filtering."""
        params = {}
        parts = theme_id.replace("watchly.theme.", "").split(".")

        for part in parts:
            if part.startswith("g"):
                genre_str = part[1:].replace("-", ",")
                params["with_genres"] = genre_str.replace(",", "|")
            elif part.startswith("k"):
                kw_str = part[1:].replace("-", "|")
                params["with_keywords"] = kw_str
            elif part.startswith("ct"):
                params["with_origin_country"] = part[2:]
            elif part.startswith("y"):
                try:
                    year = int(part[1:])
                    is_tv = content_type in ("tv", "series")
                    prefix = "first_air_date" if is_tv else "primary_release_date"
                    params[f"{prefix}.gte"] = f"{year}-01-01"
                    params[f"{prefix}.lte"] = f"{year+9}-12-31"
                except Exception:
                    pass
            elif part == "sort-vote":
                params["sort_by"] = "vote_average.desc"
                params["vote_count.gte"] = 200

        if "sort_by" not in params:
            params["sort_by"] = "popularity.desc"

        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        if excluded_ids:
            try:
                with_ids = {int(g) for g in (params.get("with_genres", "").replace("|", ",").split(",")) if g}
            except Exception:
                with_ids = set()
            final_without = [g for g in excluded_ids if g not in with_ids]
            if final_without:
                params["without_genres"] = "|".join(str(g) for g in final_without)

        whitelist = await self._get_genre_whitelist(content_type)
        candidates = []

        # Calculate how many pages to fetch based on excluded genres
        # When many genres are excluded, we need to fetch more pages to get enough results
        num_excluded = len(excluded_ids) if excluded_ids else 0
        # Movies and Series both have ~20 genres, so if more than 10 are excluded, fetch more pages
        if num_excluded > 10:
            # Fetch 10 pages when most genres are excluded
            pages_to_fetch = list(range(1, 11))
        elif num_excluded > 5:
            # Fetch 5 pages when many genres are excluded
            pages_to_fetch = list(range(1, 6))
        else:
            # Default: 3 pages
            pages_to_fetch = [1, 2, 3]

        try:
            discover_tasks = [self.tmdb_service.get_discover(content_type, page=p, **params) for p in pages_to_fetch]
            discover_results = await asyncio.gather(*discover_tasks, return_exceptions=True)
            for res in discover_results:
                if isinstance(res, Exception):
                    logger.error(f"Error fetching discover for {content_type}: {res}")
                    continue
                candidates.extend(res.get("results", []))
        except Exception:
            pass

        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            self.stremio_service, self._library_data, self.auth_key
        )

        # Initial filter
        filtered = self._filter_candidates_by_watched_and_genres(candidates, watched_tmdb, whitelist)

        # If we still don't have enough candidates, fetch more pages
        max_page_fetched = max(pages_to_fetch) if pages_to_fetch else 0
        if len(filtered) < limit * 2 and max_page_fetched < 15:
            try:
                # Fetch additional pages starting from where we left off
                next_page_start = max_page_fetched + 1
                additional_pages = list(range(next_page_start, min(next_page_start + 5, 20)))
                if additional_pages:
                    logger.info(f"Fetching additional pages {additional_pages} due to insufficient candidates")
                    additional_tasks = [
                        self.tmdb_service.get_discover(content_type, page=p, **params) for p in additional_pages
                    ]
                    additional_results = await asyncio.gather(*additional_tasks, return_exceptions=True)
                    # Collect new candidates from additional pages
                    new_candidates = []
                    for res in additional_results:
                        if isinstance(res, Exception):
                            continue
                        new_candidates.extend(res.get("results", []))
                    # Filter new candidates, excluding already processed ones
                    existing_ids = {it.get("id") for it in filtered}
                    additional_filtered = self._filter_candidates_by_watched_and_genres(
                        new_candidates, watched_tmdb, whitelist, existing_ids
                    )
                    filtered.extend(additional_filtered)
            except Exception as e:
                logger.warning(f"Failed to fetch additional pages: {e}")

        if len(filtered) < limit * 2:
            tmp_pool = {it["id"]: it for it in filtered}
            await self._inject_freshness(tmp_pool, content_type, watched_tmdb, set(excluded_ids), whitelist, limit)
            filtered = list(tmp_pool.values())

        meta = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, target_count=limit * 2, user_settings=self.user_settings
        )

        final = []
        for it in meta:
            if it["id"] in watched_imdb:
                continue
            if it.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue
            if not RecommendationFiltering.passes_top_genre_whitelist(it.get("genre_ids"), whitelist):
                continue
            it.pop("_external_ids", None)
            final.append(it)
            if len(final) >= limit:
                break

        return final

    async def pad_to_min(self, content_type: str, existing: list[dict], min_items: int) -> list[dict]:
        """Pad results with trending/top-rated items, ensuring strict exclusion."""
        need = max(0, int(min_items) - len(existing))
        if need <= 0:
            return existing

        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            self.stremio_service, self._library_data, self.auth_key
        )
        excluded_ids = set(RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type))
        whitelist = await self._get_genre_whitelist(content_type)

        mtype = "tv" if content_type in ("tv", "series") else "movie"
        pool = []
        try:
            tr = await self.tmdb_service.get_trending(mtype, time_window="week")
            pool.extend(tr.get("results", [])[:60])
            tr2 = await self.tmdb_service.get_top_rated(mtype)
            pool.extend(tr2.get("results", [])[:60])
        except Exception:
            pass

        existing_tmdb = set()
        for it in existing:
            tid = it.get("_tmdb_id") or it.get("tmdb_id") or it.get("id")
            try:
                if isinstance(tid, str) and tid.startswith("tmdb:"):
                    tid = int(tid.split(":")[1])
                existing_tmdb.add(int(tid))
            except Exception:
                pass

        dedup = {}
        for it in pool:
            tid = it.get("id")
            if not tid or tid in existing_tmdb or tid in watched_tmdb:
                continue
            gids = it.get("genre_ids") or []
            if excluded_ids.intersection(gids):
                continue
            if not RecommendationFiltering.passes_top_genre_whitelist(gids, whitelist):
                continue

            va, vc = float(it.get("vote_average") or 0.0), int(it.get("vote_count") or 0)
            if vc < 100 or va < 6.2:
                continue
            dedup[tid] = it
            if len(dedup) >= need * 3:
                break

        if not dedup:
            return existing

        meta = await RecommendationMetadata.fetch_batch(
            self.tmdb_service,
            list(dedup.values()),
            content_type,
            target_count=need * 2,
            user_settings=self.user_settings,
        )

        extra = []
        for it in meta:
            if it.get("id") in watched_imdb:
                continue
            if it.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue

            # Final check against existing
            is_dup = False
            for e in existing:
                if e.get("id") == it.get("id"):
                    is_dup = True
                    break
            if is_dup:
                continue

            it.pop("_external_ids", None)
            extra.append(it)
            if len(extra) >= need:
                break

        return existing + extra
