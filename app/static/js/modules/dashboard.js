// Dashboard — a separate nav section (gated behind login) showing the user's install:
// manifest URL, install links, KPIs, catalog previews, and taste profile. Loaded on
// nav click. Account deletion lives in the Save & Install flow, not here.

import { openNuvioInstall } from './nuvio.js';

let appState = null;
let switchSection = null;
let dashboardData = null;
let activeContentType = 'movie';

const $ = (id) => document.getElementById(id);
const show = (el) => el && el.classList.remove('hidden');
const hide = (el) => el && el.classList.add('hidden');

const POPULARITY_LABELS = { mainstream: 'Mainstream', balanced: 'Balanced', gems: 'Hidden Gems', all: 'All' };
const SORTING_LABELS = { default: 'Default', movies_first: 'Movies first', series_first: 'Series first' };

const STATE_BLOCKS = ['dashLoggedOut', 'dashNoInstall', 'dashLoading', 'dashError', 'dashContent'];

export function initializeDashboard(actions, state) {
    appState = state;
    switchSection = actions.switchSection;

    const nav = $('nav-dashboard');
    if (nav) nav.addEventListener('click', render);

    const loginBtn = $('dashLoginBtn');
    if (loginBtn) loginBtn.addEventListener('click', () => switchSection && switchSection('login'));

    wireCopy();
    wireNuvioInstall();
    wireRefresh();
    wireProfileTabs();
    wireCatalogFilter();
}

function setState(visibleId) {
    STATE_BLOCKS.forEach((id) => hide($(id)));
    show($(visibleId));
}

async function render() {
    if (!appState || !appState.auth.loggedIn) {
        setState('dashLoggedOut');
        return;
    }
    if (!appState.auth.hasInstall || !appState.auth.token) {
        setState('dashNoInstall');
        return;
    }
    setState('dashLoading');
    try {
        const res = await fetch(`/${appState.auth.token}/dashboard/data`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Could not load your dashboard.');
        }
        dashboardData = await res.json();
        renderContent();
        setState('dashContent');
    } catch (e) {
        $('dashError').textContent = e.message;
        setState('dashError');
    }
}

function chip(text) {
    const span = document.createElement('span');
    span.className = 'inline-block text-xs bg-neutral-800 border border-slate-700 rounded-full px-3 py-1 text-slate-200';
    span.textContent = text;
    return span;
}

function chipRow(label, values) {
    if (!values || !values.length) return null;
    const wrap = document.createElement('div');
    wrap.className = 'mb-4';
    const heading = document.createElement('p');
    heading.className = 'text-xs text-slate-500 mb-2';
    heading.textContent = label;
    wrap.appendChild(heading);
    const row = document.createElement('div');
    row.className = 'flex flex-wrap gap-2';
    values.forEach((v, idx) => {
        const c = chip(v);
        c.classList.add('dash-chip');
        c.style.animationDelay = `${idx * 40}ms`;
        row.appendChild(c);
    });
    wrap.appendChild(row);
    return wrap;
}

function renderSources(sources) {
    const row = $('dashSources');
    row.innerHTML = '';
    const items = [
        { label: `Source: ${sources.active}`, on: true },
        { label: 'Trakt', on: sources.trakt },
        { label: 'Simkl', on: sources.simkl },
    ];
    items.forEach(({ label, on }) => {
        const span = document.createElement('span');
        span.className = on
            ? 'text-xs rounded-full px-3 py-1 bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
            : 'text-xs rounded-full px-3 py-1 bg-neutral-800 text-slate-500 border border-slate-700';
        span.textContent = on ? `${label} ✓` : label;
        row.appendChild(span);
    });
}

function renderSettings(s) {
    const grid = $('dashSettings');
    grid.innerHTML = '';
    const fields = [
        ['Discovery', POPULARITY_LABELS[s.popularity] || s.popularity],
        ['Language', s.language],
        ['Years', `${s.year_min}–${s.year_max}`],
        ['Sorting', SORTING_LABELS[s.sorting_order] || s.sorting_order],
    ];
    fields.forEach(([label, value]) => {
        const cell = document.createElement('div');
        cell.innerHTML = `<p class="text-xs text-slate-500 mb-1">${label}</p><p class="text-slate-200">${value}</p>`;
        grid.appendChild(cell);
    });
}

const PREVIEW_ITEM_LIMIT = 14;

// Render each served catalog as a horizontal poster strip, fetched lazily as it
// scrolls into view so opening the dashboard doesn't fan out every catalog at once.
async function loadCatalogRows() {
    const container = $('dashCatalogRows');
    container.innerHTML = '<p class="text-sm text-slate-500">Loading catalogs…</p>';

    let manifest;
    try {
        const res = await fetch(`/${appState.auth.token}/manifest.json`);
        if (!res.ok) throw new Error('manifest');
        manifest = await res.json();
    } catch (e) {
        container.innerHTML = '<p class="text-sm text-red-400">Could not load your catalogs.</p>';
        return;
    }

    const catalogs = manifest.catalogs || [];
    container.innerHTML = '';
    if (!catalogs.length) {
        container.innerHTML = '<p class="text-sm text-slate-500">No catalogs enabled.</p>';
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
    header.className = 'flex items-baseline justify-between mb-2';
    header.innerHTML =
        `<h4 class="text-sm font-medium text-slate-200 truncate">${cat.name || cat.id}</h4>` +
        `<span class="text-xs text-slate-600 ml-3 flex-shrink-0"><span class="dash-row-count"></span>${cat.type === 'series' ? 'Series' : 'Movies'}</span>`;
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
        '<div class="w-[110px] h-[165px] rounded-lg bg-neutral-800 animate-pulse"></div>' +
        '<div class="mt-1.5 h-3 w-20 rounded bg-neutral-800 animate-pulse"></div>';
    return card;
}

async function fetchCatalogRow(row) {
    const strip = row.querySelector('.dash-strip');
    const countEl = row.querySelector('.dash-row-count');
    const { type, id } = row.dataset;
    try {
        const res = await fetch(`/${appState.auth.token}/catalog/${type}/${encodeURIComponent(id)}.json`);
        if (!res.ok) throw new Error('catalog');
        const data = await res.json();
        const all = data.metas || [];
        const metas = all.slice(0, PREVIEW_ITEM_LIMIT);
        strip.innerHTML = '';
        if (!metas.length) {
            strip.innerHTML = '<p class="text-xs text-slate-600">No items yet — open it in Stremio to build it.</p>';
            return;
        }
        if (countEl) countEl.textContent = `${all.length} · `;
        metas.forEach((m) => strip.appendChild(posterCard(m, type)));
    } catch (e) {
        strip.innerHTML = '<p class="text-xs text-red-400">Could not load items.</p>';
    }
}

function posterCard(meta, type) {
    // IMDb-id items deep-link to their Stremio detail page; TMDB-only items aren't linkable.
    const linkable = typeof meta.id === 'string' && meta.id.startsWith('tt');
    const card = document.createElement(linkable ? 'a' : 'div');
    card.className = 'dash-poster-card flex-shrink-0 w-[110px] group';
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
            'dash-poster-img w-[110px] h-[165px] object-cover rounded-lg bg-neutral-800 ring-1 ring-white/5 group-hover:ring-white/30';
        img.onerror = () => { img.style.visibility = 'hidden'; };
        card.appendChild(img);
    } else {
        const ph = document.createElement('div');
        ph.className = 'w-[110px] h-[165px] rounded-lg bg-neutral-800 ring-1 ring-white/5';
        card.appendChild(ph);
    }

    const title = document.createElement('p');
    title.className = 'mt-1.5 text-xs text-slate-300 truncate group-hover:text-white transition-colors';
    title.title = meta.name || '';
    title.textContent = meta.name || '';
    card.appendChild(title);

    if (rating || year) {
        const sub = document.createElement('p');
        sub.className = 'text-[11px] text-slate-600 truncate';
        sub.textContent = `${rating}${year}`.trim();
        card.appendChild(sub);
    }

    return card;
}

function setCatalogFilter(filter) {
    document.querySelectorAll('.dashCatFilter').forEach((b) => {
        const active = b.dataset.filter === filter;
        b.classList.toggle('bg-white', active);
        b.classList.toggle('text-black', active);
        b.classList.toggle('text-slate-300', !active);
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
        tab.classList.toggle('bg-white', isActive);
        tab.classList.toggle('text-black', isActive);
        tab.classList.toggle('text-slate-300', !isActive);
    });

    const p = dashboardData.profiles[activeContentType];
    if (!p) {
        body.innerHTML = `<p class="text-sm text-slate-500">No ${activeContentType} profile yet — it builds after your first catalog request.</p>`;
        return;
    }

    const meta = document.createElement('p');
    meta.className = 'text-xs text-slate-500 mb-4';
    const when = p.last_updated ? new Date(p.last_updated).toLocaleDateString() : '—';
    meta.textContent = `Built from ${p.items} item(s) · updated ${when}`;
    body.appendChild(meta);

    const rows = [
        chipRow('Top genres', p.genres),
        chipRow('Directors', p.directors),
        chipRow('Cast', p.cast),
        chipRow('Keywords', p.keywords),
        chipRow('Eras', p.eras),
        chipRow('Countries', p.countries),
    ].filter(Boolean);

    if (!rows.length) {
        body.innerHTML += `<p class="text-sm text-slate-500">Not enough signal yet.</p>`;
        return;
    }
    rows.forEach((r) => body.appendChild(r));
}

function renderContent() {
    $('dashManifestUrl').textContent = dashboardData.manifest_url;
    renderIdentity();
    renderInstallLink();
    renderKpis(dashboardData.stats);
    renderSources(dashboardData.sources);
    renderSettings(dashboardData.settings);
    renderProfile();
    loadCatalogRows();
}

function renderIdentity() {
    const name = (appState && appState.auth.userDisplay) || '';
    $('dashEmail').textContent = name || 'Your account';
    $('dashAvatar').textContent = name ? name.replace(/@.*/, '').slice(0, 2).toUpperCase() : 'W';

    const greeting = $('dashGreeting');
    if (greeting) {
        const h = new Date().getHours();
        const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
        greeting.textContent = `${part}, welcome back`;
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
    const start = performance.now();
    function tick(now) {
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
        if (dashboardData) openNuvioInstall(dashboardData.manifest_url);
    });
}

function wireRefresh() {
    const btn = $('dashRefreshBtn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        if (!appState || !appState.auth.token) return;
        const msg = $('dashRefreshMsg');
        btn.disabled = true;
        btn.classList.add('opacity-50', 'cursor-not-allowed');
        const original = btn.textContent;
        btn.textContent = 'Refreshing…';
        try {
            const res = await fetch(`/${appState.auth.token}/dashboard/refresh`, { method: 'POST' });
            if (!res.ok) throw new Error('Refresh failed. Please try again.');
            msg.textContent = 'Refresh started — your catalogs will rebuild on the next open in Stremio.';
            msg.classList.remove('hidden', 'text-red-400');
            msg.classList.add('text-emerald-300');
        } catch (e) {
            msg.textContent = e.message;
            msg.classList.remove('hidden', 'text-emerald-300');
            msg.classList.add('text-red-400');
        } finally {
            btn.disabled = false;
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
            btn.textContent = original;
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
