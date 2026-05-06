// Trakt Authentication Module

import { showToast } from './ui.js';
import { switchSection, unlockNavigation } from './navigation.js';

// LocalStorage keys for Trakt
const TRAKT_STORAGE_KEY = 'watchly_trakt_auth';
const EXPIRY_DAYS = 85; // Trakt tokens last 90 days; refresh a bit early

let languageSelect = null;
let getCatalogs = null;
let renderCatalogList = null;
let resetApp = null;

// --------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------

export function initializeTrakt(domElements, catalogState) {
    languageSelect = domElements.languageSelect;
    getCatalogs = catalogState.getCatalogs;
    renderCatalogList = catalogState.renderCatalogList;
    resetApp = catalogState.resetApp;

    initializeTraktConnectButton();
    initializeTraktLogoutButton();
    attemptTraktAutoLogin();
}

export function setTraktLoggedOutState() {
    clearTraktFromStorage();
    hideTraktStatus();

    const traktConnectBtn = document.getElementById('traktConnectBtn');
    if (traktConnectBtn) {
        traktConnectBtn.classList.remove('hidden');
    }
}

// --------------------------------------------------------------------------
// Storage helpers
// --------------------------------------------------------------------------

function saveTraktToStorage(authData) {
    try {
        const expiryDate = new Date();
        expiryDate.setDate(expiryDate.getDate() + EXPIRY_DAYS);
        localStorage.setItem(TRAKT_STORAGE_KEY, JSON.stringify({ ...authData, expiresAt: expiryDate.getTime() }));
    } catch (e) {
        console.warn('Failed to save Trakt auth:', e);
    }
}

function getTraktFromStorage() {
    try {
        const stored = localStorage.getItem(TRAKT_STORAGE_KEY);
        if (!stored) return null;
        const data = JSON.parse(stored);
        if (data.expiresAt && data.expiresAt < Date.now()) {
            clearTraktFromStorage();
            return null;
        }
        return data;
    } catch (e) {
        clearTraktFromStorage();
        return null;
    }
}

function clearTraktFromStorage() {
    try { localStorage.removeItem(TRAKT_STORAGE_KEY); } catch (e) { /* noop */ }
}

// --------------------------------------------------------------------------
// OAuth popup flow
// --------------------------------------------------------------------------

function initializeTraktConnectButton() {
    const btn = document.getElementById('traktConnectBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        setTraktConnecting(true);
        try {
            // 1. Fetch the authorization URL from backend
            const res = await fetch('/tokens/trakt/authorize');
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to start Trakt authorization');
            }
            const { url } = await res.json();

            // 2. Open OAuth popup
            const tokens = await openTraktPopup(url);

            // 3. Call identity check to get user info + existing settings
            await fetchTraktIdentity(tokens);

            // 4. Save to storage
            saveTraktToStorage(tokens);

            unlockNavigation();
            switchSection('config');
        } catch (err) {
            showToast(err.message || 'Trakt login failed', 'error');
        } finally {
            setTraktConnecting(false);
        }
    });
}

function initializeTraktLogoutButton() {
    const btn = document.getElementById('traktLogoutBtn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        if (resetApp) resetApp();
    });
}

/**
 * Open a popup window for Trakt OAuth and resolve when the callback page
 * posts a message back to us.
 */
function openTraktPopup(url) {
    return new Promise((resolve, reject) => {
        const width = 600;
        const height = 700;
        const left = Math.round(window.screenX + (window.outerWidth - width) / 2);
        const top = Math.round(window.screenY + (window.outerHeight - height) / 2);

        const popup = window.open(
            url,
            'trakt_oauth',
            `width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
        );

        if (!popup) {
            reject(new Error('Could not open the authorization popup. Please allow popups for this site.'));
            return;
        }

        let settled = false;

        function onMessage(event) {
            // Only accept messages from our own origin
            if (event.origin !== window.location.origin) return;
            const data = event.data;
            if (!data || typeof data !== 'object') return;

            if (data.type === 'trakt_auth_success') {
                if (!settled) {
                    settled = true;
                    cleanup();
                    resolve({
                        access_token: data.access_token,
                        refresh_token: data.refresh_token,
                        expires_at: data.expires_at,
                    });
                }
            } else if (data.type === 'trakt_auth_error') {
                if (!settled) {
                    settled = true;
                    cleanup();
                    reject(new Error(data.error || 'Trakt authorization failed'));
                }
            }
        }

        // Also detect if the user closes the popup manually
        const pollTimer = setInterval(() => {
            if (popup.closed && !settled) {
                settled = true;
                cleanup();
                reject(new Error('Authorization window was closed'));
            }
        }, 500);

        function cleanup() {
            window.removeEventListener('message', onMessage);
            clearInterval(pollTimer);
        }

        window.addEventListener('message', onMessage);
    });
}

// --------------------------------------------------------------------------
// Identity fetch + settings population
// --------------------------------------------------------------------------

async function fetchTraktIdentity(tokens) {
    const payload = {
        trakt_access_token: tokens.access_token,
        trakt_refresh_token: tokens.refresh_token || null,
        trakt_expires_at: tokens.expires_at || null,
    };

    const res = await fetch('/tokens/trakt/identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to verify Trakt identity');
    }

    const data = await res.json();
    const display = data.display || data.username || 'Trakt User';

    showTraktStatus(display);

    if (data.exists && data.settings) {
        showToast(`Welcome back, ${display}! Loading your settings…`, 'info', 5000);
        populateSettings(data.settings);

        const installHeader = document.querySelector('#sect-install h2');
        const installDesc = document.querySelector('#sect-install p');
        if (installHeader) installHeader.textContent = 'Update Settings';
        if (installDesc) installDesc.textContent = 'Update your preferences and re-install.';

        const btnText = document.querySelector('#submitBtn .btn-text');
        if (btnText) btnText.textContent = 'Update & Re-Install';
    } else {
        showToast(`Welcome, ${display}! Setting up your account…`, 'success', 5000);
    }

    // Store display name so the form submit can use it
    const traktDisplayInput = document.getElementById('traktDisplayName');
    if (traktDisplayInput) traktDisplayInput.value = display;
}

function populateSettings(s) {
    if (s.language && languageSelect) languageSelect.value = s.language;

    const popularitySelect = document.getElementById('popularitySelect');
    const yearMinInput = document.getElementById('yearMin');
    const yearMaxInput = document.getElementById('yearMax');
    const sortingOrderSelect = document.getElementById('sortingOrderSelect');

    if (s.popularity && popularitySelect) popularitySelect.value = s.popularity;
    if (s.year_min && yearMinInput) yearMinInput.value = s.year_min;
    if (s.year_max && yearMaxInput) yearMaxInput.value = s.year_max;
    if (window.updateYearSlider) window.updateYearSlider();
    if (s.sorting_order && sortingOrderSelect) sortingOrderSelect.value = s.sorting_order;

    const posterRatingProvider = document.getElementById('posterRatingProvider');
    const posterRatingApiKey = document.getElementById('posterRatingApiKey');
    if (posterRatingProvider && posterRatingApiKey && s.poster_rating?.provider && s.poster_rating?.api_key) {
        posterRatingProvider.value = s.poster_rating.provider;
        posterRatingApiKey.value = s.poster_rating.api_key;
        posterRatingProvider.dispatchEvent(new Event('change'));
    }

    const tmdbApiKeyInput = document.getElementById('tmdbApiKey');
    if (s.tmdb_api_key && tmdbApiKeyInput) tmdbApiKeyInput.value = s.tmdb_api_key;

    const simklApiKeyInput = document.getElementById('simklApiKey');
    if (s.simkl_api_key && simklApiKeyInput) simklApiKeyInput.value = s.simkl_api_key;

    const geminiApiKeyInput = document.getElementById('geminiApiKey');
    if (s.gemini_api_key && geminiApiKeyInput) geminiApiKeyInput.value = s.gemini_api_key;

    // Genres
    document.querySelectorAll('input[name="movie-genre"]').forEach(cb => cb.checked = false);
    document.querySelectorAll('input[name="series-genre"]').forEach(cb => cb.checked = false);
    if (s.excluded_movie_genres) s.excluded_movie_genres.forEach(id => {
        const cb = document.querySelector(`input[name="movie-genre"][value="${id}"]`);
        if (cb) cb.checked = true;
    });
    if (s.excluded_series_genres) s.excluded_series_genres.forEach(id => {
        const cb = document.querySelector(`input[name="series-genre"][value="${id}"]`);
        if (cb) cb.checked = true;
    });

    // Catalogs
    if (s.catalogs && Array.isArray(s.catalogs)) {
        const catalogs = getCatalogs ? getCatalogs() : [];
        s.catalogs.forEach(remote => {
            const local = catalogs.find(c => c.id === remote.id);
            if (local) {
                local.enabled = remote.enabled;
                if (remote.name) local.name = remote.name;
                if (typeof remote.enabled_movie === 'boolean') local.enabledMovie = remote.enabled_movie;
                if (typeof remote.enabled_series === 'boolean') local.enabledSeries = remote.enabled_series;
                if (typeof remote.display_at_home === 'boolean') local.display_at_home = remote.display_at_home;
                if (typeof remote.shuffle === 'boolean') local.shuffle = remote.shuffle;
            }
        });
        if (renderCatalogList) renderCatalogList();
    }
}

// --------------------------------------------------------------------------
// Auto-login
// --------------------------------------------------------------------------

async function attemptTraktAutoLogin() {
    const stored = getTraktFromStorage();
    if (!stored?.access_token) return;

    try {
        await fetchTraktIdentity(stored);
        unlockNavigation();
        switchSection('config');
    } catch (err) {
        console.warn('Trakt auto-login failed:', err);
        clearTraktFromStorage();
    }
}

// --------------------------------------------------------------------------
// UI helpers
// --------------------------------------------------------------------------

function setTraktConnecting(loading) {
    const btn = document.getElementById('traktConnectBtn');
    if (!btn) return;
    const text = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.loader');
    btn.disabled = loading;
    if (text) text.classList.toggle('hidden', loading);
    if (loader) loader.classList.toggle('hidden', !loading);
}

export function showTraktStatus(displayName) {
    const statusSection = document.getElementById('traktStatusSection');
    const displayEl = document.getElementById('traktStatusDisplay');
    const avatarEl = document.getElementById('traktStatusAvatar');
    const connectBtn = document.getElementById('traktConnectBtn');

    if (displayEl) displayEl.textContent = displayName;
    if (avatarEl) avatarEl.textContent = getInitials(displayName);
    if (statusSection) statusSection.classList.remove('hidden');
    if (connectBtn) connectBtn.classList.add('hidden');

    // Sidebar profile
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const userEmail = document.getElementById('user-email');
    const userAvatar = document.getElementById('user-avatar');
    const loginFormCard = document.getElementById('loginFormCard');

    if (userEmail) userEmail.textContent = displayName;
    if (userAvatar) userAvatar.textContent = getInitials(displayName);
    if (userProfileWrapper) userProfileWrapper.classList.remove('hidden');
    // Keep loginFormCard visible so users can navigate back and see the Trakt tab
    // Instead, switch to Trakt tab so it's clear which provider is active
    try {
        const saved = localStorage.getItem('watchly_login_tab');
        if (!saved || saved === 'trakt') {
            const traktTab = document.getElementById('tabTrakt');
            if (traktTab) traktTab.click();
        }
    } catch(e) {}
}

function hideTraktStatus() {
    const statusSection = document.getElementById('traktStatusSection');
    const connectBtn = document.getElementById('traktConnectBtn');
    if (statusSection) statusSection.classList.add('hidden');
    if (connectBtn) connectBtn.classList.remove('hidden');

    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    if (userProfileWrapper) userProfileWrapper.classList.add('hidden');
}

function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/[\s._-]+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
}

// --------------------------------------------------------------------------
// Exported helpers for form.js
// --------------------------------------------------------------------------

export function getTraktTokensFromStorage() {
    return getTraktFromStorage();
}
