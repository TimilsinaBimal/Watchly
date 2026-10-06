// AIOManager integration. Watchly pushes its own manifest link into the user's
// AIOManager account, and AIOManager propagates the addon to every platform that
// account is connected to. The call is made by the server, not the browser: an
// AIOManager instance only answers cross-origin requests from origins its
// operator listed, so the page could not reach it directly.

import { showToast } from './ui.js';
import { LOADING_ICON, initializeValidatedSecretField } from './field-helpers.js';

function element(id) {
    return document.getElementById(id);
}

/** The manager fields, in the shape the settings payload carries them. */
export function aiomanagerPayload() {
    const autoSync = element('aiomanagerAutoSync');
    return {
        aiomanager_instance_url: element('aiomanagerInstanceUrl')?.value.trim() || '',
        aiomanager_api_key: element('aiomanagerApiKey')?.value.trim() || '',
        aiomanager_auto_sync: autoSync ? autoSync.checked : true
    };
}

function showSyncMessage(text, ok) {
    const message = element('aiomanagerSyncMessage');
    if (!message) return;
    message.textContent = text;
    message.className = ok ? 'mt-2 text-xs text-green-400' : 'mt-2 text-xs text-red-400';
}

/**
 * Push this install into AIOManager. 409 means no manager is connected to the
 * account: the manual button says so, and a save that syncs on its own stays quiet
 * because the user did not ask for anything.
 */
export async function refreshAIOManager(token, { quiet = false } = {}) {
    if (!token) return null;

    const button = element('aiomanagerSyncBtn');
    const originalHTML = button ? button.innerHTML : null;
    if (button) {
        button.disabled = true;
        button.innerHTML = LOADING_ICON;
    }

    try {
        const response = await fetch(`/${token}/aiomanager/sync`, { method: 'POST' });
        const data = await response.json().catch(() => ({}));

        if (response.status === 409) {
            if (!quiet) {
                showSyncMessage('No AIOManager account is connected to this install yet.', false);
            }
            return null;
        }

        if (!response.ok) {
            const message = data.detail || 'Could not sync to AIOManager.';
            showSyncMessage(message, false);
            showToast(message, 'error', 8000);
            return null;
        }

        showSyncMessage(`Synced to ${data.instance}.`, true);
        return data;
    } catch {
        // A dropped connection is usually just that; the next save retries.
        showSyncMessage('Could not reach the server. Try again.', false);
        return null;
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = originalHTML;
        }
    }
}

/** Wire the manager card: the key's check button and the manual push. */
export function initializeAIOManager(state) {
    const syncBtn = element('aiomanagerSyncBtn');
    if (syncBtn) {
        syncBtn.addEventListener('click', () => {
            if (!state?.auth?.token) {
                showToast('Save your settings first — the sync uses the addon link that login produced.', 'info', 6000);
                return;
            }
            refreshAIOManager(state.auth.token);
        });
    }

    initializeValidatedSecretField({
        input: element('aiomanagerApiKey'),
        validateBtn: element('aiomanagerApiKeyValidate'),
        validationMessage: element('aiomanagerValidationMessage'),
        toggleBtn: element('aiomanagerApiKeyToggle'),
        eyeIcon: element('aiomanagerApiKeyEye'),
        eyeOffIcon: element('aiomanagerApiKeyEyeOff'),
        emptyMessage: 'Paste your AIOManager account API key',
        successMessage: 'AIOManager accepts this key ✓',
        request: (apiKey) => fetch('/aiomanager/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_url: element('aiomanagerInstanceUrl')?.value.trim() || '',
                api_key: apiKey
            })
        }).then((response) => response.json()),
        getErrorMessage: (data) => data.message || 'AIOManager did not accept this key'
    });
}
