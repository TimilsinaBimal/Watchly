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
import { setProviderConnected } from './accounts.js';
import { getPreparedStremioProfiles, recallProviderAccount } from './auth.js';

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
    initializeLlm();
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
    const authKey = (document.getElementById('authKey')?.value || '').trim() || undefined;
    const hasSelectedProfile = !!(document.getElementById('stremioProfileId')?.value && authKey);

    return {
        authKey,
        email: hasSelectedProfile ? undefined : emailInput?.value.trim() || undefined,
        password: hasSelectedProfile ? undefined : passwordInput?.value || undefined,
        catalogs: catalogs.map(catalog => ({
            id: catalog.id,
            name: catalog.name,
            enabled: catalog.enabled !== false,
            enabled_movie: catalog.enabledMovie !== false,
            enabled_series: catalog.enabledSeries !== false,
            display_at_home: catalog.display_at_home !== false,
            shuffle: catalog.shuffle === true,
            rows: catalog.rows
        })),
        language: languageSelect?.value || 'english',
        year_min: parseInt(document.getElementById('yearMin')?.value || String(YEAR_RANGE_DEFAULTS.min), 10),
        year_max: parseInt(document.getElementById('yearMax')?.value || String(YEAR_RANGE_DEFAULTS.max), 10),
        popularity: document.getElementById('popularitySelect')?.value || 'balanced',
        sorting_order: document.getElementById('sortingOrderSelect')?.value || 'default',
        poster_rating_provider: document.getElementById('posterRatingProvider')?.value || '',
        poster_rating_api_key: document.getElementById('posterRatingApiKey')?.value.trim() || '',
        poster_rating_url_template: document.getElementById('posterRatingUrlTemplate')?.value.trim() || '',
        tmdb_api_key: document.getElementById('tmdbApiKey')?.value.trim() || '',
        simkl_api_key: document.getElementById('simklApiKey')?.value.trim() || '',
        mdblist_api_key: document.getElementById('mdblistApiKey')?.value.trim() || '',
        llm_provider: document.getElementById('llmProvider')?.value || '',
        llm_api_key: document.getElementById('llmApiKey')?.value.trim() || '',
        llm_model: document.getElementById('llmModel')?.value.trim() || '',
        excluded_movie_genres: Array.from(document.querySelectorAll('input[name="movie-genre"]:checked')).map(cb => cb.value),
        excluded_series_genres: Array.from(document.querySelectorAll('input[name="series-genre"]:checked')).map(cb => cb.value),
        watch_history_source: document.getElementById('watchHistorySource')?.value || 'stremio',
    };
}

function buildTokenPayload(formData) {
    let posterRating;
    if (formData.poster_rating_provider === 'custom' && formData.poster_rating_url_template) {
        posterRating = {
            provider: 'custom',
            api_key: formData.poster_rating_api_key || null,
            url_template: formData.poster_rating_url_template
        };
    } else if (formData.poster_rating_provider && formData.poster_rating_api_key) {
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
        llm: (formData.llm_provider && formData.llm_api_key)
            ? {
                provider: formData.llm_provider,
                api_key: formData.llm_api_key,
                model: formData.llm_model || undefined,
            }
            : undefined,
        excluded_movie_genres: formData.excluded_movie_genres,
        excluded_series_genres: formData.excluded_series_genres,
        watch_history_source: formData.watch_history_source,
        trakt_access_token: window._watchlyOAuth?.trakt?.access_token || undefined,
        trakt_refresh_token: window._watchlyOAuth?.trakt?.refresh_token || undefined,
        trakt_token_expires_at: window._watchlyOAuth?.trakt?.expires_at || undefined,
        simkl_access_token: window._watchlyOAuth?.simkl?.access_token || undefined,
        mdblist_api_key: formData.mdblist_api_key || undefined,
    };
}

function validateFormData(formData) {
    const hasStremio = !!(formData.authKey || (formData.email && formData.password));
    const hasTrakt = !!window._watchlyOAuth?.trakt?.access_token;
    const hasSimkl = !!window._watchlyOAuth?.simkl?.access_token;
    const hasMdblist = !!formData.mdblist_api_key;

    if (!hasStremio && !hasTrakt && !hasSimkl && !hasMdblist) {
        showError('generalError', 'Connect at least one account: Stremio, Trakt, Simkl or MDBList.');
        switchSection('login');
        return false;
    }

    if (formData.watch_history_source === 'stremio' && !hasStremio) {
        showError('generalError', 'Login with Stremio, or pick Trakt, Simkl or MDBList as your watch history source.');
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

        if (formData.poster_rating_provider && validatePosterRatingApiKey) {
            const isValid = await validatePosterRatingApiKey();
            if (!isValid) {
                return;
            }
        }

        setLoading(true);

        try {
            const payload = buildTokenPayload(formData);
            const preparedProfiles = getPreparedStremioProfiles();
            const profileRequests = preparedProfiles.length ? preparedProfiles : [null];
            const installations = [];

            if (preparedProfiles.length > 1 && payload.watch_history_source !== 'stremio') {
                showToast('Multi-profile instances use each Stremio profile as their history source.', 'info', 5000);
            }

            for (const profile of profileRequests) {
                const profilePayload = profile
                    ? { ...payload, authKey: profile.authKey, email: undefined, password: undefined }
                    : payload;

                // A shared Trakt, Simkl or MDBList identity would merge the separate Stremio
                // profiles back into one Watchly account. Batch mode is deliberately
                // driven only by each profile's own Stremio history.
                if (preparedProfiles.length > 1) {
                    profilePayload.watch_history_source = 'stremio';
                    profilePayload.trakt_access_token = undefined;
                    profilePayload.trakt_refresh_token = undefined;
                    profilePayload.trakt_token_expires_at = undefined;
                    profilePayload.simkl_access_token = undefined;
                    profilePayload.mdblist_api_key = undefined;
                }

                const response = await fetch('/tokens/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(profilePayload)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    const prefix = profile ? `${profile.name}: ` : '';
                    throw new Error(prefix + (errorData.detail || 'Failed to generate manifest URL'));
                }

                const data = await response.json();
                installations.push({
                    profileName: profile?.name || 'Watchly',
                    profileId: profile?.id,
                    authKey: profile?.authKey,
                    url: data.manifestUrl,
                    token: data.token,
                });

                // The server refreshed an expired Trakt token while verifying it.
                // Trakt rotates refresh tokens, so keeping our old pair would make
                // a second save present a spent refresh token.
                if (data.refreshedTrakt) {
                    window._watchlyOAuth = window._watchlyOAuth || {};
                    window._watchlyOAuth.trakt = {
                        access_token: data.refreshedTrakt.access_token,
                        refresh_token: data.refreshedTrakt.refresh_token,
                        expires_at: data.refreshedTrakt.expires_at,
                    };
                }
            }

            if (appState && installations.length) {
                const firstInstallation = installations[0];
                const manifestPath = new URL(firstInstallation.url).pathname.split('/').filter(Boolean);
                appState.auth.token = firstInstallation.token || manifestPath.at(-2) || '';
                appState.auth.hasInstall = !!appState.auth.token;
            }

            showSuccess(installations.length === 1 ? installations[0] : installations);
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
        <label class="cursor-pointer select-none">
            <input type="checkbox" name="${namePrefix}" value="${genre.id}" class="peer sr-only">
            <span class="inline-flex h-10 items-center rounded-full border border-white/10 bg-white/[0.03] px-3.5 text-sm text-neutral-200 transition hover:border-white/20 hover:text-white peer-checked:border-red-400/40 peer-checked:bg-red-500/10 peer-checked:text-red-200 peer-checked:line-through peer-checked:decoration-red-300/60 peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60">${genre.name}</span>
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
    const templateContainer = document.getElementById('posterRatingTemplateContainer');
    const templateInput = document.getElementById('posterRatingUrlTemplate');
    const templateMessage = document.getElementById('posterRatingTemplateMessage');
    const previewContainer = document.getElementById('posterPreviewContainer');
    const previewBtn = document.getElementById('posterPreviewBtn');
    const previewMessage = document.getElementById('posterPreviewMessage');
    const previewGrid = document.getElementById('posterPreviewGrid');

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
            url: 'https://api.top-posters.com/',
            description: 'Enable ratings on posters via Top Posters'
        }
    };

    const CUSTOM_HELP = 'Bring your own poster service. Paste one URL that Watchly fills in per title '
        + 'before handing it to Stremio &mdash; the placeholders below are swapped for each item\'s values:'
        + '<ul class="mt-2 space-y-1 list-disc list-inside">'
        + '<li><code>{imdb_id}</code> &mdash; IMDb id, e.g. tt0468569 <em>(required)</em></li>'
        + '<li><code>{type}</code> &mdash; <code>movie</code> or <code>series</code></li>'
        + '<li><code>{language}</code> &mdash; full locale, e.g. en-US</li>'
        + '<li><code>{language_short}</code> &mdash; language only, e.g. en</li>'
        + '<li><code>{api_key}</code> &mdash; filled from the optional API key field below</li>'
        + '</ul>'
        + '<span class="block mt-2">Example: '
        + '<code>https://example.com/{type}/{imdb_id}.jpg?lang={language_short}</code></span>';

    let isValidated = false;

    initializeEyeToggle({ input: apiKeyInput, toggleBtn, eyeIcon, eyeOffIcon });

    function resetValidation() {
        isValidated = false;
        clearValidationMessage(validationMessage);
        if (templateMessage) clearValidationMessage(templateMessage);
        clearPreview();
    }

    function clearPreview() {
        if (!previewGrid) return;
        previewGrid.replaceChildren();
        previewGrid.classList.add('hidden');
        clearValidationMessage(previewMessage);
    }

    function posterTile(title, url) {
        const tile = document.createElement('figure');
        const frame = document.createElement('div');
        frame.className = 'aspect-[2/3] overflow-hidden rounded-lg border border-white/10 bg-white/[0.04] animate-pulse';
        const img = document.createElement('img');
        img.className = 'h-full w-full object-cover';
        img.alt = `${title} poster`;
        img.referrerPolicy = 'no-referrer';
        img.addEventListener('load', () => frame.classList.remove('animate-pulse'));
        img.addEventListener('error', () => {
            const note = document.createElement('div');
            note.className = 'flex h-full items-center justify-center p-3 text-center text-xs text-neutral-400';
            note.textContent = 'Couldn\u2019t load this poster \u2014 check the template';
            frame.classList.remove('animate-pulse');
            frame.replaceChildren(note);
        });
        img.src = url;
        frame.appendChild(img);
        const caption = document.createElement('figcaption');
        caption.className = 'mt-2 truncate text-xs text-neutral-300';
        caption.textContent = title;
        tile.append(frame, caption);
        return tile;
    }

    async function showPreview() {
        const apiKey = apiKeyInput.value.trim();
        const payload = {
            url_template: templateInput?.value.trim() || '',
            api_key: apiKey || null,
            language: languageSelect?.value || undefined,
            // The marker stands for the saved key, which only the server can look up.
            token: apiKey === window.STORED_SECRET ? appState?.auth.token || undefined : undefined
        };

        clearPreview();
        previewBtn.disabled = true;
        previewBtn.textContent = 'Loading\u2026';
        try {
            const response = await fetch('/poster-rating/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok) {
                setValidationMessage(previewMessage, data.detail || 'Preview failed. Please try again.', 'error');
                return;
            }
            previewGrid.replaceChildren(...data.map(poster => posterTile(poster.title, poster.url)));
            previewGrid.classList.remove('hidden');
        } catch {
            setValidationMessage(previewMessage, 'Preview failed. Please try again.', 'error');
        } finally {
            previewBtn.disabled = false;
            previewBtn.textContent = 'Preview';
        }
    }

    function updateUI() {
        const selectedProvider = providerSelect.value;

        if (selectedProvider === 'custom') {
            if (templateContainer) templateContainer.style.display = 'block';
            if (previewContainer) previewContainer.style.display = 'block';
            apiKeyContainer.style.display = 'block';
            helpContainer.style.display = 'block';
            helpText.innerHTML = CUSTOM_HELP;
            resetValidation();
            return;
        }

        if (templateContainer) templateContainer.style.display = 'none';
        if (previewContainer) previewContainer.style.display = 'none';

        const info = providerInfo[selectedProvider];
        if (info) {
            apiKeyContainer.style.display = 'block';
            helpContainer.style.display = 'block';
            helpText.innerHTML = `${info.description}. Get your API key from <a href="${info.url}" target="_blank" class="text-neutral-200 hover:text-white underline">${info.name}</a>.`;
            resetValidation();
            return;
        }

        apiKeyContainer.style.display = 'none';
        helpContainer.style.display = 'none';
        apiKeyInput.value = '';
        resetValidation();
    }

    function validateCustomTemplate() {
        const template = templateInput?.value.trim() || '';
        const msgEl = templateMessage || validationMessage;
        let parsed;
        try {
            parsed = new URL(template);
        } catch {
            parsed = null;
        }
        if (!parsed || (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')) {
            setValidationMessage(msgEl, 'Enter a valid http(s) URL', 'error');
            isValidated = false;
            return false;
        }
        if (!template.includes('{imdb_id}')) {
            setValidationMessage(msgEl, 'Template must contain {imdb_id}', 'error');
            isValidated = false;
            return false;
        }
        setValidationMessage(msgEl, 'Template looks good ✓', 'success');
        isValidated = true;
        return true;
    }

    async function validateApiKey() {
        const selectedProvider = providerSelect.value;

        if (selectedProvider === 'custom') {
            return validateCustomTemplate();
        }

        const apiKey = apiKeyInput.value.trim();

        if (!selectedProvider || !apiKey) {
            setValidationMessage(validationMessage, 'Please select a provider and enter an API key', 'error');
            return false;
        }

        if (apiKey === window.STORED_SECRET) {
            // Placeholder for the saved key, which we never received — nothing to
            // validate, and the server swaps the real key back in on submit.
            isValidated = true;
            return true;
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
    if (previewBtn) previewBtn.addEventListener('click', showPreview);

    apiKeyInput.addEventListener('input', resetValidation);
    if (templateInput) templateInput.addEventListener('input', resetValidation);
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

// AI / LLM Integration
const LLM_PROVIDER_INFO = {
    gemini: { keyPlaceholder: 'Paste your Gemini API key here', modelPlaceholder: 'Model (default: gemini-2.5-flash)' },
    openai: { keyPlaceholder: 'Paste your OpenAI API key here', modelPlaceholder: 'Model (default: gpt-5-mini)' },
    anthropic: { keyPlaceholder: 'Paste your Anthropic API key here', modelPlaceholder: 'Model (default: claude-haiku-4-5)' },
    openrouter: { keyPlaceholder: 'Paste your OpenRouter API key here', modelPlaceholder: 'Model (default: openai/gpt-4o-mini)' },
};

function initializeLlm() {
    const providerSelect = document.getElementById('llmProvider');
    const keyContainer = document.getElementById('llmApiKeyContainer');
    const keyInput = document.getElementById('llmApiKey');
    const modelContainer = document.getElementById('llmModelContainer');
    const modelInput = document.getElementById('llmModel');

    if (providerSelect) {
        providerSelect.addEventListener('change', () => {
            const info = LLM_PROVIDER_INFO[providerSelect.value];
            if (keyContainer) keyContainer.style.display = info ? 'block' : 'none';
            if (modelContainer) modelContainer.style.display = info ? 'block' : 'none';
            if (info) {
                if (keyInput) keyInput.placeholder = info.keyPlaceholder;
                if (modelInput) modelInput.placeholder = info.modelPlaceholder;
            } else {
                if (keyInput) keyInput.value = '';
                if (modelInput) modelInput.value = '';
            }
        });
    }

    initializeValidatedSecretField({
        input: keyInput,
        validateBtn: document.getElementById('llmApiKeyValidate'),
        validationMessage: document.getElementById('llmValidationMessage'),
        toggleBtn: document.getElementById('llmApiKeyToggle'),
        eyeIcon: document.getElementById('llmApiKeyEye'),
        eyeOffIcon: document.getElementById('llmApiKeyEyeOff'),
        emptyMessage: 'Please enter an API key',
        successMessage: 'API key works ✓',
        request: (apiKey) => postJson('/llm/validation', {
            provider: providerSelect?.value || 'gemini',
            api_key: apiKey,
            model: modelInput?.value.trim() || undefined,
        }),
        getErrorMessage: (data) => data.message || 'Could not validate this key'
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

function showSuccess(url, token) {
    showSuccessSection(url, token);
}

// Watch History Source + OAuth
function initializeWatchHistorySource() {
    const traktLoginBtn = document.getElementById('traktLoginBtn');
    const traktStatus = document.getElementById('traktStatus');
    const traktLogoutBtn = document.getElementById('traktLogoutBtn');
    const simklLoginBtn = document.getElementById('simklLoginBtn');
    const simklSyncStatus = document.getElementById('simklSyncStatus');
    const simklSyncLogoutBtn = document.getElementById('simklSyncLogoutBtn');

    window._watchlyOAuth = window._watchlyOAuth || {};

    window.addEventListener('message', (event) => {
        const data = event.data;
        if (!data || !data.provider || !data.tokens) return;

        if (data.provider === 'trakt') {
            window._watchlyOAuth.trakt = data.tokens;
            if (traktStatus) {
                traktStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
                traktStatus.classList.remove('text-neutral-400');
                traktStatus.classList.add('text-green-400');
            }
            if (traktLogoutBtn) traktLogoutBtn.classList.remove('hidden');
            setProviderConnected('trakt', true);
        } else if (data.provider === 'simkl') {
            window._watchlyOAuth.simkl = data.tokens;
            if (simklSyncStatus) {
                simklSyncStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
                simklSyncStatus.classList.remove('text-neutral-400');
                simklSyncStatus.classList.add('text-green-400');
            }
            if (simklSyncLogoutBtn) simklSyncLogoutBtn.classList.remove('hidden');
            setProviderConnected('simkl', true);
        }

        // First login this session: look up an existing account for this provider
        // and load its saved settings. Skipped when an account is already loaded
        // (e.g. via Stremio) so connecting a second provider can't overwrite it.
        if ((data.provider === 'trakt' || data.provider === 'simkl') && !appState?.auth?.loggedIn) {
            recallProviderAccount(data.provider, data.tokens);
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
                traktStatus.classList.add('text-neutral-400');
            }
            traktLogoutBtn.classList.add('hidden');
            setProviderConnected('trakt', false);
        });
    }

    const mdblistKeyInput = document.getElementById('mdblistApiKey');
    const mdblistConnectBtn = document.getElementById('mdblistConnectBtn');
    const mdblistStatusMessage = document.getElementById('mdblistStatusMessage');
    const mdblistStatus = document.getElementById('mdblistStatus');
    const mdblistLogoutBtn = document.getElementById('mdblistLogoutBtn');

    if (mdblistConnectBtn) {
        mdblistConnectBtn.addEventListener('click', async () => {
            const apiKey = mdblistKeyInput?.value.trim();
            if (!apiKey) {
                setValidationMessage(mdblistStatusMessage, 'Paste your MDBList API key first', 'error');
                return;
            }
            mdblistConnectBtn.disabled = true;
            try {
                const data = await postJson('/mdblist/validation', { api_key: apiKey });
                if (!data.valid) {
                    setValidationMessage(mdblistStatusMessage, data.message || 'Invalid MDBList API key', 'error');
                    return;
                }
                clearValidationMessage(mdblistStatusMessage);
                if (mdblistStatus) mdblistStatus.textContent = data.message;
                setProviderConnected('mdblist', true);
                if (!appState?.auth?.loggedIn) {
                    recallProviderAccount('mdblist', { api_key: apiKey });
                }
            } catch (e) {
                setValidationMessage(mdblistStatusMessage, 'Could not reach the server. Try again.', 'error');
            } finally {
                mdblistConnectBtn.disabled = false;
            }
        });
    }

    if (mdblistLogoutBtn) {
        mdblistLogoutBtn.addEventListener('click', () => {
            if (mdblistKeyInput) mdblistKeyInput.value = '';
            if (mdblistStatus) mdblistStatus.textContent = 'MDBList';
            setProviderConnected('mdblist', false);
        });
    }

    if (simklSyncLogoutBtn) {
        simklSyncLogoutBtn.addEventListener('click', () => {
            delete window._watchlyOAuth.simkl;
            if (simklSyncStatus) {
                simklSyncStatus.textContent = 'Not connected';
                simklSyncStatus.classList.remove('text-green-400');
                simklSyncStatus.classList.add('text-neutral-400');
            }
            simklSyncLogoutBtn.classList.add('hidden');
            setProviderConnected('simkl', false);
        });
    }
}
