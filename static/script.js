// Default catalog configurations
const defaultCatalogs = [
    { id: 'watchly.rec', name: 'Top Picks for You', enabled: true, description: 'Personalized recommendations based on your library' },
    { id: 'watchly.item', name: 'Because you Loved/Watched', enabled: true, description: 'Recommendations based on content you interacted with' },
    { id: 'watchly.theme', name: 'Keyword Genre Based Dynamic Recommendations', enabled: true, description: 'Recommendations based on your favorite genres and themes' },
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
const languageSelect = document.getElementById('languageSelect');
const generateIdBtn = document.getElementById('generateIdBtn');
const watchlyUsername = document.getElementById('watchlyUsername');
const watchlyPassword = document.getElementById('watchlyPassword');
const toggleStremioManual = document.getElementById('toggleStremioManual');
const stremioManualFields = document.getElementById('stremioManualFields');
const manualContinueBtn = document.getElementById('manualContinueBtn');
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
    watchlyLogin: document.getElementById('sect-watchly-login'),
    login: document.getElementById('sect-login'),
    config: document.getElementById('sect-config'),
    catalogs: document.getElementById('sect-catalogs'),
    install: document.getElementById('sect-install'),
    success: document.getElementById('sect-success')
};

// Welcome & Watchly Login Elements
const btnNewUser = document.getElementById('btn-new-user');
const btnExistingUser = document.getElementById('btn-existing-user');
const btnWatchlyLoginSubmit = document.getElementById('btn-watchly-login-submit');
const backToWelcome = document.getElementById('back-to-welcome');
const existingWatchlyUser = document.getElementById('existing-watchly-user');
const existingWatchlyPass = document.getElementById('existing-watchly-pass');


// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Start at Welcome
    switchSection('welcome'); // ensure welcome is visible
    initializeWelcomeFlow();

    initializeNavigation();
    initializeCatalogList();
    initializeLanguageSelect();
    initializeGenreLists();
    initializeFormSubmission();
    initializeSuccessActions();
    initializePasswordToggles();
    initializeStremioLogin();
    initializeFooter();

    // Watchly ID Generator
    if (generateIdBtn && watchlyUsername) {
        generateIdBtn.addEventListener('click', () => {
            const randomId = 'user-' + Math.random().toString(36).substring(2, 9);
            watchlyUsername.value = randomId;
        });
    }

    // Manual Stremio Toggle
    if (toggleStremioManual && stremioManualFields) {
        toggleStremioManual.addEventListener('click', () => {
            stremioManualFields.classList.toggle('hidden');
            toggleStremioManual.textContent = stremioManualFields.classList.contains('hidden')
                ? "I prefer to enter credentials manually"
                : "Hide manual credentials";
        });
    }

    // Manual Continue Button
    if (manualContinueBtn) {
        manualContinueBtn.addEventListener('click', () => {
            const user = document.getElementById('username').value.trim();
            const pass = document.getElementById('password').value;
            const key = document.getElementById('authKey').value.trim();

            if ((user && pass) || key) {
                unlockNavigation();
                switchSection('config');
            } else {
                showError('stremioAuthSection', 'Please enter your credentials or auth key first.');
            }
        });
    }

    // Next Buttons
    if (configNextBtn) configNextBtn.addEventListener('click', () => switchSection('catalogs'));
    if (catalogsNextBtn) catalogsNextBtn.addEventListener('click', () => switchSection('install'));

    // Reset Buttons
    document.getElementById('resetBtn')?.addEventListener('click', resetApp);
    if (successResetBtn) successResetBtn.addEventListener('click', resetApp);
});


// Welcome Flow Logic
function initializeWelcomeFlow() {
    if (btnNewUser) {
        btnNewUser.addEventListener('click', () => {
            // NEW USER FLOW
            navItems.login.classList.remove('disabled'); // Unlock Login

            // Reset "Save & Install" UI to default (Create Mode)
            if (watchlyUsername) {
                watchlyUsername.value = '';
                watchlyUsername.removeAttribute('readonly');
                // watchlyUsername.classList.remove('opacity-50', 'cursor-not-allowed'); // optional styling
            }
            if (watchlyPassword) watchlyPassword.value = '';

            // Show Generate Button
            if (generateIdBtn) generateIdBtn.classList.remove('hidden');

            // Update Headers/Text
            const installHeader = document.querySelector('#sect-install h2');
            const installDesc = document.querySelector('#sect-install p');
            if (installHeader) installHeader.textContent = "Save & Install";
            if (installDesc) installDesc.textContent = "Create your Watchly account to secure your settings.";

            const btnText = document.querySelector('#submitBtn .btn-text');
            if (btnText) btnText.textContent = "Generate & Install";

            // Go to Stremio Step
            switchSection('login');
        });
    }

    if (btnExistingUser) {
        btnExistingUser.addEventListener('click', () => {
            switchSection('watchlyLogin');
            // Ensure sidebar is reset visually
            Object.values(navItems).forEach(el => el.classList.remove('active'));
        });
    }

    if (backToWelcome) {
        backToWelcome.addEventListener('click', () => {
            switchSection('welcome');
        });
    }

    if (btnWatchlyLoginSubmit) {
        btnWatchlyLoginSubmit.addEventListener('click', async () => {
            const wUser = existingWatchlyUser.value.trim();
            const wPass = existingWatchlyPass.value;

            if (!wUser || !wPass) {
                alert("Please enter your Watchly ID and Password.");
                return;
            }

            const originalText = btnWatchlyLoginSubmit.textContent;
            btnWatchlyLoginSubmit.textContent = "Verifying...";
            btnWatchlyLoginSubmit.disabled = true;

            try {
                const res = await fetch('/tokens/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ watchly_username: wUser, watchly_password: wPass })
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || "Account not found or invalid credentials.");
                }

                const data = await res.json();

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
                            }
                        });
                        renderCatalogList();
                    }
                }

                // EXISTING USER FLOW (Success)
                navItems.config.classList.remove('disabled');
                navItems.catalogs.classList.remove('disabled');
                navItems.install.classList.remove('disabled');

                // Hide Login Nav
                navItems.login.style.display = 'none';

                if (watchlyUsername) {
                    watchlyUsername.value = wUser;
                    watchlyUsername.setAttribute('readonly', 'true');
                }
                if (watchlyPassword) watchlyPassword.value = wPass;
                if (generateIdBtn) generateIdBtn.classList.add('hidden');

                const installHeader = document.querySelector('#sect-install h2');
                const installDesc = document.querySelector('#sect-install p');
                if (installHeader) installHeader.textContent = "Update Account";
                if (installDesc) installDesc.textContent = "Your settings will be updated for this account.";
                const btnText = document.querySelector('#submitBtn .btn-text');
                if (btnText) btnText.textContent = "Update & Re-Install";

                switchSection('config');

            } catch (error) {
                alert(error.message);
            } finally {
                btnWatchlyLoginSubmit.textContent = originalText;
                btnWatchlyLoginSubmit.disabled = false;
            }
        });
    }
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
}


function resetApp() {
    if (configForm) configForm.reset();
    clearErrors();

    // Reset Navigation is now Back to Welcome
    switchSection('welcome');

    // Lock Navs
    Object.keys(navItems).forEach(key => {
        if (key !== 'login') navItems[key].classList.add('disabled'); // Login is always enabled technically, but we hide it via switchSection('welcome')
    });
    // Actually, we should probably disable 'login' too until they choose New/Existing User?
    // But our nav click logic handles that. If we are at 'welcome', the sidebar is visible but inactive.

    // Reset Stremio State
    if (stremioManualFields) {
        stremioManualFields.classList.add('hidden');
        if (toggleStremioManual) toggleStremioManual.textContent = "I prefer to enter credentials manually";
    }
    setStremioLoggedOutState();

    // Reset catalogs
    catalogs = JSON.parse(JSON.stringify(defaultCatalogs));
    renderCatalogList();

    // Show Form
    if (configForm) configForm.classList.remove('hidden');
    if (sections.success) sections.success.classList.add('hidden');
}


// Stremio Login Logic
function initializeStremioLogin() {
    const urlParams = new URLSearchParams(window.location.search);
    const authKey = urlParams.get('key') || urlParams.get('authKey');

    if (authKey) {
        // Logged In -> Unlock and move to config
        setStremioLoggedInState(authKey);
        unlockNavigation();
        switchSection('config');

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

function setStremioLoggedInState(authKey) {
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Logout';
    stremioLoginBtn.setAttribute('data-action', 'logout');
    stremioLoginBtn.classList.remove('bg-stremio', 'hover:bg-stremio-hover');
    stremioLoginBtn.classList.add('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    // Hide manual fields
    if (stremioManualFields) stremioManualFields.classList.add('hidden');
    if (toggleStremioManual) toggleStremioManual.classList.add('hidden');

    // Pre-fill hidden AuthKey for submission
    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = authKey;
}

function setStremioLoggedOutState() {
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Login with Stremio';
    stremioLoginBtn.removeAttribute('data-action');
    stremioLoginBtn.classList.add('bg-stremio', 'hover:bg-stremio-hover');
    stremioLoginBtn.classList.remove('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    if (toggleStremioManual) toggleStremioManual.classList.remove('hidden');
    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = '';
}


// --- Form Submission ---
async function initializeFormSubmission() {
    if (!submitBtn) return;

    submitBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        clearErrors();

        const wUser = document.getElementById("watchlyUsername").value.trim();
        const wPass = document.getElementById("watchlyPassword").value;
        const sUser = document.getElementById("username").value.trim();
        const sPass = document.getElementById("password").value;
        const sAuthKey = document.getElementById("authKey").value.trim();
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
                catalogsToSend.push({
                    id: catalogId,
                    name: originalCatalog.name,
                    enabled: enabled
                });
            }
        });

        // Validation
        let isValid = true;
        if (!wUser) {
            showError("watchlyUsername", "Please create a Watchly ID.");
            isValid = false;
        }
        if (!wPass) {
            showError("watchlyPassword", "Please secure your account with a password.");
            isValid = false;
        }

        const hasStremioCreds = sAuthKey || (sUser && sPass);
        const isUpdateMode = watchlyUsername && watchlyUsername.hasAttribute('readonly');

        if (!hasStremioCreds && !isUpdateMode) {
            showError("generalError", "Stremio credentials are missing. Please go back to Step 1.");
            switchSection('login');
            isValid = false;
        }

        if (!isValid) return;

        setLoading(true);

        try {
            const payload = {
                watchly_username: wUser,
                watchly_password: wPass,
                username: sUser,
                password: sPass,
                authKey: sAuthKey,
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
        <label class="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-800/50 cursor-pointer transition group">
            <div class="relative flex items-center">
                <input type="checkbox" name="${namePrefix}" value="${genre.id}"
                    class="peer appearance-none w-5 h-5 border-2 border-slate-600 rounded bg-slate-900 checked:bg-blue-500 checked:border-blue-500 transition-colors">
                <svg class="absolute w-3.5 h-3.5 text-white left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 peer-checked:opacity-100 pointer-events-none transition-opacity"
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
            if (a.iso_639_1 === 'en') return -1;
            if (b.iso_639_1 === 'en') return 1;
            return a.english_name.localeCompare(b.english_name);
        });
        languageSelect.innerHTML = languages.map(lang => {
            const code = lang.iso_639_1;
            const label = lang.name ? lang.name : lang.english_name;
            const fullLabel = lang.name && lang.name !== lang.english_name ? `${lang.english_name} (${lang.name})` : lang.english_name;
            return `<option value="${code}" ${code === 'en' ? 'selected' : ''}>${fullLabel}</option>`;
        }).join('');
    } catch (err) {
        languageSelect.innerHTML = '<option value="en">English</option>';
    }
}

// Password Toggles
function initializePasswordToggles() {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (input) {
                input.type = input.type === 'password' ? 'text' : 'password';
                btn.textContent = input.type === 'password' ? 'Show' : 'Hide';
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
    item.className = `catalog-item group bg-slate-900 border border-slate-700 rounded-xl p-4 transition-all hover:border-slate-600 ${disabledClass}`;
    item.setAttribute('data-index', index);

    const isRenamable = cat.id === 'watchly.rec';
    item.innerHTML = `
        <div class="flex items-start gap-3 sm:items-center sm:gap-4">
            <div class="sort-buttons flex flex-col gap-1 flex-shrink-0 mt-0.5 sm:mt-0">
                <button type="button" class="action-btn move-up p-1 text-slate-500 hover:text-white hover:bg-slate-700 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
                </button>
                <button type="button" class="action-btn move-down p-1 text-slate-500 hover:text-white hover:bg-slate-700 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
                </button>
            </div>
            <div class="flex-grow min-w-0 space-y-1 sm:space-y-0 sm:flex sm:items-center sm:gap-4">
                <div class="name-container relative flex items-center min-w-0 h-auto sm:h-9 flex-grow">
                    <span class="catalog-name-text font-medium text-white break-words leading-snug sm:truncate cursor-default w-full">${escapeHtml(cat.name)}</span>
                    <input type="text" class="catalog-name-input hidden absolute inset-0 w-full bg-slate-950 border border-blue-500 rounded-lg px-3 text-white outline-none text-sm font-medium shadow-sm font-mono" value="${escapeHtml(cat.name)}">
                    ${isRenamable ? `<button type="button" class="action-btn rename-btn ml-2 p-1.5 flex-shrink-0 text-slate-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100" title="Rename"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>` : ''}
                </div>
                <div class="catalog-desc sm:hidden text-xs text-slate-500 leading-relaxed">${escapeHtml(cat.description || '')}</div>
            </div>
            <label class="switch relative inline-flex items-center cursor-pointer flex-shrink-0 ml-auto sm:ml-0">
                <input type="checkbox" class="sr-only peer" ${cat.enabled ? 'checked' : ''} data-catalog-id="${cat.id}">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
        </div>
        <div class="catalog-desc hidden sm:block text-xs text-slate-500 mt-2 ml-8 pl-1">${escapeHtml(cat.description || '')}</div>
    `;

    if (isRenamable) setupRenameLogic(item, cat);

    const switchInput = item.querySelector('.switch input');
    switchInput.addEventListener('change', (e) => {
        cat.enabled = e.target.checked;
        if (cat.enabled) item.classList.remove('opacity-50');
        else item.classList.add('opacity-50');
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
            if (!confirm('Are you sure you want to delete your settings? This is irreversible.')) return;
            const wUser = document.getElementById("watchlyUsername").value.trim();
            const wPass = document.getElementById("watchlyPassword").value;
            const sUser = document.getElementById("username").value.trim();
            const sPass = document.getElementById("password").value;
            const sAuthKey = document.getElementById("authKey").value.trim();

            if (!sAuthKey && (!sUser || !sPass) && (!wUser || !wPass)) {
                showError('generalError', "We can't identify the account to delete. Please login or provide keys.");
                return;
            }

            setLoading(true);
            try {
                const payload = {
                    watchly_username: wUser, watchly_password: wPass,
                    username: sUser, password: sPass, authKey: sAuthKey
                };
                const res = await fetch('/tokens/', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                if (!res.ok) throw new Error((await res.json()).detail || 'Failed to delete');
                alert('Account deleted.');
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
        } else { alert(message); }
    } else if (target === 'stremioAuthSection') {
        // Fallback since we don't have a specific error div anymore
        alert(message);
        // Or highlight fields
        document.getElementById('stremioManualFields').classList.remove('hidden');
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

function initializeFooter() {
    const y = document.getElementById('currentYear');
    if (y) y.textContent = new Date().getFullYear();
}
