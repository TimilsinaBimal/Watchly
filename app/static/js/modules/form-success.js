import { showConfirm, showToast } from './ui.js';
import { switchSection } from './navigation.js';

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

export function showSuccessSection(url) {
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

    if (sections.success) {
        sections.success.classList.remove('hidden');
        document.getElementById('addonUrl').textContent = url;
    }
}
