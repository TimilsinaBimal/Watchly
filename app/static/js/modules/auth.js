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

// LocalStorage keys
const STORAGE_KEY = 'watchly_auth';
const EXPIRY_DAYS = 30;

// LocalStorage helper functions
function saveAuthToStorage(authData) {
    try {
        const expiryDate = new Date();
        expiryDate.setDate(expiryDate.getDate() + EXPIRY_DAYS);
        const data = {
            ...authData,
            expiresAt: expiryDate.getTime()
        };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
        console.warn('Failed to save auth to localStorage:', e);
    }
}

function getAuthFromStorage() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (!stored) return null;

        const data = JSON.parse(stored);
        const now = Date.now();

        // Check if expired
        if (data.expiresAt && data.expiresAt < now) {
            clearAuthFromStorage();
            return null;
        }

        return data;
    } catch (e) {
        console.warn('Failed to read auth from localStorage:', e);
        clearAuthFromStorage();
        return null;
    }
}

function clearAuthFromStorage() {
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
        console.warn('Failed to clear auth from localStorage:', e);
    }
}

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

    // Initialize logout buttons
    initializeLoginStatusLogoutButton();
    initializeUserProfileDropdown();

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

    try {
        // If we have an auth key, use it
        if (storedAuth.authKey) {
            setStremioLoggedInState(storedAuth.authKey);
            await fetchStremioIdentity(storedAuth.authKey);
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
        // Logged In -> Unlock and move to config
        setStremioLoggedInState(authKey);

        try {
            await fetchStremioIdentity(authKey);
            // Save auth key to localStorage for persistent login
            saveAuthToStorage({ authKey });
            unlockNavigation();
            switchSection('config');
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

            // Handle poster rating: prefer new format, fallback to old rpdb_key
            const posterRatingProvider = document.getElementById('posterRatingProvider');
            const posterRatingApiKey = document.getElementById('posterRatingApiKey');
            if (posterRatingProvider && posterRatingApiKey) {
                if (s.poster_rating && s.poster_rating.provider && s.poster_rating.api_key) {
                    // New format
                    posterRatingProvider.value = s.poster_rating.provider;
                    posterRatingApiKey.value = s.poster_rating.api_key;
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
                        if (typeof remote.display_at_home === 'boolean') local.display_at_home = remote.display_at_home;
                        if (typeof remote.shuffle === 'boolean') local.shuffle = remote.shuffle;
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
            // Save email/password to localStorage for persistent login
            saveAuthToStorage({ email, password: pwd });
            // Mark as logged-in (disables inputs and flips button to Logout)
            setStremioLoggedInState('');
            // Proceed to config
            unlockNavigation();
            switchSection('config');
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

    // Clear stored auth credentials
    clearAuthFromStorage();

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
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const userEmail = document.getElementById('user-email');
    const userAvatar = document.getElementById('user-avatar');

    // Login status section elements
    const loginStatusSection = document.getElementById('loginStatusSection');
    const loginStatusEmail = document.getElementById('loginStatusEmail');
    const loginStatusAvatar = document.getElementById('loginStatusAvatar');

    if (!userProfileWrapper || !userEmail || !userAvatar) return;

    // Set email
    userEmail.textContent = email;

    // Generate avatar initials from email
    const initials = getInitialsFromEmail(email);
    userAvatar.textContent = initials;

    // Show the profile dropdown wrapper
    userProfileWrapper.classList.remove('hidden');

    // Show login status section and update it
    if (loginStatusSection && loginStatusEmail && loginStatusAvatar) {
        loginStatusEmail.textContent = email;
        loginStatusAvatar.textContent = initials;
        loginStatusSection.classList.remove('hidden');
    }

    // Hide the login form when logged in
    const loginFormCard = document.getElementById('loginFormCard');
    if (loginFormCard) loginFormCard.classList.add('hidden');
}

function hideUserProfile() {
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const dropdown = document.getElementById('user-profile-dropdown');
    const loginStatusSection = document.getElementById('loginStatusSection');

    if (userProfileWrapper) {
        userProfileWrapper.classList.add('hidden');
    }

    // Close dropdown if open
    if (dropdown) {
        dropdown.classList.add('hidden');
        const chevron = document.getElementById('user-profile-chevron');
        if (chevron) {
            chevron.style.transform = 'rotate(0deg)';
        }
    }

    // Hide login status section
    if (loginStatusSection) {
        loginStatusSection.classList.add('hidden');
    }

    // Show the login form when logged out
    const loginFormCard = document.getElementById('loginFormCard');
    if (loginFormCard) loginFormCard.classList.remove('hidden');
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
