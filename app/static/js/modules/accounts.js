// Accounts page state + Watch History Source segmented control on Configure.
//
// Each provider card has two views — disconnected (login UI) and connected
// (status + Disconnect) — toggled via setProviderConnected. The Configure
// page's source picker is always interactive: clicking a provider that isn't
// connected jumps the user to the matching card in Accounts instead of
// silently doing nothing.

import { showToast } from './ui.js';
import { unlockNavigation } from './navigation.js';

const ACTIVE_CLASSES = ['bg-white/10', 'text-white', 'shadow-sm'];
const ACTIVE_BORDER_CLASS = 'border-white/20';
const INACTIVE_CLASSES = ['text-slate-400', 'hover:text-white', 'hover:bg-white/5'];
const INACTIVE_BORDER_CLASS = 'border-transparent';

const PROVIDER_LABELS = { stremio: 'Stremio', trakt: 'Trakt', simkl: 'Simkl' };

let switchSectionFn = null;
const connectedState = { stremio: false, trakt: false, simkl: false };

export function initializeAccountsUI({ switchSection } = {}) {
    switchSectionFn = switchSection || null;

    document.querySelectorAll('.source-btn').forEach(btn => {
        btn.addEventListener('click', () => onSourceButtonClick(btn.dataset.sourceBtn));
    });

    document.querySelectorAll('.account-link').forEach(link => {
        link.addEventListener('click', () => goToAccounts());
    });

    syncAccountsNextButton();
}

export function setStremioConnected(connected) {
    connectedState.stremio = connected;
    setProviderDot('stremio', connected);
    setProviderView('stremio', connected);

    if (!connected) {
        // Cascade: optional providers reset visually when Stremio drops.
        // Tokens in window._watchlyOAuth and inline status text are managed
        // by callers (resetApp / OAuth handlers), not here.
        setProviderConnected('trakt', false);
        setProviderConnected('simkl', false);
        setWatchHistorySource('stremio');
    }

    syncAccountsNextButton();
}

export function setProviderConnected(provider, connected) {
    if (provider === 'stremio') {
        setStremioConnected(connected);
        return;
    }
    if (provider !== 'trakt' && provider !== 'simkl') return;

    connectedState[provider] = connected;
    setProviderDot(provider, connected);
    setProviderView(provider, connected);

    if (connected) {
        // Trakt/Simkl alone is enough to configure the addon — no Stremio needed.
        unlockNavigation();
    }

    if (connected && !connectedState.stremio && currentSource() === 'stremio') {
        // No Stremio session to read history from — use the provider that just connected.
        setWatchHistorySource(provider);
    }

    if (!connected && currentSource() === provider) {
        setWatchHistorySource(firstConnectedSource());
    }

    syncAccountsNextButton();
}

function firstConnectedSource() {
    if (connectedState.stremio) return 'stremio';
    if (connectedState.trakt) return 'trakt';
    if (connectedState.simkl) return 'simkl';
    return 'stremio';
}

export function setWatchHistorySource(value) {
    const hidden = document.getElementById('watchHistorySource');
    if (hidden) hidden.value = value;
    document.querySelectorAll('.source-btn').forEach(btn => {
        applyActive(btn, btn.dataset.sourceBtn === value);
    });
}

function onSourceButtonClick(provider) {
    if (!connectedState[provider]) {
        showToast(`Connect ${PROVIDER_LABELS[provider]} in Accounts to use it as your watch history source.`, 'info', 4000);
        goToAccounts(provider);
        return;
    }
    setWatchHistorySource(provider);
}

function goToAccounts(scrollTo) {
    if (typeof switchSectionFn === 'function') {
        switchSectionFn('login');
    }
    if (scrollTo) {
        // Defer until the section is visible after switchSection completes.
        requestAnimationFrame(() => {
            const target = document.getElementById(`provider-${scrollTo}`);
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }
}

function syncAccountsNextButton() {
    const btn = document.getElementById('accountsNextBtn');
    if (!btn) return;
    btn.disabled = !(connectedState.stremio || connectedState.trakt || connectedState.simkl);
}

function setProviderView(provider, connected) {
    const disconnected = document.querySelector(`[data-provider-view="disconnected"][data-provider-for="${provider}"]`);
    const connectedEl = document.querySelector(`[data-provider-view="connected"][data-provider-for="${provider}"]`);
    if (disconnected) disconnected.classList.toggle('hidden', connected);
    if (connectedEl) connectedEl.classList.toggle('hidden', !connected);
}

function currentSource() {
    const hidden = document.getElementById('watchHistorySource');
    return hidden ? hidden.value : '';
}

function applyActive(btn, isActive) {
    btn.classList.remove(...ACTIVE_CLASSES, ...INACTIVE_CLASSES, ACTIVE_BORDER_CLASS, INACTIVE_BORDER_CLASS);
    if (isActive) {
        btn.classList.add(...ACTIVE_CLASSES, ACTIVE_BORDER_CLASS);
    } else {
        btn.classList.add(...INACTIVE_CLASSES, INACTIVE_BORDER_CLASS);
    }
}

function setProviderDot(provider, connected) {
    const dot = document.querySelector(`[data-account-dot="${provider}"]`);
    if (dot) {
        dot.classList.toggle('bg-green-400', connected);
        dot.classList.toggle('bg-slate-500', !connected);
    }

    const pip = document.querySelector(`[data-source-pip="${provider}"]`);
    if (pip) {
        pip.classList.toggle('bg-green-400', connected);
        pip.classList.toggle('bg-slate-600', !connected);
    }
}
