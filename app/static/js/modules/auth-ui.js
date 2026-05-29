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
    const loginStatusEmail = document.getElementById('loginStatusEmail');
    const loginStatusAvatar = document.getElementById('loginStatusAvatar');

    const initials = getInitialsFromEmail(email);

    if (userProfileWrapper && userEmail && userAvatar) {
        userEmail.textContent = email;
        userAvatar.textContent = initials;
        userProfileWrapper.classList.remove('hidden');
    }

    if (loginStatusEmail) loginStatusEmail.textContent = email;
    if (loginStatusAvatar) loginStatusAvatar.textContent = initials;
}

export function hideUserProfile() {
    const userProfileWrapper = document.getElementById('user-profile-dropdown-wrapper');
    const dropdown = document.getElementById('user-profile-dropdown');

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
}

export function renderLoggedInControls({ authKey }) {
    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = authKey || '';
}

export function renderLoggedOutControls({ emailInput, passwordInput }) {
    const authKeyInput = document.getElementById('authKey');
    if (authKeyInput) authKeyInput.value = '';

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
