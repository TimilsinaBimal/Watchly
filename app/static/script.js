// Default catalog configurations
const defaultCatalogs = [
    { id: 'watchly.rec', name: 'Top Picks for You', enabled: true, enabledMovie: true, enabledSeries: true, minItems: 20, maxItems: 24, description: 'Personalized recommendations based on your library' },
    { id: 'watchly.loved', name: 'More Like', enabled: true, enabledMovie: true, enabledSeries: true, minItems: 20, maxItems: 24, description: 'Recommendations similar to content you explicitly loved' },
    { id: 'watchly.watched', name: 'Because You Watched', enabled: true, enabledMovie: true, enabledSeries: true, minItems: 20, maxItems: 24, description: 'Recommendations based on your recent watch history' },
    { id: 'watchly.theme', name: 'Genre & Keyword Catalogs', enabled: true, enabledMovie: true, enabledSeries: true, minItems: 20, maxItems: 24, description: 'Dynamic catalogs based on your favorite genres, keyword, countries and many more. Just like netflix. Example: American Horror, Based on Novel or Book etc.' },
];

let catalogs = JSON.parse(JSON.stringify(defaultCatalogs));

// Genre Constants
const MOVIE_GENRES = [
    { id: '28', name: 'Action' }, { id: '12', name: 'Adventure' }, { id: '16', name: 'Animation' }, { id: '35', name: 'Comedy' }, { id: '80', name: 'Crime' }, { id: '99', name: 'Documentary' }, { id: '18', name: 'Drama' }, { id: '10751', name: 'Family' }, { id: '14', name: 'Fantasy' }, { id: '36', name: 'History' }, { id: '27', name: 'Horror' }, { id: '10402', name: 'Music' }, { id: '9648', name: 'Mystery' }, { id: '10749', name: 'Romance' }, { id: '878', name: 'Science Fiction' }, { id: '10770', name: 'TV Movie' }, { id: '53', name: 'Thriller' }, { id: '10752', name: 'War' }, { id: '37', name: 'Western' }
];

const SERIES_GENRES = [
    { id: '10759', name: 'Action & Adventure' }, { id: '16', name: 'Animation' }, { id: '35', name: 'Comedy' }, { id: '80', name: 'Crime' }, { id: '99', name: 'Documentary' }, { id: '18', name: 'Drama' }, { id: '10751', name: 'Family' }, { id: '10762', name: 'Kids' }, { id: '9648', name: 'Mystery' }, { id: '10763', name: 'News' }, { id: '10764', name: 'Reality' }, { id: '10765', name: 'Sci-Fi & Fantasy' }, { id: '10766', name: 'Soap' }, { id: '10767', name: 'Talk' }, { id: '10768', name: 'War & Politics' }, { id: '37', name: 'Western' }
];

// DOM Elements
const configForm = document.getElementById('configForm');
const catalogList = document.getElementById('catalogList');
const movieGenreList = document.getElementById('movieGenreList');
const seriesGenreList = document.getElementById('seriesGenreList');
const errorMessage = document.getElementById('errorMessage');
const submitBtn = document.getElementById('submitBtn');
const stremioLoginBtn = document.getElementById('stremioLoginBtn');
const stremioLoginText = document.getElementById('stremioLoginText');
const emailInput = document.getElementById('emailInput');
const passwordInput = document.getElementById('passwordInput');
const emailPwdContinueBtn = document.getElementById('emailPwdContinueBtn');
const languageSelect = document.getElementById('languageSelect');
const configNextBtn = document.getElementById('configNextBtn');
const catalogsNextBtn = document.getElementById('catalogsNextBtn');
const successResetBtn = document.getElementById('successResetBtn');
const deleteAccountBtn = document.getElementById('deleteAccountBtn');

const navItems = {
    welcome: document.getElementById('nav-welcome'),
    login: document.getElementById('nav-login'),
    config: document.getElementById('nav-config'),
    catalogs: document.getElementById('nav-catalogs'),
    install: document.getElementById('nav-install')
};

const sections = {
    welcome: document.getElementById('sect-welcome'),
    login: document.getElementById('sect-login'),
    config: document.getElementById('sect-config'),
    catalogs: document.getElementById('sect-catalogs'),
    install: document.getElementById('sect-install'),
    success: document.getElementById('sect-success')
};

// Main scroll container
const mainEl = document.querySelector('main');
const sidebarEl = document.getElementById('mainSidebar');
const headerEl = document.getElementById('mobileHeader');

function updateMobileLayout() {
    try {
        const isMobile = window.matchMedia('(max-width: 767.98px)').matches;
        const header = headerEl;
        if (!header || !mainEl || !sidebarEl) return;
        const h = header.offsetHeight || 0;
        document.documentElement.style.setProperty('--mobile-header', `${h}px`);

        if (isMobile) {
            mainEl.style.paddingTop = `${h}px`;
            sidebarEl.style.top = `${h}px`;
            sidebarEl.style.height = `calc(100dvh - ${h}px)`;
        } else {
            mainEl.style.paddingTop = '';
            sidebarEl.style.top = '';
            sidebarEl.style.height = '';
        }
    } catch (e) { /* noop */ }
}

// Welcome Elements
const btnGetStarted = document.getElementById('btn-get-started');


// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Start at Welcome
    switchSection('welcome');
    initializeWelcomeFlow();

    initializeNavigation();
    // By default, ensure logged-out users see only Welcome/Login and not configure/install/catalogs
    lockNavigationForLoggedOut();
    initializeCatalogList();
    initializeLanguageSelect();
    initializeMobileNav();
    initializeGenreLists();
    initializeFormSubmission();
    initializeSuccessActions();
    initializeStremioLogin();
    initializeEmailPasswordLogin();
    initializePasswordToggles();
    initializeFooter();
    initializeKofi();
    initializeAnnouncement();

    // Layout adjustments for fixed mobile header
    updateMobileLayout();
    window.addEventListener('resize', updateMobileLayout);
    window.addEventListener('orientationchange', updateMobileLayout);

    // Next Buttons
    if (configNextBtn) configNextBtn.addEventListener('click', () => switchSection('catalogs'));
    if (catalogsNextBtn) catalogsNextBtn.addEventListener('click', () => switchSection('install'));

    // Reset Buttons
    document.getElementById('resetBtn')?.addEventListener('click', resetApp);
    if (successResetBtn) successResetBtn.addEventListener('click', resetApp);
});


// Welcome Flow Logic
function initializeWelcomeFlow() {
    // Single "Get Started" button leads to Stremio login
    if (!btnGetStarted) return;

    // Support mobile taps reliably while avoiding double-fire (touch -> click)
    let touched = false;
    const handleGetStarted = (e) => {
        if (e.type === 'click' && touched) return;
        if (e.type === 'touchstart') touched = true;
        navItems.login.classList.remove('disabled');
        switchSection('login');
    };

    btnGetStarted.addEventListener('click', handleGetStarted);
    btnGetStarted.addEventListener('touchstart', handleGetStarted, { passive: true });
}


// Navigation Logic
function initializeNavigation() {
    Object.keys(navItems).forEach(key => {
        navItems[key].addEventListener('click', () => {
            if (!navItems[key].classList.contains('disabled')) {
                switchSection(key);
            }
        });
    });
}

function unlockNavigation() {
    Object.values(navItems).forEach(el => el.classList.remove('disabled'));
}

function lockNavigationForLoggedOut() {
    // Ensure welcome and login remain accessible; disable only config/catalogs/install
    if (navItems.welcome) navItems.welcome.classList.remove('disabled');
    if (navItems.login) navItems.login.classList.remove('disabled');
    if (navItems.config) navItems.config.classList.add('disabled');
    if (navItems.catalogs) navItems.catalogs.classList.add('disabled');
    if (navItems.install) navItems.install.classList.add('disabled');
}

function initializeMobileNav() {
    const mobileToggle = document.getElementById('mobileNavToggle');
    const sidebar = document.getElementById('mainSidebar');
    const backdrop = document.getElementById('mobileNavBackdrop');
    if (!mobileToggle || !sidebar || !backdrop) return;

    const openNav = () => {
        sidebar.classList.remove('-translate-x-full');
        sidebar.classList.add('translate-x-0');
        backdrop.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
        // Animate hamburger to X
        mobileToggle.classList.add('is-active');
        mobileToggle.setAttribute('aria-expanded', 'true');
        mobileToggle.setAttribute('aria-label', 'Close navigation');
    };
    const closeNav = () => {
        sidebar.classList.remove('translate-x-0');
        sidebar.classList.add('-translate-x-full');
        backdrop.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
        // Reset hamburger
        mobileToggle.classList.remove('is-active');
        mobileToggle.setAttribute('aria-expanded', 'false');
        mobileToggle.setAttribute('aria-label', 'Open navigation');
    };

    mobileToggle.addEventListener('click', (e) => {
        e.preventDefault();
        // Toggle open/close for convenience
        const isOpen = sidebar.classList.contains('translate-x-0');
        if (isOpen) closeNav(); else openNav();
    });
    backdrop.addEventListener('click', closeNav);

    // Auto-close when a nav item is selected (mobile)
    Object.values(navItems).forEach(n => {
        if (!n) return;
        n.addEventListener('click', () => {
            if (!sidebar.classList.contains('hidden')) closeNav();
        });
    });
}

function switchSection(sectionKey) {
    // Hide all sections
    Object.values(sections).forEach(el => {
        if (el) el.classList.add('hidden');
    });

    // Show target section
    if (sections[sectionKey]) {
        sections[sectionKey].classList.remove('hidden');
    }

    // Update Nav UI Logic
    // Reset all nav items
    Object.values(navItems).forEach(el => el.classList.remove('active', 'bg-blue-600/10', 'text-blue-400', 'border-l-2', 'border-blue-400'));

    // Activate current if exists in nav
    if (navItems[sectionKey]) {
        navItems[sectionKey].classList.add('active');
    }

    // Ensure new section starts at top in the scroll container
    try {
        if (mainEl) {
            // Using scrollTo with behavior auto to avoid jank on iOS toolbars
            mainEl.scrollTo({ top: 0, behavior: 'auto' });
        } else {
            window.scrollTo({ top: 0, behavior: 'auto' });
        }
    } catch (e) { /* noop */ }
}


function resetApp() {
    if (configForm) configForm.reset();
    clearErrors();

    // Reset Navigation is now Back to Welcome
    switchSection('welcome');

    // Lock Navs
    // Keep the Welcome nav enabled so the main Get Started entry remains usable.
    Object.keys(navItems).forEach(key => {
        if (key !== 'login' && key !== 'welcome') navItems[key].classList.add('disabled');
    });
    // Actually, we should probably disable 'login' too until they choose New/Existing User?
    // But our nav click logic handles that. If we are at 'welcome', the sidebar is visible but inactive.

    // Reset Stremio State

    setStremioLoggedOutState();

    // Reset catalogs
    catalogs = JSON.parse(JSON.stringify(defaultCatalogs));
    renderCatalogList();

    // Show Form
    if (configForm) configForm.classList.remove('hidden');
    if (sections.success) sections.success.classList.add('hidden');
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
            resetApp();
            return;
        }

        // Remove query param
        const newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }

    if (stremioLoginBtn) {
        stremioLoginBtn.addEventListener('click', () => {
            if (stremioLoginBtn.getAttribute('data-action') === 'logout') {
                resetApp(); // Logout effectively resets the app flow
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
                s.catalogs.forEach(remote => {
                    const local = catalogs.find(c => c.id === remote.id);
                    if (local) {
                        local.enabled = remote.enabled;
                        if (remote.name) local.name = remote.name;
                        if (typeof remote.min_items === 'number') local.minItems = remote.min_items;
                        if (typeof remote.max_items === 'number') local.maxItems = remote.max_items;
                        if (typeof remote.enabled_movie === 'boolean') local.enabledMovie = remote.enabled_movie;
                        if (typeof remote.enabled_series === 'boolean') local.enabledSeries = remote.enabled_series;
                    }
                });
                renderCatalogList();
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
        clearErrors();
        showEmailPwdError('');
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

function setStremioLoggedInState(authKey) {
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

function setStremioLoggedOutState() {
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


// --- Form Submission ---
async function initializeFormSubmission() {
    if (!submitBtn) return;

    submitBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        clearErrors();

        const sAuthKey = (document.getElementById("authKey").value || '').trim();
        const email = emailInput?.value.trim();
        const password = passwordInput?.value;
        const language = languageSelect.value;
        const rpdbKey = document.getElementById("rpdbKey").value.trim();
        const excludedMovieGenres = Array.from(document.querySelectorAll('input[name="movie-genre"]:checked')).map(cb => cb.value);
        const excludedSeriesGenres = Array.from(document.querySelectorAll('input[name="series-genre"]:checked')).map(cb => cb.value);

        const catalogsToSend = [];
        document.querySelectorAll(".catalog-item .switch input[type='checkbox']").forEach(toggle => {
            const catalogId = toggle.dataset.catalogId;
            const enabled = toggle.checked;
            const originalCatalog = catalogs.find(c => c.id === catalogId);
            if (originalCatalog) {
                let minV = parseInt(originalCatalog.minItems ?? 20, 10);
                let maxV = parseInt(originalCatalog.maxItems ?? 24, 10);
                if (Number.isNaN(minV)) minV = 20;
                if (Number.isNaN(maxV)) maxV = 24;
                // Enforce server policy: min <= 20, max <= 32, and max >= min
                minV = Math.max(1, Math.min(20, minV));
                maxV = Math.max(minV, Math.min(32, maxV));

                // Get enabled_movie and enabled_series from toggle buttons
                const activeBtn = document.querySelector(`.catalog-type-btn[data-catalog-id="${catalogId}"].bg-white`);
                let enabledMovie = true;
                let enabledSeries = true;

                if (activeBtn) {
                    const mode = activeBtn.dataset.mode;
                    if (mode === 'movie') {
                        enabledMovie = true;
                        enabledSeries = false;
                    } else if (mode === 'series') {
                        enabledMovie = false;
                        enabledSeries = true;
                    } else {
                        // 'both' or default
                        enabledMovie = true;
                        enabledSeries = true;
                    }
                } else {
                    // Fallback to catalog state
                    enabledMovie = originalCatalog.enabledMovie !== false;
                    enabledSeries = originalCatalog.enabledSeries !== false;
                }

                catalogsToSend.push({
                    id: catalogId,
                    name: originalCatalog.name,
                    enabled: enabled,
                    enabled_movie: enabledMovie,
                    enabled_series: enabledSeries,
                    min_items: minV,
                    max_items: maxV,
                });
            }
        });

        // Validation
        if (!sAuthKey && !(email && password)) {
            showError("generalError", "Please login with Stremio or enter email & password.");
            switchSection('login');
            return;
        }

        setLoading(true);

        try {
            const payload = {
                authKey: sAuthKey || undefined,
                email: email || undefined,
                password: password || undefined,
                catalogs: catalogsToSend,
                language: language,
                rpdb_key: rpdbKey,
                excluded_movie_genres: excludedMovieGenres,
                excluded_series_genres: excludedSeriesGenres
            };

            const response = await fetch("/tokens/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Failed to generate manifest URL");
            }
            const data = await response.json();
            showSuccess(data.manifestUrl);
        } catch (error) {
            console.error("Error:", error);
            showError("generalError", error.message);
        } finally {
            setLoading(false);
        }
    });
}


// UI Helpers & Genre Lists
function initializeGenreLists() {
    renderGenreList(movieGenreList, MOVIE_GENRES, 'movie-genre');
    renderGenreList(seriesGenreList, SERIES_GENRES, 'series-genre');
}

function renderGenreList(container, genres, namePrefix) {
    if (!container) return;
    container.innerHTML = genres.map(genre => `
        <label class="flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 cursor-pointer transition group">
            <div class="relative flex items-center">
                <input type="checkbox" name="${namePrefix}" value="${genre.id}"
                    class="peer appearance-none w-5 h-5 border-2 border-slate-600 rounded bg-slate-900 checked:bg-white checked:border-white transition-colors">
                <svg class="absolute w-3.5 h-3.5 text-black left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 peer-checked:opacity-100 pointer-events-none transition-opacity"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
            </div>
            <span class="text-sm text-slate-300 group-hover:text-white transition-colors select-none">${genre.name}</span>
        </label>
    `).join('');
}

// Language Selection
async function initializeLanguageSelect() {
    if (!languageSelect) return;
    try {
        const languagesResponse = await fetch('/api/languages');
        if (!languagesResponse.ok) throw new Error('Failed to fetch languages');
        const languages = await languagesResponse.json();
        languages.sort((a, b) => {
            if (a.iso_639_1 === 'en-US') return -1;
            if (b.iso_639_1 === 'en-US') return 1;
            return a.language.localeCompare(b.language);
        });
        languageSelect.innerHTML = languages.map(lang => {
            const code = lang.iso_639_1;
            const fullLabel = escapeHtml(lang.language) + ' (' + escapeHtml(lang.country) + ')';
            return '<option value="' + escapeHtml(code) + '"' + (code === 'en-US' ? ' selected' : '') + '>' + fullLabel + '</option>';
        }).join('');
    } catch (err) {
        languageSelect.innerHTML = '<option value="en-US">English (US)</option>';
    }
}

// Password Toggles
function initializePasswordToggles() {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (!input) return;
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            // Swap icon and labels
            if (isHidden) {
                // Now visible: show eye-off icon
                btn.setAttribute('title', 'Hide');
                btn.setAttribute('aria-label', 'Hide password');
                btn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a21.77 21.77 0 0 1 5.06-6.17M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a21.8 21.8 0 0 1-3.22 4.31"/><path d="M1 1l22 22"/><path d="M14.12 14.12A3 3 0 0 1 9.88 9.88"/></svg>';
            } else {
                // Now hidden: show eye icon
                btn.setAttribute('title', 'Show');
                btn.setAttribute('aria-label', 'Show password');
                btn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';
            }
        });
    });
}

// Catalog Management
function initializeCatalogList() { renderCatalogList(); }

function renderCatalogList() {
    if (!catalogList) return;
    catalogList.innerHTML = '';
    catalogs.forEach((cat, index) => {
        const item = createCatalogItem(cat, index);
        catalogList.appendChild(item);
    });
}

function moveCatalogUp(index) {
    if (index === 0) return;
    [catalogs[index], catalogs[index - 1]] = [catalogs[index - 1], catalogs[index]];
    renderCatalogList();
}

function moveCatalogDown(index) {
    if (index === catalogs.length - 1) return;
    [catalogs[index], catalogs[index + 1]] = [catalogs[index + 1], catalogs[index]];
    renderCatalogList();
}

function createCatalogItem(cat, index) {
    const item = document.createElement('div');
    const disabledClass = !cat.enabled ? 'opacity-50' : '';
    // Modern neutral glass card to match new theme
    item.className = `catalog-item group bg-neutral-900/60 border border-white/10 rounded-xl p-4 backdrop-blur-sm transition-all hover:border-white/20 hover:bg-neutral-900/70 hover:shadow-lg hover:shadow-black/20 ${disabledClass}`;
    item.setAttribute('data-id', cat.id);
    item.setAttribute('data-index', index);

    const isRenamable = cat.id !== 'watchly.theme';

    // Determine active mode for toggle buttons
    const enabledMovie = cat.enabledMovie !== false;
    const enabledSeries = cat.enabledSeries !== false;
    let activeMode = 'both';
    if (enabledMovie && !enabledSeries) activeMode = 'movie';
    else if (!enabledMovie && enabledSeries) activeMode = 'series';
    item.innerHTML = `
        <div class="flex items-start gap-3 sm:items-center sm:gap-4">
            <div class="sort-buttons flex flex-col gap-1 flex-shrink-0 mt-0.5 sm:mt-0">
                <button type="button" class="action-btn move-up p-1 text-slate-500 hover:text-white hover:bg-white/10 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
                </button>
                <button type="button" class="action-btn move-down p-1 text-slate-500 hover:text-white hover:bg-white/10 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
                </button>
            </div>
            <div class="flex-grow min-w-0 space-y-1 sm:space-y-0 sm:flex sm:items-center sm:gap-4">
                <div class="name-container relative flex items-center min-w-0 h-auto sm:h-9 flex-grow">
                    <span class="catalog-name-text font-medium text-white break-words leading-snug sm:truncate cursor-default w-full">${escapeHtml(cat.name)}</span>
                    <input type="text" class="catalog-name-input hidden absolute inset-0 w-full bg-neutral-950 border border-white/20 rounded-lg px-3 text-white outline-none text-sm font-medium shadow-sm font-mono focus:ring-2 focus:ring-white/20 focus:border-white/30" value="${escapeHtml(cat.name)}">
                    ${isRenamable ? `<button type="button" class="action-btn rename-btn ml-2 p-1.5 flex-shrink-0 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100" title="Rename"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>` : ''}
                </div>
                <div class="catalog-desc sm:hidden text-xs text-slate-500 leading-relaxed">${escapeHtml(cat.description || '')}</div>
            </div>
            <label class="switch relative inline-flex items-center cursor-pointer flex-shrink-0 ml-auto sm:ml-0">
                <input type="checkbox" class="sr-only peer" ${cat.enabled ? 'checked' : ''} data-catalog-id="${cat.id}">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-white/20 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-white peer-checked:after:bg-black peer-checked:after:border-black"></div>
            </label>
        </div>
        <div class="catalog-desc hidden sm:block text-xs text-slate-500 mt-2 ml-8 pl-1">${escapeHtml(cat.description || '')}</div>
        <div class="mt-3 ml-8">
            <div class="inline-flex items-center bg-neutral-950 border border-white/10 rounded-lg p-1" role="group" aria-label="Content type selection">
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'both' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="both">
                    Both
                </button>
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'movie' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="movie">
                    Movie
                </button>
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'series' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="series">
                    Series
                </button>
            </div>
        </div>
    `;

    if (isRenamable) setupRenameLogic(item, cat);

    const switchInput = item.querySelector('.switch input');
    switchInput.addEventListener('change', (e) => {
        cat.enabled = e.target.checked;
        if (cat.enabled) item.classList.remove('opacity-50');
        else item.classList.add('opacity-50');
    });

    // Handle movie/series toggle button changes
    const allTypeButtons = item.querySelectorAll(`.catalog-type-btn[data-catalog-id="${cat.id}"]`);

    allTypeButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const mode = e.target.dataset.mode;

            // Update state
            if (mode === 'both') {
                cat.enabledMovie = true;
                cat.enabledSeries = true;
            } else if (mode === 'movie') {
                cat.enabledMovie = true;
                cat.enabledSeries = false;
            } else if (mode === 'series') {
                cat.enabledMovie = false;
                cat.enabledSeries = true;
            }

            // Update UI
            allTypeButtons.forEach(b => {
                b.classList.remove('bg-white', 'text-black', 'shadow-sm', 'hover:text-black');
                b.classList.add('text-slate-400', 'hover:text-white');
            });
            e.target.classList.remove('text-slate-400', 'hover:text-white');
            e.target.classList.add('bg-white', 'text-black', 'shadow-sm', 'hover:text-black');
        });
    });

    item.querySelector('.move-up').addEventListener('click', (e) => { e.preventDefault(); moveCatalogUp(index); });
    item.querySelector('.move-down').addEventListener('click', (e) => { e.preventDefault(); moveCatalogDown(index); });

    return item;
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');

    const editActions = document.createElement('div');
    editActions.className = 'edit-actions hidden absolute right-1 top-1/2 -translate-y-1/2 flex gap-1 bg-slate-900 pl-2 z-10';
    editActions.innerHTML = `
        <button type="button" class="edit-btn save p-1 text-green-500 hover:bg-green-500/10 rounded transition" title="Save"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>
        <button type="button" class="edit-btn cancel p-1 text-red-500 hover:bg-red-500/10 rounded transition" title="Cancel"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
    `;
    nameContainer.appendChild(editActions);

    const saveBtn = editActions.querySelector('.save');
    const cancelBtn = editActions.querySelector('.cancel');

    function enableEdit() {
        nameContainer.classList.add('editing');
        nameText.classList.add('hidden');
        nameInput.classList.remove('hidden');
        editActions.classList.remove('hidden'); editActions.classList.add('flex');
        if (renameBtn) renameBtn.classList.add('invisible');
        nameInput.focus();
    }
    function saveEdit() {
        const newName = nameInput.value.trim();
        if (newName) { cat.name = newName; nameText.textContent = newName; nameInput.value = newName; }
        else { nameInput.value = cat.name; }
        closeEdit();
    }
    function cancelEdit() { nameInput.value = cat.name; closeEdit(); }
    function closeEdit() {
        nameContainer.classList.remove('editing');
        nameInput.classList.add('hidden');
        editActions.classList.add('hidden'); editActions.classList.remove('flex');
        nameText.classList.remove('hidden');
        if (renameBtn) renameBtn.classList.remove('invisible');
    }
    if (renameBtn) renameBtn.addEventListener('click', (e) => { e.preventDefault(); enableEdit(); });
    saveBtn.addEventListener('click', (e) => { e.preventDefault(); saveEdit(); });
    cancelBtn.addEventListener('click', (e) => { e.preventDefault(); cancelEdit(); });
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); saveEdit(); }
        else if (e.key === 'Escape') { cancelEdit(); }
    });
}
// Delete & Success Helpers
function initializeSuccessActions() {
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
            const urlText = document.getElementById('addonUrl').textContent;
            try {
                await navigator.clipboard.writeText(urlText);
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = 'Copied!';
                setTimeout(() => { copyBtn.innerHTML = originalText; }, 2000);
            } catch (err) { }
        });
    }

    const installDesktopBtn = document.getElementById('installDesktopBtn');
    if (installDesktopBtn) {
        installDesktopBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.location.href = `stremio://${url.replace(/^https?:\/\//, '')}`;
        });
    }
    const installWebBtn = document.getElementById('installWebBtn');
    if (installWebBtn) {
        installWebBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.open(`https://web.stremio.com/#/addons?addon=${encodeURIComponent(url)}`, '_blank');
        });
    }

    if (deleteAccountBtn) {
        deleteAccountBtn.addEventListener('click', async () => {
            const confirmed = await showConfirm(
                'Delete Account?',
                'Are you sure you want to delete your settings? This action is irreversible and all your data will be permanently removed.'
            );

            if (!confirmed) return;

            const sAuthKey = (document.getElementById("authKey").value || '').trim();
            const email = emailInput?.value.trim();
            const password = passwordInput?.value;

            if (!sAuthKey && !(email && password)) {
                showError('generalError', "Provide Stremio auth key or email & password to delete your account.");
                switchSection('login');
                return;
            }

            setLoading(true);
            try {
                const payload = { authKey: sAuthKey || undefined, email: email || undefined, password: password || undefined };
                const res = await fetch('/tokens/', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                if (!res.ok) throw new Error((await res.json()).detail || 'Failed to delete');
                showToast('Account deleted successfully.', 'success');
                resetApp();
            } catch (e) {
                showError('generalError', e.message);
            } finally {
                setLoading(false);
            }
        });
    }
}

function setLoading(loading) {
    if (!submitBtn) return;
    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader');
    submitBtn.disabled = loading;
    if (loading) {
        if (btnText) btnText.classList.add('hidden');
        if (loader) loader.classList.remove('hidden');
    } else {
        if (btnText) btnText.classList.remove('hidden');
        if (loader) loader.classList.add('hidden');
    }
}

function showError(target, message) {
    if (target === 'generalError') {
        const errEl = document.getElementById('errorMessage');
        if (errEl) {
            errEl.querySelector('.message-content').textContent = message;
            errEl.classList.remove('hidden');
        } else { showToast(message, 'error'); }
    } else if (target === 'stremioAuthSection') {
        showToast(message, 'error');
    } else {
        const el = document.getElementById(target);
        if (el) {
            el.classList.add('border-red-500');
            el.focus();
        }
    }
}

function clearErrors() {
    const errEl = document.getElementById('errorMessage');
    if (errEl) errEl.classList.add('hidden');
    document.querySelectorAll('.border-red-500').forEach(e => e.classList.remove('border-red-500'));
}

function showSuccess(url) {
    // Hide form entirely by hiding the active section
    Object.values(sections).forEach(s => { if (s) s.classList.add('hidden') });

    // Show Success Section
    if (sections.success) {
        sections.success.classList.remove('hidden');
        document.getElementById('addonUrl').textContent = url;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toast Notification System
function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-notification transform translate-x-full opacity-0 transition-all duration-300 ease-out';

    // Icon and color based on type
    let icon, bgColor, borderColor, iconColor;
    switch (type) {
        case 'success':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>`;
            bgColor = 'bg-green-500/10';
            borderColor = 'border-green-500/30';
            iconColor = 'text-green-400';
            break;
        case 'error':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>`;
            bgColor = 'bg-red-500/10';
            borderColor = 'border-red-500/30';
            iconColor = 'text-red-400';
            break;
        case 'warning':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>`;
            bgColor = 'bg-yellow-500/10';
            borderColor = 'border-yellow-500/30';
            iconColor = 'text-yellow-400';
            break;
        default: // info
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>`;
            bgColor = 'bg-white/5';
            borderColor = 'border-white/10';
            iconColor = 'text-slate-200';
    }

    toast.innerHTML = `
        <div class="flex items-start gap-3 p-4 ${bgColor} border ${borderColor} rounded-xl backdrop-blur-xl shadow-lg">
            <div class="${iconColor} flex-shrink-0 mt-0.5">${icon}</div>
            <div class="flex-1 text-sm text-slate-200 leading-relaxed">${escapeHtml(message)}</div>
            <button class="toast-close flex-shrink-0 text-slate-400 hover:text-white transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        </div>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            toast.classList.remove('translate-x-full', 'opacity-0');
        });
    });

    // Close button
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => removeToast(toast));

    // Auto remove
    if (duration > 0) {
        setTimeout(() => removeToast(toast), duration);
    }
}

function removeToast(toast) {
    toast.classList.add('translate-x-full', 'opacity-0');
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

// Confirmation Modal System
function showConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        const modalContent = document.getElementById('confirmModalContent');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmModalConfirm');
        const cancelBtn = document.getElementById('confirmModalCancel');

        if (!modal || !modalContent) {
            // Fallback to native confirm if modal not found
            resolve(confirm(message));
            return;
        }

        // Set content
        titleEl.textContent = title;
        messageEl.textContent = message;

        // Show modal
        modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                modalContent.classList.remove('scale-95', 'opacity-0');
                modalContent.classList.add('scale-100', 'opacity-100');
            });
        });

        // Handle clicks
        const handleConfirm = () => {
            cleanup();
            resolve(true);
        };

        const handleCancel = () => {
            cleanup();
            resolve(false);
        };

        const handleBackdropClick = (e) => {
            if (e.target === modal) {
                handleCancel();
            }
        };

        const cleanup = () => {
            modalContent.classList.remove('scale-100', 'opacity-100');
            modalContent.classList.add('scale-95', 'opacity-0');
            setTimeout(() => {
                modal.classList.add('hidden');
            }, 200);

            confirmBtn.removeEventListener('click', handleConfirm);
            cancelBtn.removeEventListener('click', handleCancel);
            modal.removeEventListener('click', handleBackdropClick);
        };

        confirmBtn.addEventListener('click', handleConfirm);
        cancelBtn.addEventListener('click', handleCancel);
        modal.addEventListener('click', handleBackdropClick);
    });
}

function initializeFooter() {
    const y = document.getElementById('currentYear');
    if (y) y.textContent = new Date().getFullYear();
}


// Ko-fi Modal Logic
function initializeKofi() {
    const kofiBtn = document.getElementById('kofiBtn');
    const MEMOMO_URL = 'https://buymemomo.com/timilsinabimal';

    if (kofiBtn) kofiBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // Open BuyMeMoMo in a new tab and remove window.opener for safety
        const win = window.open(MEMOMO_URL, '_blank');
        try { if (win) win.opener = null; } catch (err) { /* ignore */ }
    });
}

// Announcement: fetch small message/HTML from API and render in the home hero
async function initializeAnnouncement() {
    const container = document.getElementById('announcement');
    const content = document.getElementById('announcement-content');
    if (!container || !content) return;

    try {
        const res = await fetch('/announcement');
        if (!res.ok) return;

        let data = null;
        try { data = await res.json(); } catch (e) { data = null; }

        let html = '';
        if (data) html = data.html || data.message || '';
        if (!html) {
            try { html = await res.text(); } catch (e) { html = ''; }
        }

        if (!html) return;

        content.innerHTML = html;
        container.classList.remove('hidden');
    } catch (e) {
        // silent
    }
}
