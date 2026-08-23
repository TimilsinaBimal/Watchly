import { showConfirm, showToast } from './ui.js';
import { switchSection } from './navigation.js';
import { openNuvioInstall } from './nuvio.js';

export function initializeSuccessActions({ emailInput, passwordInput, resetApp, setLoading, showError }) {
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const urlText = document.getElementById('addonUrl').textContent;
            try {
                await navigator.clipboard.writeText(urlText);
                const originalText = copyBtn.textContent;
                copyBtn.textContent = 'Copied!';
                setTimeout(() => { copyBtn.textContent = originalText; }, 2000);
            } catch (err) { /* noop */ }
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

    const installNuvioBtn = document.getElementById('installNuvioBtn');
    if (installNuvioBtn) {
        installNuvioBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openNuvioInstall(document.getElementById('addonUrl').textContent);
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

            const sAuthKey = (document.getElementById('authKey').value || '').trim();
            const email = emailInput?.value.trim();
            const password = passwordInput?.value;

            if (!sAuthKey && !(email && password)) {
                showError('generalError', 'Provide Stremio auth key or email & password to delete your account.');
                switchSection('login');
                return;
            }

            setLoading(true);
            try {
                const payload = { authKey: sAuthKey || undefined, email: email || undefined, password: password || undefined };
                const res = await fetch('/tokens/', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
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

// Warm-up states in the order the server reports them, with the share of the bar
// each one represents. Anything unrecognised leaves the bar where it is.
const WARM_STEPS = {
    pending: { pct: 10, label: 'Saving your configuration…' },
    building_profile: { pct: 35, label: 'Reading your watch history…' },
    profile_ready: { pct: 60, label: 'Building your taste profile…' },
    warming_manifest: { pct: 75, label: 'Assembling your catalogs…' },
    warming_catalogs: { pct: 90, label: 'Picking your first recommendations…' },
};

const POLL_INTERVAL_MS = 2500;
// Warm-up holds a Redis lock for 15 minutes; past that something is wrong and the
// user is better off with the URL than an endless spinner.
const POLL_TIMEOUT_MS = 15 * 60 * 1000;

let pollTimer = null;

export function stopWarmPolling() {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
}

function revealInstall(message) {
    stopWarmPolling();
    const progress = document.getElementById('warmProgress');
    const payload = document.getElementById('successPayload');
    if (progress) progress.classList.add('hidden');
    if (payload) payload.classList.remove('hidden');

    const subheading = document.getElementById('successSubheading');
    if (subheading && message) subheading.textContent = message;
}

function renderWarmState(status) {
    const step = WARM_STEPS[status.state];
    if (!step) return;

    const label = document.getElementById('warmProgressLabel');
    const bar = document.getElementById('warmProgressBar');
    const detail = document.getElementById('warmProgressDetail');
    if (label) label.textContent = step.label;
    if (bar) bar.style.width = `${step.pct}%`;
    if (detail) detail.textContent = status.detail || '';
}

function pollWarmStatus(token, deadline) {
    pollTimer = setTimeout(async () => {
        // Checked here rather than hooked into navigation, which would mean
        // navigation importing this module while this one already imports it.
        // This also covers any route off the page, including ones added later.
        const section = document.getElementById('sect-success');
        if (!section || section.classList.contains('hidden')) {
            stopWarmPolling();
            return;
        }

        if (Date.now() > deadline) {
            revealInstall('Setup is taking a while — your URL works, and the rest finishes in the background.');
            return;
        }

        try {
            const res = await fetch(`/${token}/status`);
            const status = res.ok ? await res.json() : { state: 'unknown' };

            if (status.state === 'ready') {
                revealInstall('Your personalized catalog is ready.');
                return;
            }
            if (status.state === 'error') {
                // The account is saved either way; the rows just build on first use.
                revealInstall('Your URL is ready. We\'ll finish preparing your rows when you first open it.');
                return;
            }
            renderWarmState(status);
        } catch (e) {
            console.warn('Warm-up status check failed:', e);
        }

        pollWarmStatus(token, deadline);
    }, POLL_INTERVAL_MS);
}

export function showSuccessSection(url, token) {
    const sections = {
        welcome: document.getElementById('sect-welcome'),
        login: document.getElementById('sect-login'),
        config: document.getElementById('sect-config'),
        catalogs: document.getElementById('sect-catalogs'),
        install: document.getElementById('sect-install'),
        success: document.getElementById('sect-success')
    };

    Object.values(sections).forEach(section => {
        if (section) section.classList.add('hidden');
    });

    if (!sections.success) return;

    sections.success.classList.remove('hidden');
    document.getElementById('addonUrl').textContent = url;

    stopWarmPolling();

    // Without a token we can't track progress, so just show the URL — the rows
    // build on first request as they always did.
    if (!token) {
        revealInstall();
        return;
    }

    const progress = document.getElementById('warmProgress');
    const payload = document.getElementById('successPayload');
    const heading = document.getElementById('successHeading');
    const subheading = document.getElementById('successSubheading');
    if (progress) progress.classList.remove('hidden');
    if (payload) payload.classList.add('hidden');
    if (heading) heading.textContent = 'Almost there';
    if (subheading) subheading.textContent = 'Getting your recommendations ready before you install.';

    renderWarmState({ state: 'pending' });
    pollWarmStatus(token, Date.now() + POLL_TIMEOUT_MS);
}
