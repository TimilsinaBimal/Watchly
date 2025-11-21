document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('configForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const authKeyInput = document.getElementById('authKey');
    const authMethodSelect = document.getElementById('authMethod');
    const credentialsFields = document.getElementById('credentialsFields');
    const authKeyFieldWrapper = document.getElementById('authKeyField');
    const submitBtn = document.getElementById('submitBtn');
    const errorMessage = document.getElementById('errorMessage');
    const successMessage = document.getElementById('successMessage');
    const addonUrlInput = document.getElementById('addonUrl');
    const copyBtn = document.getElementById('copyBtn');
    const installDesktopBtn = document.getElementById('installDesktopBtn');
    const installWebBtn = document.getElementById('installWebBtn');
    const resetBtn = document.getElementById('resetBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoader = submitBtn.querySelector('.btn-loader');
    const toggleButtons = document.querySelectorAll('.toggle-visibility');

    const methodFieldMap = {
        credentials: credentialsFields,
        authkey: authKeyFieldWrapper
    };

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
    }

    function hideError() {
        errorMessage.style.display = 'none';
    }

    function setLoading(loading) {
        if (loading) {
            submitBtn.disabled = true;
            btnText.style.display = 'none';
            btnLoader.style.display = 'inline';
        } else {
            submitBtn.disabled = false;
            btnText.style.display = 'inline';
            btnLoader.style.display = 'none';
        }
    }

    function updateMethodFields() {
        const method = authMethodSelect.value;
        Object.entries(methodFieldMap).forEach(([key, element]) => {
            if (!element) {
                return;
            }
            const isActive = key === method;
            element.style.display = isActive ? 'block' : 'none';
            element.style.opacity = isActive ? '1' : '0';
            element.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        });

        const requiresCredentials = method === 'credentials';
        usernameInput.required = requiresCredentials;
        passwordInput.required = requiresCredentials;
        authKeyInput.required = !requiresCredentials;
    }

    authMethodSelect.addEventListener('change', () => {
        updateMethodFields();
        hideError();
    });

    updateMethodFields();

    const radioInputs = document.querySelectorAll('input[name="recommendationSource"]');
    radioInputs.forEach(radio => {
        radio.addEventListener('change', function () {
            document.querySelectorAll('.radio-label').forEach(label => {
                label.classList.remove('checked');
            });
            if (this.checked) {
                this.closest('.radio-label')?.classList.add('checked');
            }
        });
        if (radio.checked) {
            radio.closest('.radio-label')?.classList.add('checked');
        }
    });

    function synchronizeToggle(button, input) {
        if (!button || !input) {
            return;
        }
        const isHidden = input.getAttribute('type') === 'password';
        button.textContent = isHidden ? 'Show' : 'Hide';
        button.setAttribute('aria-pressed', (!isHidden).toString());
        button.setAttribute('aria-label', isHidden ? 'Show value' : 'Hide value');
        button.dataset.visible = (!isHidden).toString();
    }

    toggleButtons.forEach(button => {
        const targetId = button.dataset.toggleTarget;
        const targetInput = document.getElementById(targetId);
        synchronizeToggle(button, targetInput);
        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (!targetInput) {
                return;
            }
            const isHidden = targetInput.getAttribute('type') === 'password';
            targetInput.setAttribute('type', isHidden ? 'text' : 'password');
            synchronizeToggle(button, targetInput);
            targetInput.focus();
        });
    });

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        const method = authMethodSelect.value;
        const username = usernameInput.value.trim();
        const password = passwordInput.value;
        const authKey = authKeyInput.value.trim();
        const includeWatched = document.querySelector('input[name="recommendationSource"]:checked').value === 'watched';

        if (method === 'credentials') {
            if (!username || !password) {
                showError('Enter both your Stremio username/email and password to continue.');
                return;
            }
        } else if (method === 'authkey') {
            if (!authKey) {
                showError('Provide your Stremio auth key to continue.');
                return;
            }
        } else if ((!username || !password) && !authKey) {
            showError('Provide either a username/password pair or a Stremio auth key.');
            return;
        }

        hideError();
        setLoading(true);

        try {
            const response = await fetch('/tokens/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    username: method === 'credentials' ? username : null,
                    password: method === 'credentials' ? password : null,
                    authKey: method === 'authkey' ? authKey : null,
                    includeWatched
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to create token.' }));
                throw new Error(errorData.detail || 'Failed to create token.');
            }

            const data = await response.json();
            addonUrlInput.value = data.manifestUrl;
            form.style.display = 'none';
            successMessage.style.display = 'block';
        } catch (error) {
            console.error('Error creating token', error);
            showError(error.message || 'An unexpected error occurred.');
        } finally {
            setLoading(false);
        }
    });

    installDesktopBtn.addEventListener('click', function () {
        const addonUrl = addonUrlInput.value;
        if (!addonUrl) {
            return;
        }
        const stremioUrl = `stremio://${addonUrl.replace(/^https?:\/\//, '')}`;
        window.location.href = stremioUrl;
    });

    installWebBtn.addEventListener('click', function () {
        const addonUrl = addonUrlInput.value;
        if (!addonUrl) {
            return;
        }
        const stremioUrl = `https://web.stremio.com/#/addons?addon=${encodeURIComponent(addonUrl)}`;
        window.open(stremioUrl, '_blank');
    });

    copyBtn.addEventListener('click', function () {
        if (!addonUrlInput.value) {
            return;
        }
        addonUrlInput.select();
        addonUrlInput.setSelectionRange(0, 99999);

        const handleCopied = () => {
            copyBtn.textContent = '✓ Copied!';
            copyBtn.classList.add('copied');
            setTimeout(function () {
                copyBtn.textContent = '📋 Copy URL';
                copyBtn.classList.remove('copied');
            }, 2000);
        };

        if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(addonUrlInput.value).then(handleCopied);
        } else {
            document.execCommand('copy');
            handleCopied();
        }
    });

    resetBtn.addEventListener('click', function () {
        form.reset();
        authMethodSelect.value = 'credentials';
        updateMethodFields();
        form.style.display = 'block';
        successMessage.style.display = 'none';
        hideError();
        usernameInput.focus();
        document.querySelectorAll('.radio-label').forEach(label => {
            label.classList.remove('checked');
        });
        document.querySelector('input[name="recommendationSource"][value="loved"]').closest('.radio-label').classList.add('checked');
    });

});

