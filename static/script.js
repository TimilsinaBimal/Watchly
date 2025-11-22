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
    const addonUrlBox = document.getElementById('addonUrl');
    const copyBtn = document.getElementById('copyBtn');
    const installDesktopBtn = document.getElementById('installDesktopBtn');
    const installWebBtn = document.getElementById('installWebBtn');
    const resetBtn = document.getElementById('resetBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnLoader = submitBtn.querySelector('.loader');
    const toggleButtons = document.querySelectorAll('.toggle-btn');

    // Store the raw URL string since div doesn't have .value
    let generatedUrl = '';

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
    }

    function hideError() {
        errorMessage.style.display = 'none';
    }

    function setLoading(loading) {
        submitBtn.disabled = loading;
        if (loading) {
            btnText.classList.add('hidden');
            btnLoader.classList.remove('hidden');
        } else {
            btnText.classList.remove('hidden');
            btnLoader.classList.add('hidden');
        }
    }

    function updateMethodFields() {
        const method = authMethodSelect.value;
        if (method === 'credentials') {
            credentialsFields.classList.remove('hidden');
            authKeyFieldWrapper.classList.add('hidden');
            usernameInput.required = true;
            passwordInput.required = true;
            authKeyInput.required = false;
        } else {
            credentialsFields.classList.add('hidden');
            authKeyFieldWrapper.classList.remove('hidden');
            usernameInput.required = false;
            passwordInput.required = false;
            authKeyInput.required = true;
        }
    }

    authMethodSelect.addEventListener('change', () => {
        updateMethodFields();
        hideError();
    });

    // Password/AuthKey Visibility Toggles
    toggleButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (input) {
                const isPassword = input.type === 'password';
                input.type = isPassword ? 'text' : 'password';
                btn.textContent = isPassword ? 'Hide' : 'Show';
            }
        });
    });

    // Help Alert for Auth Key
    const showAuthHelp = document.getElementById('showAuthHelp');
    if (showAuthHelp) {
        showAuthHelp.addEventListener('click', (e) => {
            e.preventDefault();
            alert('To find your Auth Key:\n1. Go to web.strem.io\n2. Open Console (F12)\n3. Type: JSON.parse(localStorage.getItem("profile")).auth.key\n4. Copy the result (without quotes)');
        });
    }

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        hideError();

        const method = authMethodSelect.value;
        const username = usernameInput.value.trim();
        const password = passwordInput.value;
        const authKey = authKeyInput.value.trim();
        const includeWatched = document.querySelector('input[name="recommendationSource"]:checked').value === 'watched';

        // Client-side validation
        if (method === 'credentials') {
            if (!username || !password) {
                showError('Please enter both email and password.');
                return;
            }
        } else if (!authKey) {
            showError('Please provide your Stremio Auth Key.');
            return;
        }

        setLoading(true);

        try {
            const response = await fetch('/tokens/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: method === 'credentials' ? username : null,
                    password: method === 'credentials' ? password : null,
                    authKey: method === 'authkey' ? authKey : null,
                    includeWatched
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to create token.' }));
                throw new Error(errorData.detail || 'Failed to connect. Check credentials.');
            }

            const data = await response.json();
            generatedUrl = data.manifestUrl;
            addonUrlBox.textContent = generatedUrl;

            form.classList.add('hidden');
            successMessage.style.display = 'block';

        } catch (error) {
            console.error('Error:', error);
            showError(error.message);
        } finally {
            setLoading(false);
        }
    });

    installDesktopBtn.addEventListener('click', function () {
        if (!generatedUrl) return;
        const stremioUrl = `stremio://${generatedUrl.replace(/^https?:\/\//, '')}`;
        window.location.href = stremioUrl;
    });

    installWebBtn.addEventListener('click', function () {
        if (!generatedUrl) return;
        const stremioUrl = `https://web.stremio.com/#/addons?addon=${encodeURIComponent(generatedUrl)}`;
        window.open(stremioUrl, '_blank');
    });

    copyBtn.addEventListener('click', async function () {
        if (!generatedUrl) return;

        try {
            await navigator.clipboard.writeText(generatedUrl);
            const originalText = copyBtn.textContent;
            copyBtn.textContent = 'Copied!';
            copyBtn.classList.add('btn-primary');
            copyBtn.classList.remove('btn-outline');

            setTimeout(() => {
                copyBtn.textContent = originalText;
                copyBtn.classList.remove('btn-primary');
                copyBtn.classList.add('btn-outline');
            }, 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
            showError('Failed to copy to clipboard');
        }
    });

    resetBtn.addEventListener('click', function () {
        form.reset();
        authMethodSelect.value = 'credentials';
        updateMethodFields();

        form.classList.remove('hidden');
        successMessage.style.display = 'none';
        hideError();
        generatedUrl = '';
        addonUrlBox.textContent = '';
    });

    // Initialize
    updateMethodFields();
});
