# Changelog

## Unreleased

### Added

- Unraid template at `unraid/watchly.xml`, installable via the template URL or by adding the repo under Template Repositories (#154).

### Fixed

- Dropped the stale `GEMINI_API_KEY`/`DEFAULT_GEMINI_MODEL` server env vars from `.env.example` and the README — LLM row naming is configured per user on the configure page.

## 1.14.0 - 2026-09-01

### Added

- `ALLOW_SIGNUPS` setting: set it to `False` to lock a public instance to existing accounts. New signups get a 403 and the configure page shows a notice; existing users keep full access (#146).
- The version badge on the configure page opens a changelog popup, with a link to the GitHub releases page.

### Changed

- Release notes are generated from this changelog (with a commit-message fallback) instead of OpenAI.
- The accounts page presents Stremio, Trakt, and Simkl as equal collapsible cards, without "Recommended"/"Optional" labels.

### Fixed

- Provider logos on the accounts page are proper brand marks inlined into the page; the hot-linked Stremio logo had gone 404.
- Static assets are served with `no-cache` so deploys reach browsers that cached old bundles.

## 1.13.1 - 2026-08-25 (Sagarmatha)

### Summary

This patch bumps the application to v1.13.1 and includes targeted bug fixes to token handling, improving reliability and security around OAuth tokens.

### Bug Fixes

- Auth: Skip provider verification for masked tokens to avoid unnecessary verification steps when tokens are masked in logs or configs.
- Configure: Do not clobber live OAuth tokens with the stored-secret marker; active tokens are preserved and not overwritten by secret markers.

## 1.13.0 - 2026-08-23 (Sagarmatha Dawn)

### Summary
This release ushers in centralized API error handling, strengthened logging, broader profile sampling, and a broad set of performance improvements. It also simplifies the homepage UI by removing the taste-profile card and applies several domain and data fixes. Version 1.13.0 carries a Nepal-inspired name to celebrate new heights: Sagarmatha Dawn.

### Features
- Centralized API error handling: errors are now managed in one place rather than at each endpoint, reducing duplication and improving consistency.
- Enhanced logging: configure Loguru, tag every log line with a request ID, and suppress sensitive credentials from tracebacks for safer, cleaner logs.
- Warm-up progress visibility: users see warm-up progress before handing over the final URL, improving perceived readiness.
- Profile sampling expansion: sampling increased from 30 items to up to 200 library items for richer, more accurate taste profiles.
- Homepage simplification: removed the taste-profile feature card to streamline the landing experience.

### Improvements
- Config UI refinement: the saved-key marker is replaced with a fingerprint display for clearer identification.
- Profile workflow enhancements:
  - Sampling quota is weighted toward rated titles to better reflect user preferences.
  - Strongest items are prioritized during sampling instead of an arbitrary slice.
  - Incremental, two-source change-detection mechanism improves efficiency.
  - Trakt/Simkl items are now scored with the real scorer, improving accuracy and consistency.
  - Reuse unchanged Trakt/Simkl taste profiles to avoid unnecessary recomputation.

### Performance Enhancements
- Catalogs: serve stable slot IDs to prevent unnecessary refreshes caused by shifting slots; refresh behind the response for smoother UX.
- Catalogs: serve stale rows immediately and refresh in the background to keep data fresh without blocking.
- Install: warm accounts in the background and cache the manifest for faster initial access.
- Cache: compress large per-user cache values to reduce memory and bandwidth.
- Manifest handling: drop the manifest when all user data is invalidated to avoid stale metadata.
- Watch history handling: page through the entire Trakt watch history to ensure complete data retrieval.

### Bug Fixes
- Poster domain: follow Top Posters to the new domain to ensure continued availability.
- Translation: map ISO language codes to Google-friendly names consistently to improve localization.
- Trakt paging: fix paging to ensure complete watch history is retrieved.
- Configure UI: do not show the saved-key marker; show a fingerprint instead for clearer security indicators.

### Refactors / Architecture
- Refactor(profile): drop the external history round trip to simplify data flow.
- Refactor(profile): score Trakt/Simkl items using the real scorer for accuracy.
- Refactor(profile): reuse unchanged Trakt/Simkl taste profiles to optimize performance.
- Refactor(homepage): drop the taste-profile feature card as part of UI simplification.

## 1.12.0 - 2026-07-25 (Sagarmatha)

### Summary
This release expands provider integrations, strengthens authentication flows, and improves user experience around Nuvio, Trakt/Simkl, and LLM/provider support. It introduces dynamic poster URL placeholders, a more flexible login model, and streamlined Nuvio installation flows.

### Features
- Surface Nuvio support on the homepage to showcase latest integration and quick access.
- One-click Install on Nuvio via Nuvio Sync to simplify onboarding.
- UI enhancements for selecting LLM providers, enabling any LLM provider through a user-key approach powered by pydantic-ai.
- Poster URLs now support {type} placeholder in custom posters for dynamic posters.
- Configure: load saved settings automatically when logging in with Trakt or Simkl to preserve session state.
- Configure: allow Trakt/Simkl-only setup directly from the UI for a streamlined setup.
- Catalogs: serve Trakt/Simkl-only accounts without requiring Stremio authentication.
- Auth: allow any provider to perform a full login, not limited to Stremio.
- Auth: align identities with provider accounts and deduplicate duplicates to improve identity resolution.

### Bug Fixes
- fix(nuvio): Harden the third-party sign-in prompt to reduce friction and improve reliability.
- fix(auth): Prevent identity lookup from leaking the user's other secrets.
- fix(auth): Avoid blocking account saves due to stale provider tokens.
- fix(catalogs): Accept minted base64url tokens in route validation for safer token handling.

### Improvements
- General reliability and UX improvements across login flows and account setup, including more robust handling of third-party sign-in prompts and token validation.

## 1.11.1 - 2026-06-10 (Sagarmatha Summit)

### Summary
- Release 1.11.1 improves reliability, configurability, and documentation. Key fixes include aligning signal data sources, respecting Retry-After for HTTP retries, bounding enrichment concurrency, and aligning cache bootstrapping with configured sources.

### Features
- No new user-facing features in this release.

### Bug Fixes
- Single source of truth for popularity and other signals: centralizes signal calculation to ensure consistent behavior across components.
- Cache bootstrap: bootstrapping now respects the configured watch_history_source, aligning cache data with user configuration.
- HTTP: Retry-After header is now honored for 429 responses, resulting in smarter backoff and reduced unnecessary retries.
- Profile builder: bounds TMDB enrichment concurrency to prevent resource contention and improve stability.

### Improvements
- Documentation improvements: expanded guidance for multi-source history, catalog engines, and full configuration.
- Claude documentation: updated to replace coding standards with coding-mindset and write-like-a-human guidance to reflect modern practices.

## 1.11.0 - 2026-06-05 (Sagarmatha Dawn)

### Summary
This release introduces a new logged-in user dashboard, adds support for custom poster URLs, improves API documentation accessibility in the Vercel environment, and simplifies donation options by removing the Ko-fi option. The project version has been bumped to reflect these updates.

### Features
- Logged-in User Dashboard: Provides a personalized overview for authenticated users with quick actions and summary of activity.
- Custom Poster URLs: Allow specifying custom poster URLs to customize visuals for previews and shares.

### Improvements
- Swagger API docs now exposed in the Vercel environment, making API references easier to access in production deployments.

### UI/UX Changes
- Ko-fi donation option removed; Buy Me MoMo remains as the sole supported donation method to streamline the user experience.

### Version
- Bumped version to v1.11.0 to align with the new features and improvements.

## 1.10.0 - 2026-05-29 (Machhapuchhre-Continuum)

### Release Notes

### Summary
This milestone delivers a substantial modernization of the platform, focusing on architectural improvements, richer localization, smarter media assets, and deeper integrations with external services. Users will experience more accurate and language-aware media representations, more resilient authentication and token handling, and richer, personalized watch history data for smarter recommendations. The changes also consolidate and simplify numerous internal services for better maintainability and performance.

### Features
- Language-aware media assets: posters and logo backgrounds are now retrieved in the user language from TMDB for a more cohesive localization experience.
- Catalog metadata enhancements: added logo support and normalized IMDb ratings to ensure consistent catalog presentation.
- User-centric cache controls: introduced opt-out flags for token negative caches and rate limiting to give users and administrators finer control over caching behavior.
- Per-user caching improvements: bound Redis caches to 90 days with refresh-on-read to improve responsiveness while keeping data fresh.
- Automatic token refresh: Trakt and Simkl access tokens now refresh automatically when expired, reducing interruptions.
- Watch history integrations: added seamless integration with Trakt and Simkl to enrich user history data used for recommendations.
- New profile and scoring models: introduced enhanced data handling and scoring models to improve personalization.
- User context service: new service for managing user data and settings in a centralized way.
- Dynamic content rows: added new row-building functions to support dynamic content generation in the row_generator service.
- Simplified sampling logic: replaced SmartSampler with a standalone sample_items function for clearer and more maintainable code.
- Authentication enhancements: introduced a dedicated auth service and refactored token endpoints for a cleaner authentication workflow.
- Opt-out capabilities: additional opt-out flags for token negative cache and rate limiting provide better control for edge cases.

### Improvements & Refactors
- Core service modernization: migrated Trakt and Simkl services to a common BaseClient for improved testability, consistency, and performance.
- Catalog data model improvements: watchly.item display name is now visible and read-only; merged watchly.loved and watchly.watched into watchly.item for a unified data model.
- Profile and integration consolidation: refactored profile section and merged profile service with integration components to streamline user data handling.
- Front-end modularization: broke down frontend components into separate files for easier maintenance and evolution.
- Translation and localization: refactored translation module with better fallbacks and caching behavior; added static regex values to correct German translations; avoided caching failed translation fallbacks.
- Recommendation system refinements: clarified item-based candidate fetching, improved diversity handling, and adjusted year-era bucketing logic for more meaningful recommendations.
- Library and ingestion improvements: library ingestion now respects IMDb prefix consistently and can rebuild from Trakt/Simkl sources when configured.
- Cleanup and modernization: removed obsolete migration scripts, tightened token-related regex and startup logging, and performed various low-severity cleanup tasks to improve stability.

### Bug Fixes
- Model compatibility: replaced deprecated gemma3 model with gemma4 to align with current APIs.
- Token and caching fixes: removed unnecessary negative token cache to prevent stale decisions; reduced token TTL and improved security around token handling.
- Translation fixes: avoid word-for-word title translations in certain cases and reuse the meta language; improved German translation handling and removed problematic caching on API failures.
- API and webhook fixes: token DELETE endpoints now return JSON objects; OAuth callback pages are properly HTML-escaped to prevent injection issues; CSRF state validation added to OAuth callbacks.
- Watch history and data integrity: ensured Simkl provides accurate watch counts; cleaned up token refresh flows and 401/403 handling by clearing revoked tokens.
- Ingestion and catalog fixes: ensured IMDb prefix presence during ingestion; guard against malformed cinemeta values; fall back gracefully when seed item has no title.
- Performance and reliability: differentiation of 404 vs 5xx errors in TMDB lookups to improve logging accuracy; reuse of AsyncClient instances across calls for efficiency.
- Privacy and security: ensured catalog responses are privately cached where appropriate; eliminated exposure of raw exception details in catalog 500 responses.
- Miscellaneous fixes: corrected library construction from configured sources and improved overall error handling and resilience across services.

### Deprecations & Migrations
- Gemma model upgrade: deprecated gemma3 model in favor of gemma4 to align with updated external APIs and data structures.

### Known Considerations
- The refactors introduce architectural changes that may require configuration alignment in some deployments. Review related docs for any changes to BaseClient usage and auth endpoints.

### Notes for Developers
- This release focuses on stability, localization quality, and scalable architecture. If you customize catalog metadata or translation behavior, review the new integration points and token handling policies.

## 1.9.7 - 2026-05-06 (Sagarmatha-Refine)

### Summary
This release updates the core model usage by migrating from the deprecated gemma3 model to gemma4, and enhances the user experience with improved French translations.

### Improvements
- Upgraded core model from gemma3 to gemma4, replacing deprecated usage and aligning with the latest APIs for better stability and future compatibility.
- Enhanced French translations across the UI for a more natural phrasing and consistency (PR #130).

## 1.9.6 - 2026-04-30 (Sagarmatha)

### Summary
This patch removes an unnecessary negative token cache from the authentication flow, simplifying the verification path and reducing memory usage.

### Bug Fixes
- Removed the negative token cache for failed token verifications. This eliminates potential edge cases stemming from cached negatives and ensures correctness when token state changes.
- Reduces memory footprint associated with token caching.

### Improvements
- Cleaner authentication code path with easier maintenance. Fewer caches to reason about.

## 1.9.5 - 2026-04-04 (Sagarmatha)

### Summary
This release is a maintenance update focused on upgrading a set of project dependencies to newer versions. There are no new features or user-facing changes, but the updates improve security, compatibility, and stability across the ecosystem.

### Improvements
- Upgraded selected dependencies to the latest safe minor/patch versions to address security advisories and compatibility with modern toolchains.
- Alignment with current ecosystem standards to ensure smoother operation in newer runtimes.

### Bug Fixes
- No user-facing bugs fixed in this release.

### Security
- Dependency upgrades include security patches and mitigations where applicable. No action required for users beyond building with updated dependencies.

### Upgrade Notes
- This update does not introduce API changes. Users should run their normal build processes to adopt the updated dependencies.

## 1.9.4 - 2026-03-31 (Sagarmatha Vista)

### Release 1.9.4

### Summary
This release bumps the application to version 1.9.4 and focuses on localization-driven visuals and translation quality. It adds language-aware imagery pulled from TMDB, fixes title translation behavior, and enhances the README with contributor visuals.

### Features
- Language-aware imagery for posters and logo backgrounds are now localized using TMDB data to reflect the active language.

### Bug Fixes
- Translation: Title translation now reuses the meta language title instead of a literal word-for-word translation, ensuring consistency with the configured language.

### Improvements
- Documentation: README updated to include contributor images for better attribution.

### Notes
- Version bump performed as part of the release process (1.9.3 -> 1.9.4).

## 1.9.3 - 2026-03-23 (Sagarmatha)

### Release 1.9.3

### Summary
This patch introduces user-facing opt-out controls for two core features: token negative caching and rate limiting. The version has been bumped to 1.9.3.

### Features
- New opt-out flags to disable token negative caching. This lets you avoid caching unsuccessful token lookups when required.
- New opt-out flags to disable rate limiting. This gives you the ability to run traffic without the built-in throughput throttling when necessary.

### Improvements
- Configuration loading updated to recognize the new opt-out flags. Existing deployments retain default behavior unless you explicitly enable the opt-outs.

### Bug Fixes
- No user-facing bug fixes in this release.

## 1.9.2 - 2026-03-19 (Sagarmatha)

### Release Notes

### Summary
This release bumps the version to v1.9.2 and focuses on translation accuracy, catalog branding, and rating normalization.

### Features
- Add a logo to catalog metadata to improve branding and visual consistency across catalog entries.
- Normalize IMDb rating handling to ensure a consistent display and reliable sorting across items.

### Bug Fixes
- Translation: fix incorrect German translations from Google Translate by introducing static regex-based translation mappings, improving linguistic accuracy for German content.

## 1.9.0 - 2026-03-01 (Gosaikunda Dawn)

### Summary
A major feature-focused release introducing AI-assisted content generation, deeper integration with Simkl for recommendations, and several robustness and UI improvements. This release also strengthens data validation and error handling to provide a smoother user experience.

### Features
- Require TMDB API key field during setup to enable TMDB data access.
- Generate interest summaries and theme catalogs using a Large Language Model (LLM) for richer personalization.
- Fetch recommendations from Simkl for all loved/liked items to improve discovery and relevance.
- Add an option to enable or disable Simkl-based recommendations for flexible usage.
- Display the total number of users in the UI to provide better scale visibility.
- Add an option to group-sort results globally for more consistent organization.
- Show a clear, user-friendly error message in addon descriptions when an addon update fails.

### Refactors / Architecture
- Introduce Pydantic model validation for the stats endpoint to ensure robust data integrity.
- Merge multiple validation endpoints into a single, centralized validation path to simplify maintenance.

### Improvements
- UI and usability enhancements around user counts and sorting behavior for better discoverability.
- Consolidated validation logic reduces fragmentation and improves maintainability.

### Bug Fixes
- Improve user settings filtering for Simkl candidates to deliver more relevant results.
- Remove cache-control header when there are no recommendations to prevent unnecessary caching.
- Fix Simkl trending items retrieval that was failing due to an improper list GET operation.
- Improve retry logic to retry only retriable errors, avoiding unnecessary retries.

## 1.8.0 - 2026-02-03 (Pashupatinath)

### Summary
This is a major 1.8.0 release focused on making recommendations more personalized, reliable, and easier to reason about. It introduces onboarding-friendly trending recommendations for new users, a significant refactor of the theme-based recommendation system, daily result seeding for variety, incremental profile updates, and new runtime utilities. It also strengthens data consistency, security, and operational reliability with distributed locking, better error handling, and improved cross-origin request handling.
### Features
- Onboard with trending items: New users now receive trending recommendations to improve initial engagement and discovery.
- Theme-based recommendations refactor: Revamps the theme-based system with role-based axis recipes, adds runtime constants for movie/series durations, and introduces a comprehensive recommendation utility and scoring tests to ensure correctness.
- User-defined filtering for recommendations: Users can filter recommendations by year and popularity, with an implementation plan document provided to guide usage and future enhancements.
- Incremental profile updates: Profiles now update incrementally, reducing churn and improving responsiveness.
- Daily result seeding: A seed is added to vary results each day, providing fresh recommendations while remaining stable within a day.
- Dynamic user-specific row generator: Introduces a runtime-driven mechanism to generate user-specific rows for tailored views.
- Redis distributed locking: Adds distributed locking to coordinate library and addon services for safer, more predictable operations. Includes agent guidelines and implementation plan documentation.
- Documentation updates: Adds an implementation plan and agent guidelines to help teams plan and operate recommendations features.
### Improvements
- Performance optimization: Only fetch similar items when needed for item-based recommendations to avoid unnecessary lookups.
- Top picks improvements: Refinements to improve the relevance and quality of top-pick recommendations.
- Theme-based improvement sweep: General enhancements to the theme-based system beyond the refactor, improving alignment with titles and user context.
- Simplified data generation: Removed decade from row generation to reduce redundancy and simplify data shapes.
- In-memory caching for catalog updates: Uses in-memory cache to speed up catalog update tasks.
- CORS header hardening: Added and improved CORS headers on responses to reduce cross-origin issues.
- Profile-runtime integration: Extended runtime data to profiles to better drive recommendations.
- Library-item consistency: Adds items that exist in loved/liked APIs but not yet in the library, aligning data sources for consistency.
### Bug Fixes
- Fix: do not always initialize frequencies and related data structures to reduce unintended side effects.
- API key handling: Refined API key handling in token store to improve security and correctness.
- Poster ratings: Do not use encoded API keys when rating posters to avoid encoding-related errors.
- Row generation: Remove decade from row generation to reduce redundancy and potential mismatch.
- user_settings Redis: Fix saving of year_min, max and popularity to avoid invalid states.
- Service failure handling: Improved error handling when services fail, reducing crash scenarios.
- Token salt default: Add warning when token salt is default and improve padding filler to max, improving security posture.
- CORS headers: Fix and strengthen headers to solve cross-origin requests issues.
- User discovery preferences: Correct handling of user discovery preferences.
- Theme/title alignment: Fix theme recommendations not following the title properly.
- Top picks: Improve alignment and relevance of top picks recommendations.
- Library consistency: Ensure items not in the library but present in loved/liked APIs are treated as library items for correctness.
### Refactor
- Theme-based recommendations: Major refactor with role-based axis recipes, new runtime constants for content duration, and a comprehensive recommendation utility with scoring tests to ensure correctness and maintainability.
- Documentation scaffolding: Added agent guidelines and an implementation plan document to guide future work.
### Documentation
- Implementation plan document for recommendations features.
- Agent guidelines to support rollout, testing, and maintenance.

## 1.7.0 - 2026-01-09 (Sagarmatha)

### Summary
This release brings significant architectural refinements, performance optimizations, and user-facing enhancements focused on data handling, recommendations, and catalog management. It introduces Redis-backed caching for catalogs, a revamped recommendation and profile system, and several UX improvements to catalogs, add-ons, and templating. Documentation improvements and targeted fixes ensure more reliable behavior and clearer guidance for users and developers.

### Features
- Redis caching for catalog retrieval and Redis service integration: dramatically improved responsiveness and scalability for catalog data delivery.
- Implemented a redesigned recommendation stack and profile system: more accurate, faster recommendations with improved error handling and clearer service boundaries.
- Poster rating enhancements: adds configuration to tailor top_posters for better poster quality and relevance.
- Catalog experience enhancements: ability to enable/disable movie series catalogs separately and improved frontend-backend integration for catalogs and genres.
- Loved and liked catalogs: new categories for expressing user affinity in recommendations.
- Jinja2 templating integration: reorganized HTML components for cleaner rendering and easier templating.
- Data shuffling controls: new options to shuffle data more intelligently (only_discover and random shuffle) and a centralized shuffle_data_if_needed flow.
- Add-on metadata improvements: last updated time is shown on addon descriptions after updates.
- Recency and genre diversification: recommendation logic now emphasizes recency and genre variety to improve discovery.
- Documentation enhancements: expanded per-catalog descriptions, new badges, and visuals to better communicate catalog scope and contents.

### Improvements
- Data handling and caching: streamlined caching logic for libraries and catalogs, with better response headers and more predictable cache lifetimes.
- Recommendation and discovery: consolidated and clarified logic for fetching recommendations, enhanced error handling, and more maintainable discovery task construction.
- Frontend and backend integration: improved catalog and genre data alignment with backend data models for a more coherent UI.
- Profile and scoring: updated profile constants and scoring logic to deliver more meaningful recommendations.
- Performance: caching-related improvements reduce repeated data fetches and latency across catalog retrieval and recommendations.
- Documentation quality: added detailed descriptions for catalogs, improved README with badges, and screenshots for better onboarding.

### Refactors (meaningful architectural changes)
- Introduced shuffle_data_if_needed to streamline data shuffling logic in CatalogService.
- Consolidated recommendation fetching logic in ItemBasedService for improved clarity and error handling.
- Streamlined discover task creation in TopPicksService for maintainability and consistency.
- Enhanced frontend catalog and genre integration with backend data for smoother rendering.
- Updated strong signal item percentage and simplified scoring parameters to improve recommendation quality.
- Enhanced catalog configuration and user experience with only_discover and random shuffle options.
- Simplified recommendation filtering and theme-based service logic for clearer behavior.
- Updated profile constants and enhanced recommendation logic to improve personalization consistency (several commits).
- Improved caching logic for library items in ManifestService to reduce redundant fetches.
- Updated caching logic and response headers for catalog retrieval to optimize client-side caching.
- Miscellaneous maintenance refactors, including removal of outdated manifest request data and alignment of modules for better extensibility.

### Bug Fixes
- TopPicksService: adjust max items and update item ID retrieval method to ensure accurate sampling.
- TopPicksService: correct item reference to ensure accurate recommendation processing.
- Add-on and UI: replace description instead of append on addon update to prevent duplicate metadata.
- User profile: fix timezone import issue to ensure correct user-time related data.
- Metadata and IDs: ensure only valid IMDb IDs are returned during metadata cleaning; fix handling for TMDB IDs in several paths.
- Add-on and UI: fix get started button functionality issues observed in some flows.
- Manifest and catalog: remove unnecessary last updated date on manifest requests to keep responses clean.

### Documentation
- Docs: add detailed descriptions for each catalog to help users understand contents and scope.
- Docs: add screenshots and visuals to improve guidance and onboarding.
- Docs: add badges on readme for quick feature/glossary visibility.

### Performance and Infrastructure
- Redis-backed caching for catalog retrieval and Redis service integration to improve latency and throughput.
- Template-driven UI restructuring via Jinja2 to support cleaner rendering and easier future templating changes.
- Parallel and more efficient data fetch paths introduced to improve responsiveness during catalog and recommendation loads.

Note: This release continues the iterative improvement cadence with several RC iterations preceding a stable release, reflecting ongoing work to harden caching, recommendations, and catalog delivery.

## 1.6.1 - 2025-12-31 (Sagarmatha Summit)

### Release Notes

### Summary
This v1.6.1 release focuses on performance and accuracy improvements: optimized caching for library items, refined recommendation logic, and targeted bug fixes in the TopPicksService. A minor version bump marks preparation for the updated changes.

### Improvements
- ManifestService: Refactored caching logic for library items to reduce redundant fetches and improve lookup efficiency, leading to faster startup and smoother recommendation flows.
- Profile constants and recommendation logic: Updated profile constants and refined the recommendation computation to improve consistency and relevance.

### Bug Fixes
- TopPicksService: Adjusted maximum items in sampling and updated item ID retrieval method to ensure the sampling process evaluates the correct candidates.
- TopPicksService: Corrected item reference usage to ensure recommendations are processed against the intended items, improving accuracy.

### Chore
- Version bump to v1.6.1 (release prep and changelog alignment).

## 1.6.0 - 2025-12-30 (Sagarmatha)

### Summary
Version 1.6.0 focuses on performance, templating enhancements, and richer recommendation capabilities, while tightening payloads and improving documentation. The update introduces Redis-backed caching for catalogs and recommendations, a modern templating approach with Jinja2, expanded recommendation catalogs with liked/loved signals, and several small but meaningful improvements to payloads and docs.

### Features
- Integrate Jinja2 templating engine and restructure HTML components to enable cleaner templates and easier customization of the UI.
- Add Redis-backed caching for catalog retrieval to speed up responses and reduce backend load.
- Extend Redis caching to cover the recommendation services, improving latency and scalability for catalog-driven recommendations.
- Introduce liked and loved catalogs in the recommendation system, enabling richer user sentiment signals across all recommendations.
- Documentation improvements: README now includes status badges for quick visibility.

### Improvements
- Refined caching logic and updated response headers for catalog retrieval to ensure correct caching behavior and better client-side caching semantics.
- Remove unnecessary last updated date from manifest requests to reduce payload size and bandwidth.
- Overall performance improvements driven by Redis caching and smarter data access patterns.

### Bug Fixes
- Addon updates: fix ensures that the description field is replaced rather than appended when updating an addon, preserving accurate metadata.

### Documentation
- Add issue templates for bug reports and feature requests to streamline contributor workflows.
- Update README with badges and clearer contribution guidelines.

## 1.5.0 - 2025-12-27 (Sagarmatha Summit)

### Release Notes

### Summary
This release introduces two new personalization features for recommendations, adds visibility into addon freshness, and fixes a persistence issue after updates.

### Features
- Introduced Loved and Liked catalogs across all recommendation catalogs, enabling users to save and quickly access items they care about.
- Show last updated timestamp in the addon description after an update, providing clearer visibility into content freshness.

### Bug Fixes
- Fixed an issue where catalog names reset to defaults after updating the app. Catalog names now persist across updates, preserving user customizations.

## 1.4.5 - 2025-12-27 (Gosaikunda Dawn)

### Summary

This release (v1.4.5) introduces a brand-new recommendation services suite and a user profile system, enabling richer personalization and improved content suggestions. Platform updates include upgrading to Python 3.12 and refreshed dependencies, along with a crucial fix to ensure correct timezone handling in user profiles.

### Features

- Implemented a new recommendation services layer to deliver personalized content suggestions across the app.
- Introduced a comprehensive user profile system to support personalization, user preferences, and saved items.

### Bug Fixes

- Fixed a timezone import issue in user_profile to ensure correct timestamps and scheduling behavior across the app.

### Improvements

- Upgraded development/runtime to Python 3.12 with updated dependencies to benefit from latest language features and security improvements.
- Version bumped to v1.4.5 to reflect the new features and stability improvements.

## 1.4.4 - 2025-12-27 (Gosaikunda Dawn)

### Summary
- Introduces a new Recommendation Engine and a Profile System to personalize content and improve user data management. (#82)

### Features
- New Recommendation Engine delivers personalized content based on user interactions, with a scalable architecture. (#82)
- New Profile System enables storing and updating user preferences, settings, and basic profile data for more accurate personalization. (#82)

### Improvements
- Backend data model extended to support profiles, enabling future enhancements and analytics. (#82)
- Performance improvements through recommendation caching and more efficient query paths. (#82)
- Security and privacy enhancements for profile data with clearer access controls. (#82)

### Migration / Notes
- This update is additive; existing client integrations remain compatible while new APIs are introduced for recommendations and profiles. (#82)

## 1.4.3 - 2025-12-25 (Sagarmatha Sentinel)

### Summary
Release 1.4.3 delivers data integrity improvements and performance enhancements. It includes fixes to metadata cleaning to only include valid IMDb IDs, improved handling to avoid using TMDB IDs as final metadata, better item fetching when genres are excluded, and a caching improvement to speed up catalog loading.

### Improvements
- Cache catalogs for 6 hours to speed startup and reduce repeated fetches. (#123)

### Bug Fixes
- Ensure only valid IMDb IDs are returned during metadata cleaning, preventing invalid IDs from polluting data. (#123)
- Remove items that improperly use TMDB IDs as final metadata to ensure data consistency and correct linking. (#123)
- When genres are excluded, fetch more items to maintain catalog completeness and accuracy (refs: #79). (#123)

## 1.4.2 - 2025-12-21 (Sagarmatha Dawn)

### Summary
This patch introduces a performance improvement by caching catalog data for 6 hours and bumps the release version to v1.4.2.

### Improvements
- Cache catalogs for 6 hours to reduce repeated catalog fetches and improve startup and runtime performance. (#123)

### Maintenance
- Bump version to v1.4.2 to align with the patch release. (#123)

## 1.4.1 - 2025-12-21

### Bug Fixes
* ci: fix release generation script
* fix: handle redirection on announcement url

### Other Changes
* chore: bump version to v1.4.1
* chore: set default environment to production

## 1.4.0 - 2025-12-20

### Features
* docs: add hostname and typo fixes
* feat: add option to enable/disable movie series catalog separately (#75)

### Bug Fixes
* fix: use integer value for catalog update interval

### Other Changes
* chore: bump version to v1.4.0

## 1.3.5 - 2025-12-20

### Technical Changes
* ci: push both arm and amd images in ghcr

## 1.3.4 - 2025-12-20

### Features
* fix: add support for tmdb ids (#74)
* deps: add pydantic core

### Bug Fixes
* fix: use proper language api to return tmdb available languages (#73)

### Other Changes
* chore: bump version to v1.3.4
* pin vercel python version

## 1.3.3 - 2025-12-20

### Features
* feat: update catalogs on user request with better mechanism (#70)

### Improvements
* refactor: use parallel execution to fetch recommendations from tmdb

### Other Changes
* opt: parallelize data fetch

## 1.3.2 - 2025-12-20

### Features
* feat: enhance CI workflow with Docker Buildx and QEMU setup (#67)

### Improvements
* refactor: rearchitect app to make systems modular (#66)

## 1.3.1 - 2025-12-17

### Features
* refactor: add centralized method to get auth token (#61)

## 1.3.0 - 2025-12-17

### Features
* feat: add option to login using email/password (#60)

## 1.2.0 - 2025-12-16

### Features
* feat: add options to select minimum and maximum number of items in catalogs (#54)

## 1.1.4 - 2025-12-15

### Bug Fixes
* fix: invalidate cache on delete/store (#50)

## 1.1.3 - 2025-12-15 (Pashupatinath)

No significant changes to describe.

## 1.1.2 - 2025-12-14

### Features
* feat: Refactor catalog fetching and update migration task handling

### Other Changes
* chore: bump version to v1.1.2

## 1.1.1 - 2025-12-14

### Features
* feat: Enhance Redis client management and implement rate limiting for token requests

## 1.1.0 - 2025-12-13

### Features
* feat: Add recency preference and genre diversification to recommendation logic (#44)

## 1.0.1 - 2025-12-12

### Features
* feat: better bare row name generation

### Bug Fixes
* fix: get started button is not functional
* fix: get started button is not functional

### Other Changes
* chore: bump version to 1.0.1 (#38)

## 1.0.0-rc.4 - 2025-12-05

### What's Changed
* Add option to delete account
* Fix Recommendation Catalog rename error


**Full Changelog**: https://github.com/TimilsinaBimal/Watchly/compare/1.0.0-rc.3...1.0.0-rc.4

## 1.0.0-rc.3 - 2025-12-01

### Bug Fixes
* fix: priotrize keywords for row generation than genre

### Technical Changes
* chore: use redis token from config

### Other Changes
* chore: bump version to v1.0.0-rc.3

## 1.0.0 - 2025-12-12

### What's New
- A fully redesigned UI for a smoother and cleaner experience
- Direct Stremio authentication, so you no longer need to manually enter your email or password
- No passwords are stored on the server at any time
- Option to add an RPDb API key
- Option to exclude genres you do not want in your recommendations
- Option to enable, disable, rename, or reorder catalogs
- Option to add multiple languages
- Ability to delete your account and all data instantly
- Recommendations now use your entire Stremio library: watched, rated, added
- Netflix style catalogs including genre, keyword, actor, country, and source based categories like “based on a book”
- Fewer errors and a lot of backend optimization for better stability


**Full Changelog**: https://github.com/TimilsinaBimal/Watchly/compare/v0.1.4...1.0.0

## v0.1.4 - 2025-11-30

### What's Changed
* docs: add donation using paypal by @TimilsinaBimal in https://github.com/TimilsinaBimal/Watchly/pull/3
* Switch credential storage from URLs to redis+tokens by @funkypenguin in https://github.com/TimilsinaBimal/Watchly/pull/2
* feat: store credentials in redis and better ui and optimization by @TimilsinaBimal in https://github.com/TimilsinaBimal/Watchly/pull/4
* add host name config by @TimilsinaBimal in https://github.com/TimilsinaBimal/Watchly/pull/5
* feat: feat: add GitHub Actions workflow for building and pushing Docker images to GitHub Container Registry by @TimilsinaBimal in https://github.com/TimilsinaBimal/Watchly/pull/8
* feat: enhance catalog updater with cron and interval modes for background updates by @TimilsinaBimal in https://github.com/TimilsinaBimal/Watchly/pull/13

### New Contributors
* @TimilsinaBimal made their first contribution in https://github.com/TimilsinaBimal/Watchly/pull/3
* @funkypenguin made their first contribution in https://github.com/TimilsinaBimal/Watchly/pull/2

**Full Changelog**: https://github.com/TimilsinaBimal/Watchly/commits/v0.1.4
