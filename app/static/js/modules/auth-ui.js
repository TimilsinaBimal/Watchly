function getInitialsFromEmail(email) {
    if (!email) return '?';

    const username = email.split('@')[0];
    const parts = username.split(/[._-]/);

    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return username.substring(0, 2).toUpperCase();
}

export function updateInstallMode(existingUser) {
    const installHeader = document.querySelector('#sect-install h2');
    const installDesc = document.querySelector('#sect-install p');
    const btnText = document.querySelector('#submitBtn .btn-text');

    if (existingUser) {
        if (installHeader) installHeader.textContent = 'Update Settings';
        if (installDesc) installDesc.textContent = 'Update your preferences and re-install.';
        if (btnText) btnText.textContent = 'Update & Re-Install';
        return;
    }

    if (installHeader) installHeader.textContent = 'Save & Install';
    if (installDesc) installDesc.textContent = 'Save your settings and install the addon.';
    if (btnText) btnText.textContent = 'Save & Install';
}

export function showUserProfile(email) {
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const userEmail = document.getElementById('user-email');
    const userAvatar = document.getElementById('user-avatar');
    const loginStatusSection = document.getElementById('loginStatusSection');
    const loginStatusEmail = document.getElementById('loginStatusEmail');
    const loginStatusAvatar = document.getElementById('loginStatusAvatar');

    if (!userProfileWrapper || !userEmail || !userAvatar) return;

    const initials = getInitialsFromEmail(email);
    userEmail.textContent = email;
    userAvatar.textContent = initials;
    userProfileWrapper.classList.remove('hidden');

    if (loginStatusSection && loginStatusEmail && loginStatusAvatar) {
        loginStatusEmail.textContent = email;
        loginStatusAvatar.textContent = initials;
        loginStatusSection.classList.remove('hidden');
    }

    const loginFormCard = document.getElementById('loginFormCard');
    if (loginFormCard) loginFormCard.classList.add('hidden');
}

export function hideUserProfile() {
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const dropdown = document.getElementById('user-profile-dropdown');
    const loginStatusSection = document.getElementById('loginStatusSection');

    if (userProfileWrapper) {
        userProfileWrapper.classList.add('hidden');
    }

    if (dropdown) {
        dropdown.classList.add('hidden');
        const chevron = document.getElementById('user-profile-chevron');
        if (chevron) {
            chevron.style.transform = 'rotate(0deg)';
        }
    }

    if (loginStatusSection) {
        loginStatusSection.classList.add('hidden');
    }

    const loginFormCard = document.getElementById('loginFormCard');
    if (loginFormCard) loginFormCard.classList.remove('hidden');
}

export function renderLoggedInControls({ stremioLoginBtn, stremioLoginText, authKey }) {
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Logout';
    stremioLoginBtn.setAttribute('data-action', 'logout');
    stremioLoginBtn.classList.remove('bg-stremio', 'hover:bg-stremio-hover', 'hover:bg-white', 'hover:text-black', 'hover:border-white/10', 'border-stremio-border');
    stremioLoginBtn.classList.add('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20', 'text-white');

    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = authKey;

    const emailPwdSection = document.getElementById('emailPwdSection');
    const disclaimer = document.getElementById('emailPwdDisclaimer');
    const divider = document.getElementById('emailPwdDivider');
    if (emailPwdSection) emailPwdSection.classList.add('hidden');
    if (disclaimer) disclaimer.classList.add('hidden');
    if (divider) divider.classList.add('hidden');
}

export function renderLoggedOutControls({ stremioLoginBtn, stremioLoginText, emailInput, passwordInput }) {
    if (!stremioLoginBtn) return;
    stremioLoginText.textContent = 'Login with Stremio';
    stremioLoginBtn.removeAttribute('data-action');
    stremioLoginBtn.classList.add('bg-stremio', 'hover:bg-white', 'hover:text-black', 'hover:border-white/10', 'border-stremio-border', 'text-white');
    stremioLoginBtn.classList.remove('bg-red-600', 'hover:bg-red-700', 'border-red-700', 'shadow-red-900/20');

    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = '';

    const emailPwdSection = document.getElementById('emailPwdSection');
    const disclaimer = document.getElementById('emailPwdDisclaimer');
    const divider = document.getElementById('emailPwdDivider');
    if (emailPwdSection) emailPwdSection.classList.remove('hidden');
    if (disclaimer) disclaimer.classList.remove('hidden');
    if (divider) divider.classList.remove('hidden');
    if (emailInput) emailInput.value = '';
    if (passwordInput) passwordInput.value = '';

    const toggleBtn = document.querySelector('.toggle-btn[data-target="passwordInput"]');
    const pwd = document.getElementById('passwordInput');
    if (toggleBtn && pwd) {
        pwd.type = 'password';
        toggleBtn.setAttribute('title', 'Show');
        toggleBtn.setAttribute('aria-label', 'Show password');
        toggleBtn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';
    }
}
