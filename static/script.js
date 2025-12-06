// Default catalog configurations
const defaultCatalogs = [
    { id: 'watchly.rec', name: 'Top Picks for You', enabled: true, description: 'Personalized recommendations based on your library' },
    { id: 'watchly.item', name: 'Because you Loved/Watched', enabled: true, description: 'Recommendations based on content you interacted with' },
    { id: 'watchly.theme', name: 'Keyword Genre Based Dynamic Recommendations', enabled: true, description: 'Recommendations based on your favorite genres and themes' },
];

let catalogs = JSON.parse(JSON.stringify(defaultCatalogs));

// Genre Constants (TMDB)
const MOVIE_GENRES = [
    { id: '28', name: 'Action' },
    { id: '12', name: 'Adventure' },
    { id: '16', name: 'Animation' },
    { id: '35', name: 'Comedy' },
    { id: '80', name: 'Crime' },
    { id: '99', name: 'Documentary' },
    { id: '18', name: 'Drama' },
    { id: '10751', name: 'Family' },
    { id: '14', name: 'Fantasy' },
    { id: '36', name: 'History' },
    { id: '27', name: 'Horror' },
    { id: '10402', name: 'Music' },
    { id: '9648', name: 'Mystery' },
    { id: '10749', name: 'Romance' },
    { id: '878', name: 'Science Fiction' },
    { id: '10770', name: 'TV Movie' },
    { id: '53', name: 'Thriller' },
    { id: '10752', name: 'War' },
    { id: '37', name: 'Western' }
];

const SERIES_GENRES = [
    { id: '10759', name: 'Action & Adventure' },
    { id: '16', name: 'Animation' },
    { id: '35', name: 'Comedy' },
    { id: '80', name: 'Crime' },
    { id: '99', name: 'Documentary' },
    { id: '18', name: 'Drama' },
    { id: '10751', name: 'Family' },
    { id: '10762', name: 'Kids' },
    { id: '9648', name: 'Mystery' },
    { id: '10763', name: 'News' },
    { id: '10764', name: 'Reality' },
    { id: '10765', name: 'Sci-Fi & Fantasy' },
    { id: '10766', name: 'Soap' },
    { id: '10767', name: 'Talk' },
    { id: '10768', name: 'War & Politics' },
    { id: '37', name: 'Western' }
];

// DOM Elements
const configForm = document.getElementById('configForm');
const authMethod = document.getElementById('authMethod');
const credentialsFields = document.getElementById('credentialsFields');
const authKeyField = document.getElementById('authKeyField');
const catalogList = document.getElementById('catalogList');
const movieGenreList = document.getElementById('movieGenreList');
const seriesGenreList = document.getElementById('seriesGenreList');
const errorMessage = document.getElementById('errorMessage');
const successMessage = document.getElementById('successMessage');
const submitBtn = document.getElementById('submitBtn');
const btnText = submitBtn.querySelector('.btn-text');
const loader = submitBtn.querySelector('.loader');
const stremioLoginBtn = document.getElementById('stremioLoginBtn');
const stremioLoginText = document.getElementById('stremioLoginText');
const manualAuthContainer = document.getElementById('manualAuthContainer');
const orDivider = document.getElementById('orDivider');
const languageSelect = document.getElementById('languageSelect');
const rpdbKeyInput = document.getElementById('rpdbKey');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initializeAuthMethodToggle();
    initializeCatalogList();
    initializeLanguageSelect();
    initializeGenreLists();
    initializeFormSubmission();
    initializeSuccessActions();
    initializePasswordToggles();
    initializeAuthHelp();
    initializeStremioLogin();
    initializeFooter();
});

// Genre Lists
function initializeGenreLists() {
    renderGenreList(movieGenreList, MOVIE_GENRES, 'movie-genre');
    renderGenreList(seriesGenreList, SERIES_GENRES, 'series-genre');
}

function renderGenreList(container, genres, namePrefix) {
    container.innerHTML = genres.map(genre => `
        <label class="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-700/50 cursor-pointer transition group">
            <div class="relative flex items-center">
                <input type="checkbox" name="${namePrefix}" value="${genre.id}"
                    class="peer appearance-none w-5 h-5 border-2 border-slate-600 rounded bg-slate-800 checked:bg-blue-500 checked:border-blue-500 transition-colors">
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
    try {

        const languagesResponse = await fetch('/api/languages');
        if (!languagesResponse.ok) throw new Error('Failed to fetch languages');

        const languages = await languagesResponse.json();

        // Sort: English first, then alphabetical by English name
        languages.sort((a, b) => {
            if (a.iso_639_1 === 'en') return -1;
            if (b.iso_639_1 === 'en') return 1;
            return a.english_name.localeCompare(b.english_name);
        });

        languageSelect.innerHTML = languages.map(lang => {
            const code = lang.iso_639_1;
            // Construct label: "English (US)" or just "English" if name is empty?
            // The example showed "name": "" for Bislama.
            const label = lang.name ? lang.name : lang.english_name;
            const fullLabel = lang.name && lang.name !== lang.english_name
                ? `${lang.english_name} (${lang.name})`
                : lang.english_name;

            return `<option value="${code}" ${code === 'en' ? 'selected' : ''}>${fullLabel}</option>`;
        }).join('');

    } catch (err) {
        console.error('Failed to load languages:', err);
        // Fallback
        languageSelect.innerHTML = '<option value="en">English</option>';
    }
}

// Stremio Login Logic
function initializeStremioLogin() {
    // Check for auth key in URL (from callback)
    const urlParams = new URLSearchParams(window.location.search);
    const authKey = urlParams.get('key') || urlParams.get('authKey');

    if (authKey) {
        // Logged in state
        setStremioLoggedInState(authKey);

        // Remove query param from URL without reload
        const newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: newUrl }, '', newUrl);
    }

    // Handle login button click
    if (stremioLoginBtn) {
        stremioLoginBtn.addEventListener('click', () => {
            if (stremioLoginBtn.getAttribute('data-action') === 'logout') {
                // Handle Logout
                setStremioLoggedOutState();
            } else {
                // Handle Login
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
    // 1. Update button to Logout
    stremioLoginText.textContent = 'Logout from Stremio';
    stremioLoginBtn.setAttribute('data-action', 'logout');
    stremioLoginBtn.classList.remove('bg-stremio', 'hover:bg-stremio-hover');
    stremioLoginBtn.classList.add('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    // 2. Disable and hide manual fields
    if (orDivider) orDivider.classList.add('hidden');
    if (manualAuthContainer) manualAuthContainer.classList.add('hidden');
    credentialsFields.classList.add('hidden');
    authKeyField.classList.add('hidden');

    // 3. Set hidden values for submission
    // We secretly switch to 'authkey' mode and fill the hidden field
    authMethod.value = 'authkey';
    // We don't dispatch 'change' because we don't want to show the authKeyField UI
    document.getElementById('authKey').value = authKey;
}

function setStremioLoggedOutState() {
    // 1. Reset button to Login
    stremioLoginText.textContent = 'Login with Stremio';
    stremioLoginBtn.removeAttribute('data-action');
    stremioLoginBtn.classList.add('bg-stremio', 'hover:bg-stremio-hover');
    stremioLoginBtn.classList.remove('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    // 2. Re-enable manual fields
    if (orDivider) orDivider.classList.remove('hidden');
    if (manualAuthContainer) manualAuthContainer.classList.remove('hidden');

    // Reset to default view (credentials)
    authMethod.value = 'credentials';
    credentialsFields.classList.remove('hidden');
    authKeyField.classList.add('hidden');

    // Clear values
    document.getElementById('authKey').value = '';
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
}

// Auth Method Toggle
function initializeAuthMethodToggle() {
    authMethod.addEventListener('change', (e) => {
        if (e.target.value === 'credentials') {
            credentialsFields.classList.remove('hidden');
            authKeyField.classList.add('hidden');
        } else {
            credentialsFields.classList.add('hidden');
            authKeyField.classList.remove('hidden');
        }
    });
}

// Password Toggles
function initializePasswordToggles() {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (input.type === 'password') {
                input.type = 'text';
                btn.textContent = 'Hide';
            } else {
                input.type = 'password';
                btn.textContent = 'Show';
            }
        });
    });
}

// Auth Help
function initializeAuthHelp() {
    const showAuthHelp = document.getElementById('showAuthHelp');
    if (showAuthHelp) {
        showAuthHelp.addEventListener('click', (e) => {
            e.preventDefault();
            alert('To find your Stremio Auth Key:\n\n1. Open web.strem.io in your browser\n2. Open Developer Tools (F12)\n3. Go to Application/Storage tab\n4. Click on Local Storage\n5. Find the "authKey" entry\n6. Copy the long string value');
        });
    }
}

// Catalog List
function initializeCatalogList() {
    renderCatalogList();
}

function renderCatalogList() {
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
    // Tailwind classes for the item container
    const disabledClass = !cat.enabled ? 'opacity-50' : '';
    item.className = `catalog-item group bg-slate-800 border border-slate-700 rounded-xl p-4 transition-all hover:border-slate-600 ${disabledClass}`;
    item.setAttribute('data-index', index);

    // Show rename button only for the first catalog (Recommended) or all?
    // User asked: "give option to rename recommended catalog"
    const isRenamable = cat.id === 'watchly.rec';

    item.innerHTML = `
        <div class="flex items-start gap-3 sm:items-center sm:gap-4">
            <!-- Sort Buttons -->
            <div class="sort-buttons flex flex-col gap-1 flex-shrink-0 mt-0.5 sm:mt-0">
                <button type="button" class="action-btn move-up p-1 text-slate-500 hover:text-white hover:bg-slate-700 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M18 15l-6-6-6 6"/>
                    </svg>
                </button>
                <button type="button" class="action-btn move-down p-1 text-slate-500 hover:text-white hover:bg-slate-700 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                </button>
            </div>

            <!-- Content Area -->
            <div class="flex-grow min-w-0 space-y-1 sm:space-y-0 sm:flex sm:items-center sm:gap-4">
                <!-- Name & Rename -->
                <div class="name-container relative flex items-center min-w-0 h-auto sm:h-9 flex-grow">
                    <span class="catalog-name-text font-medium text-white break-words leading-snug sm:truncate cursor-default w-full">${escapeHtml(cat.name)}</span>
                    <input
                        type="text"
                        class="catalog-name-input hidden absolute inset-0 w-full bg-slate-900 border border-blue-500 rounded-lg px-3 text-white outline-none text-sm font-medium shadow-sm"
                        value="${escapeHtml(cat.name)}"
                    >
                    ${isRenamable ? `
                    <button type="button" class="action-btn rename-btn ml-2 p-1.5 flex-shrink-0 text-slate-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100" title="Rename">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </button>
                    ` : ''}
                </div>

                <!-- Description Mobile (Hidden on Desktop to maintain layout if preferred, or show below) -->
                <div class="catalog-desc sm:hidden text-xs text-slate-500 leading-relaxed">${escapeHtml(cat.description || '')}</div>
            </div>

            <!-- Toggle Switch -->
            <label class="switch relative inline-flex items-center cursor-pointer flex-shrink-0 ml-auto sm:ml-0">
                <input type="checkbox" class="sr-only peer" ${cat.enabled ? 'checked' : ''} data-catalog-id="${cat.id}">
                <div class="w-11 h-6 bg-slate-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-800 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
        </div>
        <!-- Description Desktop -->
        <div class="catalog-desc hidden sm:block text-xs text-slate-500 mt-2 ml-8 pl-1">${escapeHtml(cat.description || '')}</div>
    `;

    if (isRenamable) {
        setupRenameLogic(item, cat);
    }

    // Setup switch toggle
    const switchInput = item.querySelector('.switch input');
    switchInput.addEventListener('change', (e) => {
        cat.enabled = e.target.checked;
        // Update disabled styling
        if (cat.enabled) {
            item.classList.remove('opacity-50');
        } else {
            item.classList.add('opacity-50');
        }
    });

    // Setup sort buttons
    const moveUpBtn = item.querySelector('.move-up');
    const moveDownBtn = item.querySelector('.move-down');

    moveUpBtn.addEventListener('click', (e) => {
        e.preventDefault();
        moveCatalogUp(index);
    });

    moveDownBtn.addEventListener('click', (e) => {
        e.preventDefault();
        moveCatalogDown(index);
    });

    return item;
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');

    // Create edit action buttons dynamically (Tailwind styled)
    const editActions = document.createElement('div');
    editActions.className = 'edit-actions hidden absolute right-1 top-1/2 -translate-y-1/2 flex gap-1 bg-slate-900 pl-2 z-10'; // hidden by default
    editActions.innerHTML = `
        <button type="button" class="edit-btn save p-1 text-green-500 hover:bg-green-500/10 rounded transition" title="Save">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </button>
        <button type="button" class="edit-btn cancel p-1 text-red-500 hover:bg-red-500/10 rounded transition" title="Cancel">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
    `;
    nameContainer.appendChild(editActions);

    const saveBtn = editActions.querySelector('.save');
    const cancelBtn = editActions.querySelector('.cancel');

    function enableEdit() {
        nameContainer.classList.add('editing');
        nameText.classList.add('hidden');
        nameInput.classList.remove('hidden');
        editActions.classList.remove('hidden'); // Show actions
        editActions.classList.add('flex');
        renameBtn.classList.add('invisible');
        nameInput.focus();
        const len = nameInput.value.length;
        nameInput.setSelectionRange(len, len);
    }

    function saveEdit() {
        const newName = nameInput.value.trim();
        if (newName) {
            cat.name = newName;
            nameText.textContent = newName;
            nameInput.value = newName;
        } else {
            nameInput.value = cat.name; // Revert if empty
        }
        closeEdit();
    }

    function cancelEdit() {
        nameInput.value = cat.name; // Revert value
        closeEdit();
    }

    function closeEdit() {
        nameContainer.classList.remove('editing');
        nameInput.classList.add('hidden');
        editActions.classList.add('hidden');
        editActions.classList.remove('flex');
        nameText.classList.remove('hidden');
        renameBtn.classList.remove('invisible');
    }

    renameBtn.addEventListener('click', (e) => {
        e.preventDefault();
        enableEdit();
    });

    saveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        saveEdit();
    });

    cancelBtn.addEventListener('click', (e) => {
        e.preventDefault();
        cancelEdit();
    });

    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveEdit();
        } else if (e.key === 'Escape') {
            cancelEdit();
        }
    });
}

// Form Submission
function initializeFormSubmission() {
    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const authMethodValue = authMethod.value;
        const username = document.getElementById('username')?.value.trim();
        const password = document.getElementById('password')?.value;
        const authKey = document.getElementById('authKey')?.value.trim();
        const language = document.getElementById('languageSelect').value;
        const rpdbKey = document.getElementById('rpdbKey').value.trim();

        // Get excluded genres
        const excludedMovieGenres = Array.from(document.querySelectorAll('input[name="movie-genre"]:checked')).map(cb => cb.value);
        const excludedSeriesGenres = Array.from(document.querySelectorAll('input[name="series-genre"]:checked')).map(cb => cb.value);

        // Validation
        if (authMethodValue === 'credentials') {
            if (!username || !password) {
                showError('Please provide both email and password.');
                return;
            }
        } else {
            if (!authKey) {
                showError('Please provide your Stremio auth key.');
                return;
            }
        }

        // Prepare catalog configs
        const catalogConfigs = catalogs.map(cat => ({
            id: cat.id,
            name: cat.name,
            enabled: cat.enabled
        }));

        // Prepare payload
        const payload = {
            catalogs: catalogConfigs,
            language: language,
            rpdb_key: rpdbKey || null,
            excluded_movie_genres: excludedMovieGenres,
            excluded_series_genres: excludedSeriesGenres
        };

        if (authMethodValue === 'credentials') {
            payload.username = username;
            payload.password = password;
        } else {
            payload.authKey = authKey;
        }

        // Submit
        setLoading(true);
        hideError();

        try {
            const response = await fetch('/tokens/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to create token');
            }

            showSuccess(data.manifestUrl);
        } catch (error) {
            showError(error.message || 'An error occurred. Please try again.');
        } finally {
            setLoading(false);
        }
    });
}


// Success Actions
function initializeSuccessActions() {
    const installDesktopBtn = document.getElementById('installDesktopBtn');
    const installWebBtn = document.getElementById('installWebBtn');
    const copyBtn = document.getElementById('copyBtn');
    const resetBtn = document.getElementById('resetBtn');

    if (installDesktopBtn) {
        installDesktopBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.location.href = `stremio://${url.replace(/^https?:\/\//, '')}`;
        });
    }

    if (installWebBtn) {
        installWebBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.open(`https://web.stremio.com/#/addons?addon=${encodeURIComponent(url)}`, '_blank');
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
            const url = document.getElementById('addonUrl').textContent;
            try {
                await navigator.clipboard.writeText(url);
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = `
                    <svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    Copied!
                `;
                setTimeout(() => {
                    copyBtn.innerHTML = originalText;
                }, 2000);
            } catch (err) {
                showError('Failed to copy URL');
            }
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            configForm.reset();
            catalogs = JSON.parse(JSON.stringify(defaultCatalogs));
            renderCatalogList();
            configForm.classList.remove('hidden');
            configForm.style.display = ''; // Clear inline style if any
            successMessage.classList.add('hidden');
            successMessage.style.display = '';
            hideError();

            if (stremioLoginBtn.getAttribute('data-action') === 'logout') {
                setStremioLoggedOutState();
            }
        });
    }

    const deleteAccountBtn = document.getElementById('deleteAccountBtn');
    if (deleteAccountBtn) {
        deleteAccountBtn.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to delete your settings? This will remove your credentials from the server and stop your addons from working.')) {
                return;
            }

            const authMethodValue = authMethod.value;
            const username = document.getElementById('username')?.value.trim();
            const password = document.getElementById('password')?.value;
            const authKey = document.getElementById('authKey')?.value.trim();

            // Validation
            if (authMethodValue === 'credentials') {
                if (!username || !password) {
                    showError('Please provide both email and password to delete your account.');
                    return;
                }
            } else {
                if (!authKey) {
                    showError('Please provide your Stremio auth key to delete your account.');
                    return;
                }
            }

            const payload = {};
            if (authMethodValue === 'credentials') {
                payload.username = username;
                payload.password = password;
            } else {
                payload.authKey = authKey;
            }

            setLoading(true);
            hideError();

            try {
                const response = await fetch('/tokens/', {
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || 'Failed to delete account');
                }

                alert('Settings deleted successfully.');
                // Clear form
                configForm.reset();
                if (stremioLoginBtn.getAttribute('data-action') === 'logout') {
                    setStremioLoggedOutState();
                }
                catalogs = JSON.parse(JSON.stringify(defaultCatalogs));
                renderCatalogList();

            } catch (err) {
                showError(err.message || 'Failed to delete account. Please try again.');
            } finally {
                setLoading(false);
            }
        });
    }
}

// UI Helpers
function setLoading(loading) {
    submitBtn.disabled = loading;
    if (loading) {
        btnText.classList.add('hidden'); // Use class hidden
        loader.classList.remove('hidden');
    } else {
        btnText.classList.remove('hidden');
        loader.classList.add('hidden');
    }
}

function showError(message) {
    const msgContent = errorMessage.querySelector('.message-content') || errorMessage;
    // Check if message-content span exists (it does in new HTML)
    if (errorMessage.querySelector('.message-content')) {
        errorMessage.querySelector('.message-content').textContent = message;
    } else {
        errorMessage.textContent = message;
    }
    errorMessage.classList.remove('hidden');
    errorMessage.classList.add('flex');
}

function hideError() {
    errorMessage.classList.add('hidden');
    errorMessage.classList.remove('flex');
}

function showSuccess(manifestUrl) {
    configForm.classList.add('hidden'); // Use classes
    successMessage.classList.remove('hidden');
    document.getElementById('addonUrl').textContent = manifestUrl;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Footer Year
function initializeFooter() {
    const yearSpan = document.getElementById('currentYear');
    if (yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }
}
