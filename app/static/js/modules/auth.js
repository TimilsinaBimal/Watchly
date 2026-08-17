// Authentication Logic

import { showToast } from './ui.js';
import { clearAuthFromStorage, getAuthFromStorage, saveAuthToStorage } from './auth-storage.js';
import {
    hideUserProfile,
    renderLoggedInControls,
    renderLoggedOutControls,
    showUserProfile,
    updateInstallMode
} from './auth-ui.js';
import {
    setProviderConnected,
    setStremioConnected,
    setWatchHistorySource,
} from './accounts.js';

// DOM Elements - will be initialized
let stremioLoginBtn = null;
let stremioLoginText = null;
let emailInput = null;
let passwordInput = null;
let emailPwdContinueBtn = null;
let languageSelect = null;
let appState = null;
let renderCatalogList = null;
let resetApp = null;
let switchSection = null;
let unlockNavigation = null;
let updateYearSlider = null;
let stremioProfileCredentials = null;
let stremioProfiles = [];
let preparedStremioProfiles = [];

export function initializeAuth(domElements, state, actions) {
    stremioLoginBtn = domElements.stremioLoginBtn;
    stremioLoginText = domElements.stremioLoginText;
    emailInput = domElements.emailInput;
    passwordInput = domElements.passwordInput;
    emailPwdContinueBtn = domElements.emailPwdContinueBtn;
    languageSelect = domElements.languageSelect;
    appState = state;
    renderCatalogList = actions.renderCatalogList;
    resetApp = actions.resetApp;
    switchSection = actions.switchSection;
    unlockNavigation = actions.unlockNavigation;
    updateYearSlider = actions.updateYearSlider;

    // Initialize logout buttons
    initializeLoginStatusLogoutButton();
    initializeUserProfileDropdown();
    initializeStremioProfileSelection();

    // Try to auto-login from localStorage
    attemptAutoLogin();

    initializeStremioLogin();
    initializeEmailPasswordLogin();
}

// Initialize user profile dropdown
function initializeUserProfileDropdown() {
    const trigger = document.getElementById('user-profile-trigger');
    const dropdown = document.getElementById('user-profile-dropdown');
    const logoutBtn = document.getElementById('user-profile-logout-btn');
    const chevron = document.getElementById('user-profile-chevron');

    if (!trigger || !dropdown || !logoutBtn) return;

    // Toggle dropdown on trigger click
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = !dropdown.classList.contains('hidden');
        if (isOpen) {
            closeDropdown();
        } else {
            openDropdown();
        }
    });

    // Handle logout button click
    logoutBtn.addEventListener('click', () => {
        closeDropdown();
        // Close mobile nav if open
        const sidebar = document.getElementById('mainSidebar');
        const backdrop = document.getElementById('mobileNavBackdrop');
        if (sidebar && backdrop) {
            sidebar.classList.remove('translate-x-0');
            sidebar.classList.add('-translate-x-full');
            backdrop.classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
            const mobileToggle = document.getElementById('mobileNavToggle');
            if (mobileToggle) {
                mobileToggle.classList.remove('is-active');
                mobileToggle.setAttribute('aria-expanded', 'false');
                mobileToggle.setAttribute('aria-label', 'Open navigation');
            }
        }
        if (resetApp) resetApp();
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!trigger.contains(e.target) && !dropdown.contains(e.target)) {
            closeDropdown();
        }
    });

    function openDropdown() {
        dropdown.classList.remove('hidden');
        if (chevron) {
            chevron.style.transform = 'rotate(180deg)';
        }
    }

    function closeDropdown() {
        dropdown.classList.add('hidden');
        if (chevron) {
            chevron.style.transform = 'rotate(0deg)';
        }
    }
}

// Initialize logout button in login status section
function initializeLoginStatusLogoutButton() {
    const logoutBtn = document.getElementById('loginStatusLogoutBtn');
    if (!logoutBtn) return;

    logoutBtn.addEventListener('click', () => {
        if (resetApp) resetApp();
    });
}

// Attempt to auto-login from stored credentials
async function attemptAutoLogin() {
    // Don't auto-login if there's an auth key in URL (let URL-based login handle it)
    const urlParams = new URLSearchParams(window.location.search);
    const urlAuthKey = urlParams.get('key') || urlParams.get('authKey');
    if (urlAuthKey) return;

    const storedAuth = getAuthFromStorage();
    if (!storedAuth) return;

    stremioProfileCredentials = storedAuth.email && storedAuth.password
        ? { email: storedAuth.email, password: storedAuth.password }
        : { authKey: storedAuth.rootAuthKey || storedAuth.authKey };

    try {
        // If we have an auth key, use it
        if (storedAuth.authKey) {
            setStremioLoggedInState(storedAuth.authKey);
            await fetchStremioIdentity(storedAuth.authKey);
            await loadStremioProfiles(stremioProfileCredentials, storedAuth.profileId);
            unlockNavigation();
            switchSection('config');
            return;
        }

        // If we have email/password, use them
        if (storedAuth.email && storedAuth.password) {
            // Pre-fill inputs
            if (emailInput) emailInput.value = storedAuth.email;
            if (passwordInput) passwordInput.value = storedAuth.password;

            // Try to login
            await fetchStremioIdentity(null);
            setStremioLoggedInState('');
            await loadStremioProfiles(stremioProfileCredentials, storedAuth.profileId);
            unlockNavigation();
            switchSection('config');
            return;
        }
    } catch (error) {
        // Auto-login failed, clear stored auth
        console.warn('Auto-login failed:', error);
        clearAuthFromStorage();
        if (resetApp) resetApp();
    }
}

// Stremio Login Logic
async function initializeStremioLogin() {
    const urlParams = new URLSearchParams(window.location.search);
    const authKey = urlParams.get('key') || urlParams.get('authKey');

    if (authKey) {
        // Logged In -> Unlock; stay on Accounts so the user can connect optional providers
        setStremioLoggedInState(authKey);

        try {
            await fetchStremioIdentity(authKey);
            stremioProfileCredentials = { authKey };
            await loadStremioProfiles(stremioProfileCredentials);
            // Save auth key to localStorage for persistent login
            saveAuthToStorage({ authKey, rootAuthKey: authKey });
            unlockNavigation();
            switchSection('login');
        } catch (error) {
            showToast(error.message, "error");
            clearAuthFromStorage();
            if (resetApp) resetApp();
            return;
        }

        // Remove query param
        const newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }

    if (stremioLoginBtn) {
        stremioLoginBtn.addEventListener('click', () => {
            if (stremioLoginBtn.getAttribute('data-action') === 'logout') {
                if (resetApp) resetApp(); // Logout effectively resets the app flow
            } else {
                let appHost = window.APP_HOST;
                if (!appHost || appHost.includes('<!--')) {
                    appHost = window.location.origin;
                }
                appHost = appHost.replace(/\/$/, '');
                const callbackUrl = `${appHost}/configure`;
                const stremioLoginUrl = `https://www.stremio.com/login?appName=Watchly&appCallback=${encodeURIComponent(callbackUrl)}`;
                window.location.href = stremioLoginUrl;
            }
        });
    }
}

async function fetchStremioIdentity(authKey) {
    const payload = {};
    if (authKey) {
        payload.authKey = authKey;
    } else if (emailInput?.value && passwordInput?.value) {
        payload.email = emailInput.value.trim();
        payload.password = passwordInput.value;
    }
    await fetchIdentity(payload);
}

function initializeStremioProfileSelection() {
    const select = document.getElementById('stremioProfileSelect');
    const applyBtn = document.getElementById('stremioProfileApplyBtn');
    const pinInput = document.getElementById('stremioProfilePin');
    const allProfiles = document.getElementById('stremioAllProfiles');
    if (!select || !applyBtn || !allProfiles) return;

    select.addEventListener('change', updateStremioProfilePinVisibility);
    allProfiles.addEventListener('change', updateStremioProfileMode);
    applyBtn.addEventListener('click', prepareStremioProfiles);
    pinInput?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            prepareStremioProfiles();
        }
    });
}

async function loadStremioProfiles(credentials, preferredProfileId = null) {
    const section = document.getElementById('stremioProfileSection');
    const select = document.getElementById('stremioProfileSelect');
    if (!section || !select || !credentials) return;

    try {
        const response = await fetch('/stremio/profiles/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(credentials),
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Could not load Stremio profiles.');
        }

        const data = await response.json();
        stremioProfiles = Array.isArray(data.profiles) ? data.profiles : [];
        if (stremioProfiles.length <= 1) {
            section.classList.add('hidden');
            return;
        }

        select.replaceChildren(...stremioProfiles.map(profile => new Option(
            profile.is_master ? `${profile.name} (primary)` : profile.name,
            profile.id,
        )));
        const preferredProfile = stremioProfiles.find(profile => profile.id === preferredProfileId);
        const activeProfile = preferredProfile
            || stremioProfiles.find(profile => profile.selected)
            || stremioProfiles.find(profile => profile.is_master)
            || stremioProfiles[0];
        select.value = activeProfile.id;
        section.classList.remove('hidden');
        renderStremioProfilePinList();
        updateStremioProfileMode();

        const allProfilesEnabled = document.getElementById('stremioAllProfiles')?.checked;
        if (preferredProfile && !allProfilesEnabled) {
            setSelectedStremioProfile(preferredProfile.id, preferredProfile.name);
            setStremioProfileStatus(`Using ${preferredProfile.name} for this Watchly instance.`, 'success');
        } else if (!allProfilesEnabled) {
            setSelectedStremioProfile('', '');
            setStremioProfileStatus('Select the profile that should power this Watchly instance.');
        }
    } catch (error) {
        console.warn('Could not load Stremio profiles:', error);
        section.classList.remove('hidden');
        setStremioProfileStatus(error.message || 'Could not load Stremio profiles.', 'error');
    }
}

function renderStremioProfilePinList() {
    const container = document.getElementById('stremioProfilePinList');
    if (!container) return;
    container.replaceChildren();

    stremioProfiles.filter(profile => profile.has_pin).forEach(profile => {
        const wrapper = document.createElement('div');
        const label = document.createElement('label');
        const input = document.createElement('input');

        label.className = 'block text-xs text-slate-400 mb-2';
        label.htmlFor = `stremio-profile-pin-${profile.id}`;
        label.textContent = `PIN for ${profile.name}`;
        input.id = `stremio-profile-pin-${profile.id}`;
        input.type = 'password';
        input.inputMode = 'numeric';
        input.autocomplete = 'one-time-code';
        input.placeholder = `Enter ${profile.name}'s PIN`;
        input.dataset.stremioProfilePin = profile.id;
        input.className = 'w-full bg-neutral-900 border border-slate-700 rounded-lg px-3 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition';
        wrapper.append(label, input);
        container.append(wrapper);
    });
}

function updateStremioProfileMode() {
    const allProfiles = document.getElementById('stremioAllProfiles')?.checked;
    const singleControls = document.getElementById('stremioSingleProfileControls');
    const pinList = document.getElementById('stremioProfilePinList');
    const applyBtn = document.getElementById('stremioProfileApplyBtn');

    singleControls?.classList.toggle('hidden', allProfiles);
    pinList?.classList.toggle('hidden', !allProfiles || !stremioProfiles.some(profile => profile.has_pin));
    if (applyBtn) applyBtn.textContent = allProfiles ? 'Prepare all profiles' : 'Use this profile';
    preparedStremioProfiles = [];
    setSelectedStremioProfile('', '');
    if (!allProfiles) updateStremioProfilePinVisibility();
    setStremioProfileStatus(allProfiles
        ? `${stremioProfiles.length} profiles will receive separate Watchly instances.`
        : 'Choose the profile that should power this Watchly instance.');
}

function updateStremioProfilePinVisibility() {
    const select = document.getElementById('stremioProfileSelect');
    const pinRow = document.getElementById('stremioProfilePinRow');
    const pinInput = document.getElementById('stremioProfilePin');
    const profile = stremioProfiles.find(item => item.id === select?.value);
    const needsPin = !!profile?.has_pin;
    pinRow?.classList.toggle('hidden', !needsPin);
    if (!needsPin && pinInput) pinInput.value = '';
    setStremioProfileStatus('');
}

async function prepareStremioProfiles() {
    const select = document.getElementById('stremioProfileSelect');
    const pinInput = document.getElementById('stremioProfilePin');
    const applyBtn = document.getElementById('stremioProfileApplyBtn');
    const allProfiles = document.getElementById('stremioAllProfiles')?.checked;
    const targets = allProfiles
        ? stremioProfiles
        : stremioProfiles.filter(profile => profile.id === select?.value);
    if (!targets.length || !stremioProfileCredentials || !applyBtn) return;

    const profilePins = new Map();
    for (const profile of targets) {
        const profilePinInput = allProfiles
            ? document.querySelector(`[data-stremio-profile-pin="${CSS.escape(profile.id)}"]`)
            : pinInput;
        const pin = profilePinInput?.value.trim() || '';
        if (profile.has_pin && !pin) {
            setStremioProfileStatus(`Enter the PIN for ${profile.name}.`, 'error');
            profilePinInput?.focus();
            return;
        }
        profilePins.set(profile.id, pin);
    }

    applyBtn.disabled = true;
    applyBtn.textContent = 'Preparing...';
    preparedStremioProfiles = [];
    try {
        for (const [index, profile] of targets.entries()) {
            setStremioProfileStatus(`Preparing ${profile.name} (${index + 1}/${targets.length})...`);
            const response = await fetch('/stremio/profiles/authenticate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...stremioProfileCredentials,
                    profile_id: profile.id,
                    pin: profilePins.get(profile.id) || undefined,
                }),
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(`${profile.name}: ${error.detail || 'Could not unlock this profile.'}`);
            }

            const data = await response.json();
            preparedStremioProfiles.push({
                id: data.profile_id || profile.id,
                name: data.profile_name || profile.name,
                authKey: data.authKey,
            });
        }

        const firstProfile = preparedStremioProfiles[0];
        setStremioLoggedInState(firstProfile.authKey);
        setSelectedStremioProfile(firstProfile.id, firstProfile.name);
        await fetchStremioIdentity(firstProfile.authKey);

        const storedAuth = {
            authKey: firstProfile.authKey,
            profileId: firstProfile.id,
            profileName: firstProfile.name,
        };
        if (stremioProfileCredentials.email && stremioProfileCredentials.password) {
            storedAuth.email = stremioProfileCredentials.email;
            storedAuth.password = stremioProfileCredentials.password;
        } else if (stremioProfileCredentials.authKey) {
            storedAuth.rootAuthKey = stremioProfileCredentials.authKey;
        }
        saveAuthToStorage(storedAuth);
        if (pinInput) pinInput.value = '';
        document.querySelectorAll('[data-stremio-profile-pin]').forEach(input => { input.value = ''; });
        const message = preparedStremioProfiles.length > 1
            ? `${preparedStremioProfiles.length} profiles ready. Configure Watchly once, then generate every instance.`
            : `${firstProfile.name} is ready for this Watchly instance.`;
        setStremioProfileStatus(message, 'success');
        showToast(message, 'success', 5000);
    } catch (error) {
        preparedStremioProfiles = [];
        setStremioProfileStatus(error.message || 'Could not select this profile.', 'error');
    } finally {
        applyBtn.disabled = false;
        applyBtn.textContent = allProfiles ? 'Prepare all profiles' : 'Use this profile';
    }
}

export function getPreparedStremioProfiles() {
    return preparedStremioProfiles.map(profile => ({ ...profile }));
}

function setSelectedStremioProfile(profileId, profileName) {
    const idInput = document.getElementById('stremioProfileId');
    const nameInput = document.getElementById('stremioProfileName');
    if (idInput) idInput.value = profileId || '';
    if (nameInput) nameInput.value = profileName || '';
}

function setStremioProfileStatus(message, kind = 'neutral') {
    const status = document.getElementById('stremioProfileStatus');
    if (!status) return;
    status.textContent = message;
    status.classList.remove('text-slate-400', 'text-green-400', 'text-red-300');
    status.classList.add(kind === 'success' ? 'text-green-400' : kind === 'error' ? 'text-red-300' : 'text-slate-400');
}

// Look up an existing account by a freshly connected Trakt/Simkl token, so
// provider-only users get their saved settings and dashboard back without a
// Stremio login. Lookup failures are non-fatal — the user can still configure.
export async function recallProviderAccount(provider, tokens) {
    const payload = provider === 'trakt'
        ? { trakt_access_token: tokens.access_token }
        : { simkl_access_token: tokens.access_token };
    try {
        await fetchIdentity(payload);
    } catch (e) {
        console.warn(`Account lookup via ${provider} failed:`, e);
    }
}

async function fetchIdentity(payload) {
    const sortingOrderSelect = document.getElementById("sortingOrderSelect");
    if (sortingOrderSelect) {
        payload.sorting_order = sortingOrderSelect.value;
    }
    const tmdbApiKeyInput = document.getElementById("tmdbApiKey");
    if (tmdbApiKeyInput) {
        payload.tmdb_api_key = tmdbApiKeyInput.value.trim();
    }
    const simklApiKeyInput = document.getElementById("simklApiKey");
    if (simklApiKeyInput) {
        payload.simkl_api_key = simklApiKeyInput.value.trim();
    }
    const res = await fetch('/tokens/identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to verify identity");
    }

    const data = await res.json();
    const userDisplay = data.email || data.user_id;

    // Remember whether this account already has an install (and its token) so the
    // Dashboard section can load it without a second login.
    if (appState) {
        appState.auth.loggedIn = true;
        appState.auth.token = data.token || '';
        appState.auth.hasInstall = !!data.exists;
        appState.auth.userDisplay = userDisplay;
    }

    // Show user profile in sidebar
    showUserProfile(userDisplay);

    if (data.exists) {
        showToast(`Welcome back! Loading your settings for ${userDisplay}...`, "info", 5000);

        // POPULATE SETTINGS
        if (data.settings) {
            const s = data.settings;
            if (s.language && languageSelect) languageSelect.value = s.language;

            // Popularity & Year Range
            const popularitySelect = document.getElementById('popularitySelect');
            const yearMinInput = document.getElementById('yearMin');
            const yearMaxInput = document.getElementById('yearMax');

            if (s.popularity && popularitySelect) popularitySelect.value = s.popularity;
            if (s.year_min && yearMinInput) yearMinInput.value = s.year_min;
            if (s.year_max && yearMaxInput) yearMaxInput.value = s.year_max;
            if (updateYearSlider) updateYearSlider();

            const sortingOrderSelect = document.getElementById('sortingOrderSelect');
            if (s.sorting_order && sortingOrderSelect) sortingOrderSelect.value = s.sorting_order;

            // Handle poster rating: prefer new format, fallback to old rpdb_key
            const posterRatingProvider = document.getElementById('posterRatingProvider');
            const posterRatingApiKey = document.getElementById('posterRatingApiKey');
            const posterRatingUrlTemplate = document.getElementById('posterRatingUrlTemplate');
            if (posterRatingProvider && posterRatingApiKey) {
                if (s.poster_rating && s.poster_rating.provider && (s.poster_rating.api_key || s.poster_rating.url_template)) {
                    // New format
                    posterRatingProvider.value = s.poster_rating.provider;
                    posterRatingApiKey.value = s.poster_rating.api_key || '';
                    if (posterRatingUrlTemplate) posterRatingUrlTemplate.value = s.poster_rating.url_template || '';
                    // Trigger change event to show/hide fields
                    posterRatingProvider.dispatchEvent(new Event('change'));
                } else if (s.rpdb_key) {
                    // Old format - migrate to new format in UI
                    posterRatingProvider.value = 'rpdb';
                    posterRatingApiKey.value = s.rpdb_key;
                    // Trigger change event to show/hide fields
                    posterRatingProvider.dispatchEvent(new Event('change'));
                }
            }

            const tmdbApiKeyInput = document.getElementById('tmdbApiKey');
            if (s.tmdb_api_key && tmdbApiKeyInput) tmdbApiKeyInput.value = s.tmdb_api_key;

            const simklApiKeyInput = document.getElementById('simklApiKey');
            if (s.simkl_api_key && simklApiKeyInput) simklApiKeyInput.value = s.simkl_api_key;

            // LLM config; legacy gemini_api_key maps onto the gemini provider
            const llmProviderSelect = document.getElementById('llmProvider');
            const llmApiKeyInput = document.getElementById('llmApiKey');
            const llmModelInput = document.getElementById('llmModel');
            const llm = (s.llm && s.llm.api_key)
                ? s.llm
                : (s.gemini_api_key ? { provider: 'gemini', api_key: s.gemini_api_key, model: null } : null);
            if (llm && llmProviderSelect && llmApiKeyInput) {
                llmProviderSelect.value = llm.provider;
                llmApiKeyInput.value = llm.api_key;
                if (llmModelInput) llmModelInput.value = llm.model || '';
                // Trigger change event to show the key/model fields
                llmProviderSelect.dispatchEvent(new Event('change'));
            }

            // Watch History Source + OAuth tokens
            restoreWatchHistoryState(s);

            // Genres (Checked = Excluded)
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
                const catalogs = appState ? appState.catalogs : [];
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

        // Update UI for "Update Mode"
        updateInstallMode(true);
    } else {
        // New Account
        showToast(`Welcome! Setting up new account for ${userDisplay}`, "success", 5000);
        updateInstallMode(false);
    }
}

// Email/Password login flow
function initializeEmailPasswordLogin() {
    if (!emailPwdContinueBtn) return;
    emailPwdContinueBtn.addEventListener('click', async () => {
        const errorEl = document.getElementById('emailPwdError');
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('hidden');
        }
        const email = emailInput?.value.trim();
        const pwd = passwordInput?.value;
        if (!email || !pwd) {
            showEmailPwdError('Please enter email and password.');
            return;
        }
        if (!isValidEmail(email)) {
            showEmailPwdError('Please enter a valid email address.');
            try { emailInput?.focus(); } catch (e) { }
            return;
        }
        try {
            setEmailPwdLoading(true);
            // Reuse the shared identity handler to populate settings if account exists
            await fetchStremioIdentity(null);
            stremioProfileCredentials = { email, password: pwd };
            // Save email/password to localStorage for persistent login
            saveAuthToStorage({ email, password: pwd });
            // Mark as logged-in (disables inputs and flips button to Logout)
            setStremioLoggedInState('');
            await loadStremioProfiles(stremioProfileCredentials);
            // Stay on Accounts so the user can connect optional providers
            unlockNavigation();
        } catch (e) {
            showEmailPwdError(e.message || 'Login failed');
            clearAuthFromStorage();
            // Preserve email, clear only password
            if (passwordInput) passwordInput.value = '';
        } finally {
            setEmailPwdLoading(false);
        }
    });
}

function setEmailPwdLoading(loading) {
    try {
        if (!emailPwdContinueBtn) return;
        const t = emailPwdContinueBtn.querySelector('.btn-text');
        const l = emailPwdContinueBtn.querySelector('.loader');
        emailPwdContinueBtn.disabled = loading;
        if (t) t.classList.toggle('hidden', loading);
        if (l) l.classList.toggle('hidden', !loading);
        if (emailInput) emailInput.disabled = loading;
        if (passwordInput) passwordInput.disabled = loading;
    } catch (e) { /* noop */ }
}

function showEmailPwdError(message) {
    const el = document.getElementById('emailPwdError');
    if (!el) return;
    if (message && message.trim()) {
        el.textContent = message;
        el.classList.remove('hidden');
    } else {
        el.textContent = '';
        el.classList.add('hidden');
    }
}

function isValidEmail(value) {
    // Basic email pattern sufficient for UI validation (server still verifies)
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function setStremioLoggedInState(authKey) {
    if (appState) {
        appState.auth.loggedIn = true;
        appState.auth.authKey = authKey || '';
    }

    renderLoggedInControls({ stremioLoginBtn, stremioLoginText, authKey });
    setStremioConnected(true);
}

export function setStremioLoggedOutState() {
    if (appState) {
        appState.auth.loggedIn = false;
        appState.auth.authKey = '';
        appState.auth.userDisplay = null;
    }

    // Clear stored auth credentials
    clearAuthFromStorage();
    stremioProfileCredentials = null;
    stremioProfiles = [];
    preparedStremioProfiles = [];
    setSelectedStremioProfile('', '');
    document.getElementById('stremioProfileSection')?.classList.add('hidden');
    const profileSelect = document.getElementById('stremioProfileSelect');
    if (profileSelect) profileSelect.replaceChildren();
    const profilePin = document.getElementById('stremioProfilePin');
    if (profilePin) profilePin.value = '';

    // Hide user profile
    hideUserProfile();

    renderLoggedOutControls({ stremioLoginBtn, stremioLoginText, emailInput, passwordInput });
    setStremioConnected(false);
}

// Restore Watch History Source and OAuth connected state from saved settings
function restoreWatchHistoryState(settings) {
    window._watchlyOAuth = window._watchlyOAuth || {};

    if (settings.trakt_access_token) {
        window._watchlyOAuth.trakt = {
            access_token: settings.trakt_access_token,
            refresh_token: settings.trakt_refresh_token || '',
            expires_at: settings.trakt_token_expires_at || 0,
        };
        const traktStatus = document.getElementById('traktStatus');
        if (traktStatus) {
            traktStatus.textContent = 'Connected';
            traktStatus.classList.remove('text-slate-500');
            traktStatus.classList.add('text-green-400');
        }
        const traktLogoutBtn = document.getElementById('traktLogoutBtn');
        if (traktLogoutBtn) traktLogoutBtn.classList.remove('hidden');
        setProviderConnected('trakt', true);
        validateAndShowTraktUser(settings.trakt_access_token);
    }

    if (settings.simkl_access_token) {
        window._watchlyOAuth.simkl = {
            access_token: settings.simkl_access_token,
        };
        const simklSyncStatus = document.getElementById('simklSyncStatus');
        if (simklSyncStatus) {
            simklSyncStatus.textContent = 'Connected';
            simklSyncStatus.classList.remove('text-slate-500');
            simklSyncStatus.classList.add('text-green-400');
        }
        const simklSyncLogoutBtn = document.getElementById('simklSyncLogoutBtn');
        if (simklSyncLogoutBtn) simklSyncLogoutBtn.classList.remove('hidden');
        setProviderConnected('simkl', true);
        validateAndShowSimklUser(settings.simkl_access_token);
    }

    if (settings.watch_history_source) {
        setWatchHistorySource(settings.watch_history_source);
    }
}

async function validateAndShowTraktUser(accessToken) {
    try {
        const res = await fetch('/trakt/validation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ access_token: accessToken }),
        });
        const data = await res.json();
        const traktStatus = document.getElementById('traktStatus');
        if (data.valid && traktStatus) {
            traktStatus.textContent = data.message; // "Connected as username"
        }
    } catch (e) {
        // Silently ignore — status already shows "Connected"
    }
}

async function validateAndShowSimklUser(accessToken) {
    try {
        const res = await fetch('/simkl-sync/validation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ access_token: accessToken }),
        });
        const data = await res.json();
        const simklSyncStatus = document.getElementById('simklSyncStatus');
        if (data.valid && simklSyncStatus) {
            simklSyncStatus.textContent = data.message; // "Connected as username"
        }
    } catch (e) {
        // Silently ignore — status already shows "Connected"
    }
}
