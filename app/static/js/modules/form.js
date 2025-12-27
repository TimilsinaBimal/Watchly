// Form Submission and UI Helpers

import { showToast, showConfirm, escapeHtml } from './ui.js';
import { switchSection } from './navigation.js';
import { MOVIE_GENRES, SERIES_GENRES } from '../constants.js';

// DOM Elements - will be initialized
let configForm = null;
let submitBtn = null;
let emailInput = null;
let passwordInput = null;
let languageSelect = null;
let movieGenreList = null;
let seriesGenreList = null;
let getCatalogs = null;
let resetApp = null;

export function initializeForm(domElements, catalogState) {
    configForm = domElements.configForm;
    submitBtn = domElements.submitBtn;
    emailInput = domElements.emailInput;
    passwordInput = domElements.passwordInput;
    languageSelect = domElements.languageSelect;
    movieGenreList = domElements.movieGenreList;
    seriesGenreList = domElements.seriesGenreList;
    getCatalogs = catalogState.getCatalogs;
    resetApp = catalogState.resetApp;

    initializeFormSubmission();
    initializeGenreLists();
    initializeLanguageSelect();
    initializePasswordToggles();
    initializeSuccessActions();
}

// Form Submission
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
        const catalogs = getCatalogs ? getCatalogs() : [];
        document.querySelectorAll(".catalog-item .switch input[type='checkbox']").forEach(toggle => {
            const catalogId = toggle.dataset.catalogId;
            const enabled = toggle.checked;
            const originalCatalog = catalogs.find(c => c.id === catalogId);
            if (originalCatalog) {
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
                    class="peer appearance-none w-5 h-5 border-2 border-slate-600 rounded bg-neutral-900 checked:bg-white checked:border-white transition-colors">
                <svg class="absolute w-3.5 h-3.5 text-black left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 peer-checked:opacity-100 pointer-events-none transition-opacity"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
            </div>
            <span class="text-sm text-slate-300 group-hover:text-white transition-colors select-none">${genre.name}</span>
        </label>
    `).join('');
}

function initializeLanguageSelect() {
    if (!languageSelect) return;
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

// Delete & Success Helpers
function initializeSuccessActions() {
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
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
        installDesktopBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const url = document.getElementById('addonUrl').textContent;
            window.location.href = `stremio://${url.replace(/^https?:\/\//, '')}`;
        });
    }
    const installWebBtn = document.getElementById('installWebBtn');
    if (installWebBtn) {
        installWebBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const url = document.getElementById('addonUrl').textContent;
            window.open(`https://web.stremio.com/#/addons?addon=${encodeURIComponent(url)}`, '_blank');
        });
    }

    const deleteAccountBtn = document.getElementById('deleteAccountBtn');
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
                if (resetApp) resetApp();
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

export function clearErrors() {
    const errEl = document.getElementById('errorMessage');
    if (errEl) errEl.classList.add('hidden');
    document.querySelectorAll('.border-red-500').forEach(e => e.classList.remove('border-red-500'));
}

function showSuccess(url) {
    // Hide form entirely by hiding the active section
    const sections = {
        welcome: document.getElementById('sect-welcome'),
        login: document.getElementById('sect-login'),
        config: document.getElementById('sect-config'),
        catalogs: document.getElementById('sect-catalogs'),
        install: document.getElementById('sect-install'),
        success: document.getElementById('sect-success')
    };
    Object.values(sections).forEach(s => { if (s) s.classList.add('hidden') });

    // Show Success Section
    if (sections.success) {
        sections.success.classList.remove('hidden');
        document.getElementById('addonUrl').textContent = url;
    }
}
