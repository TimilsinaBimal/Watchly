// Form Submission and UI Helpers

import { escapeHtml, showToast } from './ui.js';
import { switchSection } from './navigation.js';
import {
    clearValidationMessage,
    initializeEyeToggle,
    initializePasswordToggleButton,
    initializeValidatedSecretField,
    LOADING_ICON,
    setValidationMessage
} from './field-helpers.js';
import { initializeSuccessActions, showSuccessSection } from './form-success.js';
import { initializeYearSliderControl } from './year-slider.js';
import { MOVIE_GENRES, SERIES_GENRES } from '../constants.js';
import { setProviderConnected } from './accounts.js';
import { getPreparedStremioProfiles, recallProviderAccount } from './auth.js';

let submitBtn = null;
let emailInput = null;
let passwordInput = null;
let languageSelect = null;
let movieGenreList = null;
let seriesGenreList = null;
let appState = null;
let resetApp = null;
let validatePosterRatingApiKey = null;

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
    initializePasswordToggleButton();
    initializeSuccessActions({
        emailInput,
        passwordInput,
        resetApp,
        setLoading,
        showError
    });
    validatePosterRatingApiKey = initializePosterRatingProvider();
    initializeTmdb();
    initializeSimkl();
    initializeLlm();
    const updateYearSlider = initializeYearSliderControl();
    initializeWatchHistorySource();
    return updateYearSlider;
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
    const authKey = document.getElementById('authKey').value.trim() || undefined;
    const hasSelectedProfile = !!(document.getElementById('stremioProfileId').value && authKey);

    const posterProvider = document.getElementById('posterRatingProvider').value;
    const posterApiKey = document.getElementById('posterRatingApiKey').value.trim();
    const posterUrlTemplate = document.getElementById('posterRatingUrlTemplate').value.trim();
    let posterRating = null;
    if (posterProvider === 'custom' && posterUrlTemplate) {
        posterRating = { provider: 'custom', api_key: posterApiKey || null, url_template: posterUrlTemplate };
    } else if (posterProvider && posterApiKey) {
        posterRating = { provider: posterProvider, api_key: posterApiKey };
    }

    const llmProvider = document.getElementById('llmProvider').value;
    const llmApiKey = document.getElementById('llmApiKey').value.trim();

    return {
        authKey,
        email: hasSelectedProfile ? undefined : emailInput.value.trim() || undefined,
        password: hasSelectedProfile ? undefined : passwordInput.value || undefined,
        catalogs: appState.catalogs.map(catalog => ({
            id: catalog.id,
            name: catalog.name,
            enabled: catalog.enabled,
            enabled_movie: catalog.enabledMovie,
            enabled_series: catalog.enabledSeries,
            display_at_home: catalog.display_at_home,
            shuffle: catalog.shuffle,
            rows: catalog.rows
        })),
        language: languageSelect.value,
        year_min: parseInt(document.getElementById('yearMin').value, 10),
        year_max: parseInt(document.getElementById('yearMax').value, 10),
        popularity: document.getElementById('popularitySelect').value,
        sorting_order: document.getElementById('sortingOrderSelect').value,
        poster_rating: posterRating,
        tmdb_api_key: document.getElementById('tmdbApiKey').value.trim() || undefined,
        simkl_api_key: document.getElementById('simklApiKey').value.trim(),
        llm: (llmProvider && llmApiKey)
            ? {
                provider: llmProvider,
                api_key: llmApiKey,
                model: document.getElementById('llmModel').value.trim() || undefined,
            }
            : undefined,
        excluded_movie_genres: Array.from(document.querySelectorAll('input[name="movie-genre"]:checked')).map(cb => cb.value),
        excluded_series_genres: Array.from(document.querySelectorAll('input[name="series-genre"]:checked')).map(cb => cb.value),
        watch_history_source: document.getElementById('watchHistorySource').value,
        trakt_access_token: window._watchlyOAuth?.trakt?.access_token || undefined,
        trakt_refresh_token: window._watchlyOAuth?.trakt?.refresh_token || undefined,
        trakt_token_expires_at: window._watchlyOAuth?.trakt?.expires_at || undefined,
        simkl_access_token: window._watchlyOAuth?.simkl?.access_token || undefined,
    };
}

function validateFormData(formData) {
    const hasStremio = !!(formData.authKey || (formData.email && formData.password));
    const hasTrakt = !!window._watchlyOAuth?.trakt?.access_token;
    const hasSimkl = !!window._watchlyOAuth?.simkl?.access_token;

    if (!hasStremio && !hasTrakt && !hasSimkl) {
        showError('Connect at least one account: Stremio, Trakt, or Simkl.');
        switchSection('login');
        return false;
    }

    if (formData.watch_history_source === 'stremio' && !hasStremio) {
        showError('Login with Stremio, or pick Trakt/Simkl as your watch history source.');
        switchSection('login');
        return false;
    }

    if (!formData.tmdb_api_key) {
        showError('TMDB API key is required.');
        const tmdbInput = document.getElementById('tmdbApiKey');
        if (tmdbInput) {
            tmdbInput.focus();
            tmdbInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return false;
    }

    return true;
}

function initializeFormSubmission() {
    if (!submitBtn) return;

    submitBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        clearErrors();

        const payload = getRequestPayload();
        if (!validateFormData(payload)) {
            return;
        }

        if (document.getElementById('posterRatingProvider').value && validatePosterRatingApiKey) {
            const isValid = await validatePosterRatingApiKey();
            if (!isValid) {
                return;
            }
        }

        setLoading(true);

        try {
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

                // A shared Trakt or Simkl identity would merge the separate Stremio
                // profiles back into one Watchly account. Batch mode is deliberately
                // driven only by each profile's own Stremio history.
                if (preparedProfiles.length > 1) {
                    profilePayload.watch_history_source = 'stremio';
                    profilePayload.trakt_access_token = undefined;
                    profilePayload.trakt_refresh_token = undefined;
                    profilePayload.trakt_token_expires_at = undefined;
                    profilePayload.simkl_access_token = undefined;
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

            appState.auth.token = installations[0].token;
            appState.auth.hasInstall = true;

            showSuccessSection(installations);
        } catch (error) {
            console.error('Error:', error);
            showError(error.message);
        } finally {
            setLoading(false);
        }
    });
}

function initializeGenreLists() {
    renderGenreList(movieGenreList, MOVIE_GENRES, 'movie-genre');
    renderGenreList(seriesGenreList, SERIES_GENRES, 'series-genre');
}

function renderGenreList(container, genres, namePrefix) {
    if (!container) return;

    container.innerHTML = genres.map(genre => `
        <label class="flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 cursor-pointer transition group">
            <div class="relative flex items-center">
                <input type="checkbox" name="${namePrefix}" value="${escapeHtml(genre.id)}"
                    class="peer appearance-none w-5 h-5 border-2 border-slate-600 rounded bg-neutral-900 checked:bg-white checked:border-white transition-colors">
                <svg class="absolute w-3.5 h-3.5 text-black left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 peer-checked:opacity-100 pointer-events-none transition-opacity"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
            </div>
            <span class="text-sm text-slate-300 group-hover:text-white transition-colors select-none">${escapeHtml(genre.name)}</span>
        </label>
    `).join('');
}

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
    }

    function updateUI() {
        const selectedProvider = providerSelect.value;

        if (selectedProvider === 'custom') {
            if (templateContainer) templateContainer.style.display = 'block';
            apiKeyContainer.style.display = 'block';
            helpContainer.style.display = 'block';
            helpText.innerHTML = CUSTOM_HELP;
            resetValidation();
            return;
        }

        if (templateContainer) templateContainer.style.display = 'none';

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
        errorMessage: 'Invalid TMDB API key'
    });
}

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
        errorMessage: 'Invalid Simkl API key'
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
        errorMessage: 'Could not validate this key'
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

function showError(message) {
    const errEl = document.getElementById('errorMessage');
    errEl.querySelector('.message-content').textContent = message;
    errEl.classList.remove('hidden');
}

export function clearErrors() {
    document.getElementById('errorMessage').classList.add('hidden');
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
        if (event.origin !== window.location.origin) return;
        const data = event.data;
        if (!data || !data.provider || !data.tokens) return;

        if (data.provider === 'trakt') {
            window._watchlyOAuth.trakt = data.tokens;
            if (traktStatus) traktStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
            setProviderConnected('trakt', true);
        } else if (data.provider === 'simkl') {
            window._watchlyOAuth.simkl = data.tokens;
            if (simklSyncStatus) simklSyncStatus.textContent = `Connected as ${data.username || 'Unknown'}`;
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
            setProviderConnected('trakt', false);
        });
    }

    if (simklSyncLogoutBtn) {
        simklSyncLogoutBtn.addEventListener('click', () => {
            delete window._watchlyOAuth.simkl;
            setProviderConnected('simkl', false);
        });
    }
}
