// Authentication Logic

import { showToast } from './ui.js';
import { switchSection, unlockNavigation, lockNavigationForLoggedOut } from './navigation.js';

// DOM Elements - will be initialized
let stremioLoginBtn = null;
let stremioLoginText = null;
let emailInput = null;
let passwordInput = null;
let emailPwdContinueBtn = null;
let languageSelect = null;
let getCatalogs = null;
let renderCatalogList = null;
let resetApp = null;

export function initializeAuth(domElements, catalogState) {
    stremioLoginBtn = domElements.stremioLoginBtn;
    stremioLoginText = domElements.stremioLoginText;
    emailInput = domElements.emailInput;
    passwordInput = domElements.passwordInput;
    emailPwdContinueBtn = domElements.emailPwdContinueBtn;
    languageSelect = domElements.languageSelect;
    getCatalogs = catalogState.getCatalogs;
    renderCatalogList = catalogState.renderCatalogList;
    resetApp = catalogState.resetApp;

    initializeStremioLogin();
    initializeEmailPasswordLogin();
}

// Stremio Login Logic
async function initializeStremioLogin() {
    const urlParams = new URLSearchParams(window.location.search);
    const authKey = urlParams.get('key') || urlParams.get('authKey');

    if (authKey) {
        // Logged In -> Unlock and move to config
        setStremioLoggedInState(authKey);

        try {
            await fetchStremioIdentity(authKey);
            unlockNavigation();
            switchSection('config');
        } catch (error) {
            showToast(error.message, "error");
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
    const res = await fetch('/tokens/stremio-identity', {
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

    // Show user profile in sidebar
    showUserProfile(userDisplay);

    if (data.exists) {
        showToast(`Welcome back! Loading your settings for ${userDisplay}...`, "info", 5000);

        // POPULATE SETTINGS
        if (data.settings) {
            const s = data.settings;
            if (s.language && languageSelect) languageSelect.value = s.language;
            if (s.rpdb_key && document.getElementById('rpdbKey')) document.getElementById('rpdbKey').value = s.rpdb_key;

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
                const catalogs = getCatalogs ? getCatalogs() : [];
                s.catalogs.forEach(remote => {
                    const local = catalogs.find(c => c.id === remote.id);
                    if (local) {
                        local.enabled = remote.enabled;
                        if (remote.name) local.name = remote.name;
                        if (typeof remote.enabled_movie === 'boolean') local.enabledMovie = remote.enabled_movie;
                        if (typeof remote.enabled_series === 'boolean') local.enabledSeries = remote.enabled_series;
                    }
                });
                if (renderCatalogList) renderCatalogList();
            }
        }

        // Update UI for "Update Mode"
        const installHeader = document.querySelector('#sect-install h2');
        const installDesc = document.querySelector('#sect-install p');
        if (installHeader) installHeader.textContent = "Update Settings";
        if (installDesc) installDesc.textContent = "Update your preferences and re-install.";

        const btnText = document.querySelector('#submitBtn .btn-text');
        if (btnText) btnText.textContent = "Update & Re-Install";
    } else {
        // New Account
        showToast(`Welcome! Setting up new account for ${userDisplay}`, "success", 5000);

        const installHeader = document.querySelector('#sect-install h2');
        const installDesc = document.querySelector('#sect-install p');
        if (installHeader) installHeader.textContent = "Save & Install";
        if (installDesc) installDesc.textContent = "Save your settings and install the addon.";

        const btnText = document.querySelector('#submitBtn .btn-text');
        if (btnText) btnText.textContent = "Save & Install";
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
            // Mark as logged-in (disables inputs and flips button to Logout)
            setStremioLoggedInState('');
            // Proceed to config
            unlockNavigation();
            switchSection('config');
        } catch (e) {
            showEmailPwdError(e.message || 'Login failed');
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
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Logout';
    stremioLoginBtn.setAttribute('data-action', 'logout');
    stremioLoginBtn.classList.remove('bg-stremio', 'hover:bg-stremio-hover', 'hover:bg-white', 'hover:text-black', 'hover:border-white/10', 'border-stremio-border');
    stremioLoginBtn.classList.add('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20', 'text-white');

    // Pre-fill hidden AuthKey for submission
    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = authKey;

    // Hide email/password login block and its disclaimer; keep only Logout button visible
    try {
        const emailPwdSection = document.getElementById('emailPwdSection');
        const disclaimer = document.getElementById('emailPwdDisclaimer');
        const divider = document.getElementById('emailPwdDivider');
        if (emailPwdSection) emailPwdSection.classList.add('hidden');
        if (disclaimer) disclaimer.classList.add('hidden');
        if (divider) divider.classList.add('hidden');
    } catch (e) { /* noop */ }
}

export function setStremioLoggedOutState() {
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Login with Stremio';
    stremioLoginBtn.removeAttribute('data-action');
    stremioLoginBtn.classList.add('bg-stremio', 'hover:bg-white', 'hover:text-black', 'hover:border-white/10', 'border-stremio-border', 'text-white');
    stremioLoginBtn.classList.remove('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = '';

    // Hide user profile
    hideUserProfile();

    // Restore email/password login block visibility and clear inputs
    try {
        const emailPwdSection = document.getElementById('emailPwdSection');
        const disclaimer = document.getElementById('emailPwdDisclaimer');
        const divider = document.getElementById('emailPwdDivider');
        if (emailPwdSection) emailPwdSection.classList.remove('hidden');
        if (disclaimer) disclaimer.classList.remove('hidden');
        if (divider) divider.classList.remove('hidden');
        if (emailInput) { emailInput.value = ''; }
        if (passwordInput) { passwordInput.value = ''; }
        // Reset password toggle button state to hidden
        const toggleBtn = document.querySelector('.toggle-btn[data-target="passwordInput"]');
        const pwd = document.getElementById('passwordInput');
        if (toggleBtn && pwd) {
            pwd.type = 'password';
            toggleBtn.setAttribute('title', 'Show');
            toggleBtn.setAttribute('aria-label', 'Show password');
            toggleBtn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';
        }
    } catch (e) { /* noop */ }
}

// User Profile Functions
function showUserProfile(email) {
    const userProfile = document.getElementById('user-profile');
    const userEmail = document.getElementById('user-email');
    const userAvatar = document.getElementById('user-avatar');

    if (!userProfile || !userEmail || !userAvatar) return;

    // Set email
    userEmail.textContent = email;

    // Generate avatar initials from email
    const initials = getInitialsFromEmail(email);
    userAvatar.textContent = initials;

    // Show the profile
    userProfile.classList.remove('hidden');
}

function hideUserProfile() {
    const userProfile = document.getElementById('user-profile');
    if (userProfile) {
        userProfile.classList.add('hidden');
    }
}

function getInitialsFromEmail(email) {
    if (!email) return '?';

    // If it's an email, get the part before @
    const username = email.split('@')[0];

    // Split by common separators (., _, -)
    const parts = username.split(/[._-]/);

    if (parts.length >= 2) {
        // Take first letter of first two parts
        return (parts[0][0] + parts[1][0]).toUpperCase();
    } else {
        // Take first two letters of username
        return username.substring(0, 2).toUpperCase();
    }
}
