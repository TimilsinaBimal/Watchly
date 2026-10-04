// Dashboard — a separate nav section (gated behind login) showing the user's install:
// manifest URL, install links, KPIs, catalog previews, and taste profile. Loaded on
// nav click. Account deletion lives in the Save & Install flow, not here.

import { installOnNuvio } from './nuvio.js';
import { escapeHtml } from './ui.js';

let appState = null;
let switchSection = null;
let dashboardData = null;
let activeContentType = 'movie';
let dashboardInstances = [];
let activeInstance = null;
let activeDashboardToken = '';
let dashboardRequestId = 0;

const $ = (id) => document.getElementById(id);
const show = (el) => el && el.classList.remove('hidden');
const hide = (el) => el && el.classList.add('hidden');

const POPULARITY_LABELS = { mainstream: 'Mainstream', balanced: 'Balanced', gems: 'Hidden Gems', all: 'All' };
const SORTING_LABELS = { default: 'Default', movies_first: 'Movies first', series_first: 'Series first' };
const SOURCE_LABELS = { stremio: 'Stremio', trakt: 'Trakt', simkl: 'Simkl', mdblist: 'MDBList', nuvio: 'Nuvio' };
const WARMING_LABELS = {
    pending: 'Saving your configuration',
    building_profile: 'Reading your watch history',
    profile_ready: 'Building your taste profile',
    warming_manifest: 'Assembling your catalogs',
    warming_catalogs: 'Picking your first recommendations',
};
const BADGE_OK = 'bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20';
const BADGE_WARN = 'bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20';
const BADGE_MUTED = 'bg-white/[0.04] text-neutral-300 ring-1 ring-white/10';
const SEGMENT_ACTIVE = ['bg-accent', 'text-white'];

const STATE_BLOCKS = ['dashLoggedOut', 'dashNoInstall', 'dashLoading', 'dashError', 'dashContent'];

export function initializeDashboard(actions, state) {
    appState = state;
    switchSection = actions.switchSection;

    const nav = $('nav-dashboard');
    if (nav) nav.addEventListener('click', render);

    const loginBtn = $('dashLoginBtn');
    if (loginBtn) loginBtn.addEventListener('click', () => switchSection && switchSection('login'));
    $('dashSetupBtn')?.addEventListener('click', () => switchSection && switchSection('config'));
    $('dashEditBtn')?.addEventListener('click', () => switchSection && switchSection('config'));

    wireCopy();
    wireNuvioInstall();
    wireRefresh();
    wireProfileTabs();
    wireCatalogFilter();
    wireInstancePicker();
}

function setState(visibleId) {
    STATE_BLOCKS.forEach((id) => hide($(id)));
    show($(visibleId));
}

async function render() {
    hide($('dashInstancePicker'));
    if (!appState || !appState.auth.loggedIn) {
        setState('dashLoggedOut');
        return;
    }

    setState('dashLoading');
    dashboardInstances = await loadProfileInstances();
    const installedInstances = dashboardInstances.filter(instance => instance.token);
    if (!installedInstances.length && appState.auth.token) {
        installedInstances.push({
            profile_id: '',
            profile_name: appState.auth.userDisplay || 'Current profile',
            token: appState.auth.token,
        });
        dashboardInstances = installedInstances;
    }
    if (!installedInstances.length) {
        setState('dashNoInstall');
        return;
    }

    activeInstance = installedInstances.find(instance => instance.token === activeDashboardToken)
        || installedInstances.find(instance => instance.token === appState.auth.token)
        || installedInstances[0];
    activeDashboardToken = activeInstance.token;
    renderInstancePicker();
    await loadDashboard(activeDashboardToken);
}

async function loadProfileInstances() {
    if (!appState.auth.authKey) return [];
    try {
        const response = await fetch('/stremio/profiles/instances', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ authKey: appState.auth.authKey }),
        });
        if (!response.ok) return [];
        const data = await response.json();
        return data.instances || [];
    } catch (error) {
        return [];
    }
}

async function loadDashboard(token) {
    const requestId = ++dashboardRequestId;
    const refreshMessage = $('dashRefreshMsg');
    if (refreshMessage) {
        refreshMessage.textContent = '';
        refreshMessage.classList.add('hidden');
    }
    setState('dashLoading');
    try {
        const [res, warm] = await Promise.all([
            fetch(`/${token}/dashboard/data`),
            fetch(`/${token}/status`).then(r => (r.ok ? r.json() : null)).catch(() => null),
        ]);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Could not load your dashboard.');
        }
        if (requestId !== dashboardRequestId) return;
        dashboardData = await res.json();
        renderContent(warm);
        setState('dashContent');
    } catch (e) {
        if (requestId !== dashboardRequestId) return;
        $('dashError').textContent = e.message;
        setState('dashError');
    }
}

function renderInstancePicker() {
    const picker = $('dashInstancePicker');
    const select = $('dashProfileSelect');
    if (!picker || !select) return;
    if (dashboardInstances.length <= 1) {
        hide(picker);
        return;
    }
    select.replaceChildren();
    dashboardInstances.forEach(instance => {
        const option = document.createElement('option');
        option.value = instance.token || '';
        option.disabled = !instance.token;
        option.textContent = instance.token
            ? instance.profile_name
            : `${instance.profile_name} — not configured`;
        option.selected = instance.token === activeDashboardToken;
        select.appendChild(option);
    });
    select.disabled = dashboardInstances.filter(instance => instance.token).length < 2;
    show(picker);
    updateProfileHint();
}

function updateProfileHint() {
    const hint = $('dashProfileHint');
    if (hint && activeInstance) hint.textContent = `Showing the private instance for ${activeInstance.profile_name}.`;
}

function wireInstancePicker() {
    const select = $('dashProfileSelect');
    if (!select) return;
    select.addEventListener('change', async () => {
        const instance = dashboardInstances.find(item => item.token === select.value);
        if (!instance || !instance.token || instance.token === activeDashboardToken) return;
        activeInstance = instance;
        activeDashboardToken = instance.token;
        updateProfileHint();
        await loadDashboard(activeDashboardToken);
    });
}

// The profile summary carries names in rank order but no weights, so rank is shown
// as order (the top entry accented) rather than as bar lengths the data can't back.
function chipRow(label, values) {
    if (!values || !values.length) return null;
    const wrap = document.createElement('div');
    const heading = document.createElement('p');
    heading.className = 'mb-2 text-sm font-medium text-neutral-200';
    heading.textContent = label;
    wrap.appendChild(heading);
    const row = document.createElement('div');
    row.className = 'flex flex-wrap gap-1.5';
    values.forEach((v, idx) => {
        const span = document.createElement('span');
        span.className = idx === 0
            ? 'rounded-lg bg-accent/15 px-2.5 py-1 text-[13px] font-medium text-accent-soft ring-1 ring-accent/30'
            : 'rounded-lg bg-white/[0.04] px-2.5 py-1 text-[13px] text-neutral-100 ring-1 ring-white/10';
        span.textContent = v;
        row.appendChild(span);
    });
    wrap.appendChild(row);
    return wrap;
}

function countryName(code) {
    try {
        return new Intl.DisplayNames(undefined, { type: 'region' }).of(code) || code;
    } catch (e) {
        return code;
    }
}

function renderStatus(warm, stats) {
    const el = $('dashStatus');
    let label = 'Installed';
    let tone = BADGE_OK;
    if (warm && WARMING_LABELS[warm.state]) {
        label = `Warming up: ${WARMING_LABELS[warm.state]}`;
        tone = BADGE_WARN;
    } else if (warm && warm.state === 'error') {
        label = 'Some rows finish on first open';
        tone = BADGE_WARN;
    } else if (!stats || !stats.library) {
        label = 'Waiting for first open in Stremio';
        tone = BADGE_WARN;
    }
    el.className = `badge px-2.5 py-1 text-xs ${tone}`;
    el.textContent = label;
}

function renderSources(sources) {
    const row = $('dashSources');
    row.innerHTML = '';
    const items = [
        { label: `History from ${SOURCE_LABELS[sources.active] || sources.active}`, tone: BADGE_MUTED },
        { label: sources.trakt ? 'Trakt connected' : 'Trakt not connected', tone: sources.trakt ? BADGE_OK : BADGE_MUTED },
        { label: sources.simkl ? 'Simkl connected' : 'Simkl not connected', tone: sources.simkl ? BADGE_OK : BADGE_MUTED },
        { label: sources.mdblist ? 'MDBList connected' : 'MDBList not connected', tone: sources.mdblist ? BADGE_OK : BADGE_MUTED },
        { label: sources.nuvio ? 'Nuvio connected' : 'Nuvio not connected', tone: sources.nuvio ? BADGE_OK : BADGE_MUTED },
    ];
    items.forEach(({ label, tone }) => {
        const span = document.createElement('span');
        span.className = `badge px-2.5 py-1 text-xs ${tone}`;
        span.textContent = label;
        row.appendChild(span);
    });
}

function renderSettings(s) {
    const grid = $('dashSettings');
    grid.innerHTML = '';
    const fields = [
        ['Discovery', POPULARITY_LABELS[s.popularity] || s.popularity],
        ['Language', s.language],
        ['Years', `${s.year_min}–${s.year_max ?? 'now'}`],
        ['Sorting', SORTING_LABELS[s.sorting_order] || s.sorting_order],
    ];
    fields.forEach(([label, value]) => {
        const cell = document.createElement('div');
        cell.className = 'flex items-baseline justify-between gap-4 py-2.5';
        cell.innerHTML = `<dt class="text-neutral-300">${label}</dt><dd class="text-right text-neutral-100">${escapeHtml(value)}</dd>`;
        grid.appendChild(cell);
    });
}

const PREVIEW_ITEM_LIMIT = 14;

// Render each served catalog as a horizontal poster strip, fetched lazily as it
// scrolls into view so opening the dashboard doesn't fan out every catalog at once.
async function loadCatalogRows() {
    const container = $('dashCatalogRows');
    container.innerHTML = '<p class="text-sm text-neutral-300">Loading catalogs…</p>';

    let manifest;
    try {
        const res = await fetch(`/${activeDashboardToken}/manifest.json`);
        if (!res.ok) throw new Error('manifest');
        manifest = await res.json();
    } catch (e) {
        container.innerHTML = '<p class="text-sm text-red-400">Could not load your catalogs.</p>';
        return;
    }

    const catalogs = manifest.catalogs || [];
    container.innerHTML = '';
    if (!catalogs.length) {
        container.innerHTML = '<p class="text-sm text-neutral-300">No catalogs enabled.</p>';
        return;
    }

    const observer = new IntersectionObserver(
        (entries, obs) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    obs.unobserve(entry.target);
                    fetchCatalogRow(entry.target);
                }
            });
        },
        { rootMargin: '300px' }
    );

    catalogs.forEach((cat) => {
        const row = buildCatalogRow(cat);
        container.appendChild(row);
        observer.observe(row);
    });

    setCatalogFilter('all');
}

function buildCatalogRow(cat) {
    const row = document.createElement('div');
    row.dataset.type = cat.type;
    row.dataset.id = cat.id;

    const header = document.createElement('div');
    header.className = 'mb-2.5 flex items-baseline justify-between';
    header.innerHTML =
        `<h4 class="truncate text-sm font-medium text-neutral-100">${escapeHtml(cat.name || cat.id)}</h4>` +
        `<span class="ml-3 flex-shrink-0 text-[13px] text-neutral-400"><span class="dash-row-count"></span>${cat.type === 'series' ? 'Series' : 'Movies'}</span>`;
    row.appendChild(header);

    const strip = document.createElement('div');
    strip.className = 'dash-strip flex gap-3 overflow-x-auto pb-2';
    for (let i = 0; i < 6; i++) strip.appendChild(skeletonCard());
    row.appendChild(strip);

    return row;
}

function skeletonCard() {
    const card = document.createElement('div');
    card.className = 'flex-shrink-0 w-[110px]';
    card.innerHTML =
        '<div class="w-[110px] h-[165px] rounded-lg bg-white/[0.05] animate-pulse"></div>' +
        '<div class="mt-1.5 h-3 w-20 rounded bg-white/[0.05] animate-pulse"></div>';
    return card;
}

async function fetchCatalogRow(row) {
    const strip = row.querySelector('.dash-strip');
    const countEl = row.querySelector('.dash-row-count');
    const { type, id } = row.dataset;
    try {
        const res = await fetch(`/${activeDashboardToken}/catalog/${type}/${encodeURIComponent(id)}.json`);
        if (!res.ok) throw new Error('catalog');
        const data = await res.json();
        const all = data.metas || [];
        const metas = all.slice(0, PREVIEW_ITEM_LIMIT);
        strip.innerHTML = '';
        if (!metas.length) {
            strip.innerHTML = '<p class="text-[13px] text-neutral-400">No items yet. Open it in Stremio to build it.</p>';
            return;
        }
        if (countEl) countEl.textContent = `${all.length} · `;
        metas.forEach((m) => strip.appendChild(posterCard(m, type)));
    } catch (e) {
        strip.innerHTML = '<p class="text-[13px] text-red-400">Could not load items.</p>';
    }
}

function posterCard(meta, type) {
    // IMDb-id items deep-link to their Stremio detail page; TMDB-only items aren't linkable.
    const linkable = typeof meta.id === 'string' && meta.id.startsWith('tt');
    const card = document.createElement(linkable ? 'a' : 'div');
    card.className = 'flex-shrink-0 w-[110px] group';
    if (linkable) {
        card.href = `https://web.stremio.com/#/detail/${type}/${meta.id}`;
        card.target = '_blank';
        card.rel = 'noopener';
        card.title = `Open "${meta.name || ''}" in Stremio`;
    }

    const year = meta.releaseInfo ? ` · ${meta.releaseInfo}` : '';
    const rating = meta.imdbRating && meta.imdbRating !== 'None' ? `★ ${meta.imdbRating}` : '';

    if (meta.poster) {
        const img = document.createElement('img');
        img.src = meta.poster;
        img.alt = meta.name || '';
        img.loading = 'lazy';
        img.className =
            'w-[110px] h-[165px] object-cover rounded-lg bg-white/[0.05] ring-1 ring-white/5 transition group-hover:ring-accent/60';
        img.onerror = () => { img.style.visibility = 'hidden'; };
        card.appendChild(img);
    } else {
        const ph = document.createElement('div');
        ph.className = 'w-[110px] h-[165px] rounded-lg bg-white/[0.05] ring-1 ring-white/5';
        card.appendChild(ph);
    }

    const title = document.createElement('p');
    title.className = 'mt-1.5 text-xs text-neutral-200 truncate group-hover:text-white transition-colors';
    title.title = meta.name || '';
    title.textContent = meta.name || '';
    card.appendChild(title);

    if (rating || year) {
        const sub = document.createElement('p');
        sub.className = 'text-xs text-neutral-400 truncate';
        sub.textContent = `${rating}${year}`.trim();
        card.appendChild(sub);
    }

    return card;
}

function setCatalogFilter(filter) {
    document.querySelectorAll('.dashCatFilter').forEach((b) => {
        const active = b.dataset.filter === filter;
        SEGMENT_ACTIVE.forEach((c) => b.classList.toggle(c, active));
        b.classList.toggle('text-neutral-200', !active);
    });
    document.querySelectorAll('#dashCatalogRows [data-type]').forEach((row) => {
        row.classList.toggle('hidden', filter !== 'all' && row.dataset.type !== filter);
    });
}

function wireCatalogFilter() {
    document.querySelectorAll('.dashCatFilter').forEach((b) =>
        b.addEventListener('click', () => setCatalogFilter(b.dataset.filter))
    );
}

function renderProfile() {
    const body = $('dashProfileBody');
    body.innerHTML = '';

    document.querySelectorAll('.dashProfileTab').forEach((tab) => {
        const isActive = tab.dataset.ct === activeContentType;
        SEGMENT_ACTIVE.forEach((c) => tab.classList.toggle(c, isActive));
        tab.classList.toggle('text-neutral-200', !isActive);
    });

    const p = dashboardData.profiles[activeContentType];
    if (!p) {
        body.innerHTML = `<p class="text-sm text-neutral-300">No ${activeContentType} profile yet. It builds after your first catalog request.</p>`;
        return;
    }

    const meta = document.createElement('p');
    meta.className = 'mb-5 text-sm text-neutral-300';
    const when = p.last_updated ? new Date(p.last_updated).toLocaleDateString() : '—';
    meta.textContent = `Built from ${p.items} item(s) · updated ${when}`;
    body.appendChild(meta);

    const grid = document.createElement('div');
    grid.className = 'grid gap-5 sm:grid-cols-2';

    const rows = [
        chipRow('Top genres', p.genres),
        chipRow('Directors', p.directors),
        chipRow('Cast', p.cast),
        chipRow('Keywords', p.keywords),
        chipRow('Eras', p.eras),
        chipRow('Countries', (p.countries || []).map(countryName)),
    ].filter(Boolean);

    if (!rows.length) {
        body.innerHTML += `<p class="text-sm text-neutral-300">Not enough signal yet.</p>`;
        return;
    }
    rows.forEach((r) => grid.appendChild(r));
    body.appendChild(grid);
}

function renderContent(warm) {
    $('dashManifestUrl').textContent = dashboardData.manifest_url;
    $('dashManifestUrl').title = dashboardData.manifest_url;
    renderStatus(warm, dashboardData.stats);
    renderIdentity();
    renderInstallLink();
    renderKpis(dashboardData.stats);
    renderSources(dashboardData.sources);
    renderSettings(dashboardData.settings);
    renderProfile();
    loadCatalogRows();
}

function renderIdentity() {
    const accountName = (appState && appState.auth.userDisplay) || '';
    const hasProfileChoices = dashboardInstances.length > 1;
    const name = hasProfileChoices ? activeInstance?.profile_name || accountName : accountName;
    $('dashEmail').textContent = name || 'Your profile';
    $('dashAvatar').textContent = name ? name.replace(/@.*/, '').slice(0, 2).toUpperCase() : 'W';

    const greeting = $('dashGreeting');
    if (greeting) {
        const h = new Date().getHours();
        const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
        greeting.textContent = hasProfileChoices ? `${part}, previewing this profile` : `${part}, welcome back`;
    }
}

// Ease-out count-up; leaves non-numeric values (e.g. "—") untouched.
function animateCount(el, target) {
    if (!el) return;
    if (typeof target !== 'number' || isNaN(target)) {
        el.textContent = target == null ? '—' : target;
        return;
    }
    const duration = 750;
    // A frame timestamp can precede a performance.now() taken just before, so start
    // the clock on the first frame instead, or the first frame counts below zero.
    let start = null;
    function tick(now) {
        if (start === null) start = now;
        const p = Math.min(1, (now - start) / duration);
        el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function renderInstallLink() {
    const url = dashboardData.manifest_url || '';
    // stremio:// deep link opens the install dialog in the Stremio app; web link installs via web.stremio.com.
    $('dashInstallBtn').href = url.replace(/^https?:\/\//, 'stremio://');
    $('dashInstallWebBtn').href = `https://web.stremio.com/#/addons?addon=${encodeURIComponent(url)}`;
}

function renderKpis(stats) {
    const lib = stats && stats.library;
    animateCount($('dashKpiTotal'), lib ? lib.total : '—');
    animateCount($('dashKpiLoved'), lib ? lib.loved : '—');
    animateCount($('dashKpiLiked'), lib ? lib.liked : '—');
    animateCount($('dashKpiWatched'), lib ? lib.watched : '—');
    animateCount($('dashKpiCatalogs'), stats && stats.active_catalogs != null ? stats.active_catalogs : '—');

    const lastEl = $('dashLastRefresh');
    if (stats && stats.last_refresh) {
        const d = new Date(stats.last_refresh);
        lastEl.textContent = `Last refreshed ${isNaN(d.getTime()) ? stats.last_refresh : d.toLocaleString()}`;
        lastEl.classList.remove('hidden');
    } else {
        lastEl.classList.add('hidden');
    }
}

function wireCopy() {
    const btn = $('dashCopyBtn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        if (!dashboardData) return;
        try {
            await navigator.clipboard.writeText(dashboardData.manifest_url);
            const original = btn.textContent;
            btn.textContent = 'Copied ✓';
            setTimeout(() => (btn.textContent = original), 1500);
        } catch (e) {
            /* clipboard blocked — no-op */
        }
    });
}

function wireNuvioInstall() {
    const btn = $('dashInstallNuvioBtn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        if (dashboardData) installOnNuvio(dashboardData.manifest_url);
    });
}

function wireRefresh() {
    const btn = $('dashRefreshBtn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        if (!activeDashboardToken) return;
        const msg = $('dashRefreshMsg');
        btn.disabled = true;
        btn.classList.add('opacity-50', 'cursor-not-allowed');
        const label = btn.querySelector('[data-label]');
        const original = label.textContent;
        label.textContent = 'Refreshing…';
        try {
            const res = await fetch(`/${activeDashboardToken}/dashboard/refresh`, { method: 'POST' });
            if (!res.ok) throw new Error('Refresh failed. Please try again.');
            msg.textContent = 'Refresh started. Your catalogs rebuild the next time you open Stremio.';
            msg.classList.remove('hidden', 'text-red-400');
            msg.classList.add('text-emerald-300');
        } catch (e) {
            msg.textContent = e.message;
            msg.classList.remove('hidden', 'text-emerald-300');
            msg.classList.add('text-red-400');
        } finally {
            btn.disabled = false;
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
            label.textContent = original;
        }
    });
}

function wireProfileTabs() {
    document.querySelectorAll('.dashProfileTab').forEach((tab) => {
        tab.addEventListener('click', () => {
            activeContentType = tab.dataset.ct;
            if (dashboardData) renderProfile();
        });
    });
}
