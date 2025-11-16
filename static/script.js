document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('configForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
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

    // Helper functions
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

    // Check if there's an encoded value in the URL path
    function checkForEncodedCredentials() {
        const path = window.location.pathname;
        // Check if path matches /{encoded}/configure
        const match = path.match(/^\/(.+)\/configure$/);
        if (match && match[1]) {
            const encoded = match[1];
            try {
                // Decode the credentials
                const decoded = atob(encoded);
                const credentials = JSON.parse(decoded);

                if (credentials.username && credentials.password) {
                    // Populate the form fields
                    usernameInput.value = credentials.username;
                    passwordInput.value = credentials.password;
                    // Optionally show a message that fields were pre-filled
                    console.log('Credentials loaded from URL');
                }
            } catch (error) {
                // Invalid encoding, ignore and show error
                console.error('Failed to decode credentials from URL:', error);
                showError('Invalid credentials in URL. Please enter your credentials manually.');
            }
        }
    }

    // Check for encoded credentials on page load
    checkForEncodedCredentials();

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        const username = usernameInput.value.trim();
        const password = passwordInput.value;

        if (!username || !password) {
            showError('Please fill in all fields');
            return;
        }

        // Hide error, show loading
        hideError();
        setLoading(true);

        try {
            // Encode credentials
            const credentials = {
                username: username,
                password: password
            };

            const encoded = btoa(JSON.stringify(credentials));

            // Get current origin
            const baseUrl = window.location.origin;
            const addonUrl = `${baseUrl}/${encoded}/manifest.json`;

            // Show success
            addonUrlInput.value = addonUrl;
            form.style.display = 'none';
            successMessage.style.display = 'block';

        } catch (error) {
            showError('An error occurred. Please try again.');
            console.error('Error:', error);
        } finally {
            setLoading(false);
        }
    });

    // Install on Stremio Desktop/Mobile
    installDesktopBtn.addEventListener('click', function () {
        const addonUrl = addonUrlInput.value;
        const stremioUrl = `stremio://${addonUrl.replace(/^https?:\/\//, '')}`;
        window.location.href = stremioUrl;
    });

    // Install on Stremio Web
    installWebBtn.addEventListener('click', function () {
        const addonUrl = encodeURIComponent(addonUrlInput.value);
        // Open Stremio web app with addon installation
        const stremioWebUrl = `https://web.stremio.com/#/addons?addon=${addonUrl}`;
        window.open(stremioWebUrl, '_blank');
    });

    // Copy URL to clipboard
    copyBtn.addEventListener('click', function () {
        addonUrlInput.select();
        addonUrlInput.setSelectionRange(0, 99999); // For mobile devices

        try {
            navigator.clipboard.writeText(addonUrlInput.value).then(function () {
                copyBtn.textContent = '✓ Copied!';
                copyBtn.classList.add('copied');

                setTimeout(function () {
                    copyBtn.textContent = '📋 Copy URL';
                    copyBtn.classList.remove('copied');
                }, 2000);
            });
        } catch (err) {
            // Fallback for older browsers
            document.execCommand('copy');
            copyBtn.textContent = '✓ Copied!';
            copyBtn.classList.add('copied');

            setTimeout(function () {
                copyBtn.textContent = '📋 Copy URL';
                copyBtn.classList.remove('copied');
            }, 2000);
        }
    });

    resetBtn.addEventListener('click', function () {
        form.reset();
        form.style.display = 'block';
        successMessage.style.display = 'none';
        hideError();
        usernameInput.focus();
    });
});

