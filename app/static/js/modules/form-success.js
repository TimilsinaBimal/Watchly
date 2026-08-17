import { showConfirm, showToast } from './ui.js';
import { switchSection } from './navigation.js';
import { openNuvioInstall } from './nuvio.js';

let preparedInstallations = [];

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

    const installAllProfilesBtn = document.getElementById('installAllProfilesBtn');
    if (installAllProfilesBtn) {
        installAllProfilesBtn.addEventListener('click', async () => {
            const pending = preparedInstallations.filter(installation => !installation.installed);
            if (!pending.length) return;

            installAllProfilesBtn.disabled = true;
            try {
                for (let index = 0; index < pending.length; index += 1) {
                    const installation = pending[index];
                    installAllProfilesBtn.textContent = `Installing ${index + 1} of ${pending.length}…`;
                    const response = await fetch('/stremio/profiles/install-addon', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            authKey: installation.authKey,
                            profile_id: installation.profileId,
                            manifest_url: installation.url,
                        }),
                    });
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(`${installation.profileName}: ${error.detail || 'Installation failed'}`);
                    }
                    installation.installed = true;
                    if (installation.statusElement) {
                        installation.statusElement.textContent = 'Installed in this profile';
                        installation.statusElement.className = 'text-xs text-green-400 mt-1';
                    }
                }
                installAllProfilesBtn.textContent = 'Installed in all profiles';
                showToast('Watchly was installed in every Stremio profile.', 'success', 5000);
            } catch (error) {
                installAllProfilesBtn.disabled = false;
                installAllProfilesBtn.textContent = 'Retry remaining profiles';
                showToast(error.message, 'error', 6000);
            }
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

export function showSuccessSection(result) {
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
        const installations = Array.isArray(result) ? result : [];
        const isBatch = installations.length > 1;
        const singleInstall = document.getElementById('singleAddonInstall');
        const profileInstances = document.getElementById('profileAddonInstances');
        const profileBatchInstall = document.getElementById('profileBatchInstall');
        const description = document.getElementById('successDescription');

        singleInstall?.classList.toggle('hidden', isBatch);
        profileInstances?.classList.toggle('hidden', !isBatch);
        profileBatchInstall?.classList.toggle('hidden', !isBatch);
        preparedInstallations = isBatch ? installations : [];
        if (isBatch) {
            if (description) {
                description.textContent = `${installations.length} profile-specific instances are ready.`;
            }
            const installAllProfilesBtn = document.getElementById('installAllProfilesBtn');
            if (installAllProfilesBtn) {
                installAllProfilesBtn.disabled = false;
                installAllProfilesBtn.textContent = 'Install all profiles in Stremio';
            }
            renderProfileInstallations(profileInstances, installations);
        } else {
            if (description) description.textContent = 'Your personalized catalog is ready.';
            document.getElementById('addonUrl').textContent = result;
            profileInstances?.replaceChildren();
        }
    }
}

function renderProfileInstallations(container, installations) {
    if (!container) return;
    container.replaceChildren();

    installations.forEach(installation => {
        const row = document.createElement('div');
        const details = document.createElement('div');
        const name = document.createElement('div');
        const metadata = document.createElement('div');
        const actions = document.createElement('div');
        const appButton = createInstallButton('App', true);
        const webButton = createInstallButton('Web');
        const copyButton = createInstallButton('Copy');

        row.className = 'py-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between';
        details.className = 'min-w-0';
        name.className = 'text-sm font-semibold text-white truncate';
        metadata.className = 'text-xs text-slate-500 mt-1';
        actions.className = 'flex gap-2 flex-shrink-0';
        name.textContent = `Watchly - ${installation.profileName}`;
        metadata.textContent = 'Private profile-specific manifest';
        installation.statusElement = metadata;

        appButton.addEventListener('click', () => {
            window.location.href = `stremio://${installation.url.replace(/^https?:\/\//, '')}`;
        });
        webButton.addEventListener('click', () => {
            window.open(`https://web.stremio.com/#/addons?addon=${encodeURIComponent(installation.url)}`, '_blank');
        });
        copyButton.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(installation.url);
                copyButton.textContent = 'Copied';
                setTimeout(() => { copyButton.textContent = 'Copy'; }, 2000);
            } catch (error) { /* noop */ }
        });

        details.append(name, metadata);
        actions.append(appButton, webButton, copyButton);
        row.append(details, actions);
        container.append(row);
    });
}

function createInstallButton(label, primary = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.className = primary
        ? 'bg-white text-black hover:bg-white/90 text-sm font-medium px-4 py-2 rounded-lg transition'
        : 'bg-neutral-800 text-slate-200 hover:bg-neutral-700 text-sm font-medium px-4 py-2 rounded-lg transition';
    return button;
}
