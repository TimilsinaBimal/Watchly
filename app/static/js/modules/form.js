// Form Submission and UI Helpers

import { showToast } from './ui.js';
import { switchSection } from './navigation.js';
import {
    clearValidationMessage,
    initializeEyeToggle,
    initializePasswordToggleButton,
    initializeValidatedSecretField,
    setValidationMessage
} from './field-helpers.js';
import { initializeSuccessActions, showSuccessSection } from './form-success.js';
import { initializeYearSliderControl } from './year-slider.js';
import { MOVIE_GENRES, SERIES_GENRES } from '../constants.js';

const YEAR_RANGE_DEFAULTS = window.YEAR_RANGE_DEFAULTS || { min: 1970, max: new Date().getFullYear() };
const LOADING_ICON = '<svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

// DOM Elements - will be initialized
let submitBtn = null;
let emailInput = null;
let passwordInput = null;
let languageSelect = null;
let movieGenreList = null;
let seriesGenreList = null;
let appState = null;
let resetApp = null;
let validatePosterRatingApiKey = null;
let updateYearSlider = () => {};

export function initializeForm(domElements, state, actions) {
    submitBtn = domElements.submitBtn;
    emailInput = domElements.emailInput;
    passwordInput = domElements.passwordInput;
    languageSelect = domElements.languageSelect;
    movieGenreList = domElements.movieGenreList;
    seriesGenreList = domElements.seriesGenreList;
    appState = state;
    resetApp = actions.resetApp;

    initializeFormSubmission();
    initializeGenreLists();
    initializeLanguageSelect();
    initializePasswordToggles();
    initializeSuccessHandlers();
    validatePosterRatingApiKey = initializePosterRatingProvider();
    initializeTmdb();
    initializeSimkl();
    initializeGemini();
    updateYearSlider = initializeYearSliderControl();
    initializeWatchHistorySource();
}

async function postJson(url, payload) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    return response.json();
}

function getRequestPayload() {
    const catalogs = appState ? appState.catalogs : [];

    return {
        authKey: (document.getElementById('authKey')?.value || '').trim() || undefined,
        email: emailInput?.value.trim() || undefined,
        password: passwordInput?.value || undefined,
        catalogs: catalogs.map(catalog => ({
            id: catalog.id,
            name: catalog.name,
            enabled: catalog.enabled !== false,
            enabled_movie: catalog.enabledMovie !== false,
            enabled_series: catalog.enabledSeries !== false,
            display_at_home: catalog.display_at_home !== false,
            shuffle: catalog.shuffle === true
        })),
        language: languageSelect?.value || 'english',
        year_min: parseInt(document.getElementById('yearMin')?.value || String(YEAR_RANGE_DEFAULTS.min), 10),
        year_max: parseInt(document.getElementById('yearMax')?.value || String(YEAR_RANGE_DEFAULTS.max), 10),
        popularity: document.getElementById('popularitySelect')?.value || 'balanced',
        sorting_order: document.getElementById('sortingOrderSelect')?.value || 'default',
        poster_rating_provider: document.getElementById('posterRatingProvider')?.value || '',
        poster_rating_api_key: document.getElementById('posterRatingApiKey')?.value.trim() || '',
        tmdb_api_key: document.getElementById('tmdbApiKey')?.value.trim() || '',
        simkl_api_key: document.getElementById('simklApiKey')?.value.trim() || '',
        gemini_api_key: document.getElementById('geminiApiKey')?.value.trim() || '',
        excluded_movie_genres: Array.from(document.querySelectorAll('input[name="movie-genre"]:checked')).map(cb => cb.value),
        excluded_series_genres: Array.from(document.querySelectorAll('input[name="series-genre"]:checked')).map(cb => cb.value),
        watch_history_source: document.getElementById('watchHistorySource')?.value || 'stremio',
    };
}

function buildTokenPayload(formData) {
    let posterRating;
    if (formData.poster_rating_provider && formData.poster_rating_api_key) {
        posterRating = {
            provider: formData.poster_rating_provider,
            api_key: formData.poster_rating_api_key
        };
    }

    return {
        authKey: formData.authKey,
        email: formData.email,
        password: formData.password,
        catalogs: formData.catalogs,
        language: formData.language,
        year_min: formData.year_min,
        year_max: formData.year_max,
        popularity: formData.popularity,
        sorting_order: formData.sorting_order,
        poster_rating: posterRating || null,
        tmdb_api_key: formData.tmdb_api_key || undefined,
        simkl_api_key: formData.simkl_api_key,
        gemini_api_key: formData.gemini_api_key,
        excluded_movie_genres: formData.excluded_movie_genres,
        excluded_series_genres: formData.excluded_series_genres,
        watch_history_source: formData.watch_history_source,
        trakt_access_token: window._watchlyOAuth?.trakt?.access_token || undefined,
        trakt_refresh_token: window._watchlyOAuth?.trakt?.refresh_token || undefined,
        simkl_access_token: window._watchlyOAuth?.simkl?.access_token || undefined,
    };
}

function validateFormData(formData) {
    if (!formData.authKey && !(formData.email && formData.password)) {
        showError('generalError', 'Please login with Stremio or enter email & password.');
        switchSection('login');
        return false;
    }

    if (!formData.tmdb_api_key) {
        showError('generalError', 'TMDB API key is required.');
        const tmdbInput = document.getElementById('tmdbApiKey');
        if (tmdbInput) {
            tmdbInput.focus();
            tmdbInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return false;
    }

    return true;
}

// Form Submission
function initializeFormSubmission() {
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        clearErrors();

        const formData = getRequestPayload();
        if (!validateFormData(formData)) {
            return;
        }

        if (formData.poster_rating_provider && formData.poster_rating_api_key && validatePosterRatingApiKey) {
            const isValid = await validatePosterRatingApiKey();
            if (!isValid) {
                return;
            }
        }

        setLoading(true);

        try {
            const payload = buildTokenPayload(formData);
            const response = await fetch('/tokens/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to generate manifest URL');
            }

            const data = await response.json();
            showSuccess(data.manifestUrl);
        } catch (error) {
            console.error('Error:', error);
            showError('generalError', error.message);
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

// Poster Rating Provider
function initializePosterRatingProvider() {
    const providerSelect = document.getElementById('posterRatingProvider');
    const apiKeyContainer = document.getElementById('posterRatingApiKeyContainer');
    const apiKeyInput = document.getElementById('posterRatingApiKey');
    const helpContainer = document.getElementById('posterRatingHelp');
    const helpText = document.getElementById('posterRatingHelpText');
    const validateBtn = document.getElementById('posterRatingApiKeyValidate');
    const toggleBtn = document.getElementById('posterRatingApiKeyToggle');
    const eyeIcon = document.getElementById('posterRatingApiKeyEye');
    const eyeOffIcon = document.getElementById('posterRatingApiKeyEyeOff');
    const validationMessage = document.getElementById('posterRatingValidationMessage');

    if (!providerSelect || !apiKeyContainer || !apiKeyInput || !helpContainer || !helpText) {
        return null;
    }

    const providerInfo = {
        rpdb: {
            name: 'RPDB (RatingPosterDB)',
            url: 'https://ratingposterdb.com',
            description: 'Enable ratings on posters via RatingPosterDB'
        },
        top_posters: {
            name: 'Top Posters',
            url: 'https://api.top-streaming.stream/',
            description: 'Enable ratings on posters via Top Posters'
        }
    };

    let isValidated = false;

    initializeEyeToggle({ input: apiKeyInput, toggleBtn, eyeIcon, eyeOffIcon });

    function resetValidation() {
        isValidated = false;
        clearValidationMessage(validationMessage);
    }

    function updateUI() {
        const selectedProvider = providerSelect.value;
        const info = providerInfo[selectedProvider];

        if (info) {
            apiKeyContainer.style.display = 'block';
            helpContainer.style.display = 'block';
            helpText.innerHTML = `${info.description}. Get your API key from <a href="${info.url}" target="_blank" class="text-slate-300 hover:text-white underline">${info.name}</a>.`;
            resetValidation();
            return;
        }

        apiKeyContainer.style.display = 'none';
        helpContainer.style.display = 'none';
        apiKeyInput.value = '';
        resetValidation();
    }

    async function validateApiKey() {
        const selectedProvider = providerSelect.value;
        const apiKey = apiKeyInput.value.trim();

        if (!selectedProvider || !apiKey) {
            setValidationMessage(validationMessage, 'Please select a provider and enter an API key', 'error');
            return false;
        }

        if (!validateBtn) {
            return false;
        }

        validateBtn.disabled = true;
        validateBtn.classList.add('opacity-50', 'cursor-not-allowed');
        const originalHTML = validateBtn.innerHTML;
        validateBtn.innerHTML = LOADING_ICON;

        try {
            const data = await postJson('/poster-rating/validate', {
                provider: selectedProvider,
                api_key: apiKey
            });

            if (data.valid) {
                setValidationMessage(validationMessage, 'API key is valid ✓', 'success');
                isValidated = true;
                return true;
            }

            setValidationMessage(validationMessage, data.message || 'Invalid API key', 'error');
            apiKeyInput.value = '';
            isValidated = false;
            return false;
        } catch (error) {
            setValidationMessage(validationMessage, 'Validation failed. Please try again.', 'error');
            isValidated = false;
            return false;
        } finally {
            validateBtn.disabled = false;
            validateBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            validateBtn.innerHTML = originalHTML;
        }
    }

    if (validateBtn) {
        validateBtn.addEventListener('click', validateApiKey);
    }

    apiKeyInput.addEventListener('input', resetValidation);
    providerSelect.addEventListener('change', updateUI);
    updateUI();

    return async () => {
        if (isValidated) {
            return true;
        }

        return validateApiKey();
    };
}

// TMDB API Key (Required)
function initializeTmdb() {
    initializeValidatedSecretField({
        input: document.getElementById('tmdbApiKey'),
        validateBtn: document.getElementById('tmdbApiKeyValidate'),
        validationMessage: document.getElementById('tmdbValidationMessage'),
        toggleBtn: document.getElementById('tmdbApiKeyToggle'),
        eyeIcon: document.getElementById('tmdbApiKeyEye'),
        eyeOffIcon: document.getElementById('tmdbApiKeyEyeOff'),
        emptyMessage: 'Please enter a TMDB API key',
        successMessage: 'TMDB API key is valid ✓',
        request: (apiKey) => postJson('/tmdb/validation', { api_key: apiKey }),
        getErrorMessage: (data) => data.message || 'Invalid TMDB API key'
    });
}

// Simkl Integration
function initializeSimkl() {
    initializeValidatedSecretField({
        input: document.getElementById('simklApiKey'),
        validateBtn: document.getElementById('simklApiKeyValidate'),
        validationMessage: document.getElementById('simklValidationMessage'),
        toggleBtn: document.getElementById('simklApiKeyToggle'),
        eyeIcon: document.getElementById('simklApiKeyEye'),
        eyeOffIcon: document.getElementById('simklApiKeyEyeOff'),
        emptyMessage: 'Please enter a Simkl API key',
        successMessage: 'Simkl API key is valid ✓',
        request: (apiKey) => postJson('/simkl/validation', { api_key: apiKey }),
        getErrorMessage: (data) => data.message || 'Invalid Simkl API key'
    });
}

// Gemini AI Integration
function initializeGemini() {
    initializeValidatedSecretField({
        input: document.getElementById('geminiApiKey'),
        validateBtn: document.getElementById('geminiApiKeyValidate'),
        validationMessage: document.getElementById('geminiValidationMessage'),
        toggleBtn: document.getElementById('geminiApiKeyToggle'),
        eyeIcon: document.getElementById('geminiApiKeyEye'),
        eyeOffIcon: document.getElementById('geminiApiKeyEyeOff'),
        emptyMessage: 'Please enter a Gemini API key',
        successMessage: 'Gemini API key is valid ✓',
        request: (apiKey) => postJson('/gemini/validation', { api_key: apiKey }),
        getErrorMessage: (data) => data.message || 'Invalid Gemini API key'
    });
}

function initializePasswordToggles() {
    initializePasswordToggleButton();
}

function initializeSuccessHandlers() {
    initializeSuccessActions({
        emailInput,
        passwordInput,
        resetApp,
        setLoading,
        showError
    });
}

function setLoading(loading) {
    if (!submitBtn) return;

    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader');
    submitBtn.disabled = loading;

    if (loading) {
        if (btnText) btnText.classList.add('hidden');
        if (loader) loader.classList.remove('hidden');
        return;
    }

    if (btnText) btnText.classList.remove('hidden');
    if (loader) loader.classList.add('hidden');
}

function showError(target, message) {
    if (target === 'generalError') {
        const errEl = document.getElementById('errorMessage');
        if (errEl) {
            errEl.querySelector('.message-content').textContent = message;
            errEl.classList.remove('hidden');
        } else {
            showToast(message, 'error');
        }
        return;
    }

    if (target === 'stremioAuthSection') {
        showToast(message, 'error');
        return;
    }

    const element = document.getElementById(target);
    if (!element) return;

    element.classList.add('border-red-500');
    element.focus();
}

export function clearErrors() {
    const errEl = document.getElementById('errorMessage');
    if (errEl) {
        errEl.classList.add('hidden');
    }

    document.querySelectorAll('.border-red-500').forEach(element => {
        element.classList.remove('border-red-500');
    });
}

export function refreshYearSlider() {
    updateYearSlider();
}

function showSuccess(url) {
    showSuccessSection(url);
}

// Watch History Source + OAuth
function initializeWatchHistorySource() {
    const sourceSelect = document.getElementById('watchHistorySource');
    const traktLoginBtn = document.getElementById('traktLoginBtn');
    const traktStatus = document.getElementById('traktStatus');
    const traktLogoutBtn = document.getElementById('traktLogoutBtn');
    const simklLoginBtn = document.getElementById('simklLoginBtn');
    const simklSyncStatus = document.getElementById('simklSyncStatus');
    const simklSyncLogoutBtn = document.getElementById('simklSyncLogoutBtn');

    if (!sourceSelect) return;

    window._watchlyOAuth = window._watchlyOAuth || {};

    window.addEventListener('message', (event) => {
        const data = event.data;
        if (!data || !data.provider || !data.tokens) return;

        if (data.provider === 'trakt') {
            window._watchlyOAuth.trakt = data.tokens;
            if (traktStatus) {
                traktStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
                traktStatus.classList.remove('text-slate-500');
                traktStatus.classList.add('text-green-400');
            }
            if (traktLogoutBtn) traktLogoutBtn.classList.remove('hidden');
            const traktOption = sourceSelect.querySelector('option[value="trakt"]');
            if (traktOption) traktOption.disabled = false;
        } else if (data.provider === 'simkl') {
            window._watchlyOAuth.simkl = data.tokens;
            if (simklSyncStatus) {
                simklSyncStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
                simklSyncStatus.classList.remove('text-slate-500');
                simklSyncStatus.classList.add('text-green-400');
            }
            if (simklSyncLogoutBtn) simklSyncLogoutBtn.classList.remove('hidden');
            const simklOption = sourceSelect.querySelector('option[value="simkl"]');
            if (simklOption) simklOption.disabled = false;
        }
    });

    if (traktLoginBtn) {
        traktLoginBtn.addEventListener('click', () => {
            window.open('/auth/trakt', '_blank', 'width=600,height=700');
        });
    }

    if (simklLoginBtn) {
        simklLoginBtn.addEventListener('click', () => {
            window.open('/auth/simkl', '_blank', 'width=600,height=700');
        });
    }

    if (traktLogoutBtn) {
        traktLogoutBtn.addEventListener('click', () => {
            delete window._watchlyOAuth.trakt;
            if (traktStatus) {
                traktStatus.textContent = 'Not connected';
                traktStatus.classList.remove('text-green-400');
                traktStatus.classList.add('text-slate-500');
            }
            traktLogoutBtn.classList.add('hidden');
            const traktOption = sourceSelect.querySelector('option[value="trakt"]');
            if (traktOption) traktOption.disabled = true;
            if (sourceSelect.value === 'trakt') sourceSelect.value = 'stremio';
        });
    }

    if (simklSyncLogoutBtn) {
        simklSyncLogoutBtn.addEventListener('click', () => {
            delete window._watchlyOAuth.simkl;
            if (simklSyncStatus) {
                simklSyncStatus.textContent = 'Not connected';
                simklSyncStatus.classList.remove('text-green-400');
                simklSyncStatus.classList.add('text-slate-500');
            }
            simklSyncLogoutBtn.classList.add('hidden');
            const simklOption = sourceSelect.querySelector('option[value="simkl"]');
            if (simklOption) simklOption.disabled = true;
            if (sourceSelect.value === 'simkl') sourceSelect.value = 'stremio';
        });
    }
}
