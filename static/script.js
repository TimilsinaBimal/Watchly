// Default catalog configurations
const defaultCatalogs = [
    { id: 'watchly.rec', name: 'Recommended', enabled: true, description: 'Personalized recommendations based on your library' },
    { id: 'watchly.loved', name: 'Because you Loved', enabled: true, description: 'Recommendations based on most recent item you loved' },
    { id: 'watchly.watched', name: 'Because you Watched', enabled: true, description: 'Recommendations based on the most recent item you watched' },
    { id: 'watchly.genre', name: 'You might also Like', enabled: true, description: 'Recommendations based on your favorite genres' },
];

let catalogs = [...defaultCatalogs];

// DOM Elements
const configForm = document.getElementById('configForm');
const authMethod = document.getElementById('authMethod');
const credentialsFields = document.getElementById('credentialsFields');
const authKeyField = document.getElementById('authKeyField');
const catalogList = document.getElementById('catalogList');
const errorMessage = document.getElementById('errorMessage');
const successMessage = document.getElementById('successMessage');
const submitBtn = document.getElementById('submitBtn');
const btnText = submitBtn.querySelector('.btn-text');
const loader = submitBtn.querySelector('.loader');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initializeAuthMethodToggle();
    initializeCatalogList();
    initializeFormSubmission();
    initializeSuccessActions();
    initializePasswordToggles();
    initializeAuthHelp();
});

// Auth Method Toggle
function initializeAuthMethodToggle() {
    authMethod.addEventListener('change', (e) => {
        if (e.target.value === 'credentials') {
            credentialsFields.classList.remove('hidden');
            authKeyField.classList.add('hidden');
        } else {
            credentialsFields.classList.add('hidden');
            authKeyField.classList.remove('hidden');
        }
    });
}

// Password Toggles
function initializePasswordToggles() {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (input.type === 'password') {
                input.type = 'text';
                btn.textContent = 'Hide';
            } else {
                input.type = 'password';
                btn.textContent = 'Show';
            }
        });
    });
}

// Auth Help
function initializeAuthHelp() {
    const showAuthHelp = document.getElementById('showAuthHelp');
    if (showAuthHelp) {
        showAuthHelp.addEventListener('click', (e) => {
            e.preventDefault();
            alert('To find your Stremio Auth Key:\n\n1. Open web.strem.io in your browser\n2. Open Developer Tools (F12)\n3. Go to Application/Storage tab\n4. Click on Local Storage\n5. Find the "authKey" entry\n6. Copy the long string value');
        });
    }
}

// Catalog List
function initializeCatalogList() {
    renderCatalogList();
}

function renderCatalogList() {
    catalogList.innerHTML = '';

    catalogs.forEach((cat, index) => {
        const item = createCatalogItem(cat, index);
        catalogList.appendChild(item);
    });
}

function moveCatalogUp(index) {
    if (index === 0) return;

    // Swap in array
    [catalogs[index], catalogs[index - 1]] = [catalogs[index - 1], catalogs[index]];

    // Re-render
    renderCatalogList();
}

function moveCatalogDown(index) {
    if (index === catalogs.length - 1) return;

    // Swap in array
    [catalogs[index], catalogs[index + 1]] = [catalogs[index + 1], catalogs[index]];

    // Re-render
    renderCatalogList();
}

function createCatalogItem(cat, index) {
    const item = document.createElement('div');
    item.className = `catalog-item ${cat.enabled ? '' : 'disabled'}`;
    item.setAttribute('data-index', index);

    item.innerHTML = `
        <div class="catalog-header">
            <div class="sort-buttons">
                <button type="button" class="action-btn sort-btn move-up" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M18 15l-6-6-6 6"/>
                    </svg>
                </button>
                <button type="button" class="action-btn sort-btn move-down" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                </button>
            </div>
            <div class="name-container">
                <span class="catalog-name-text">${escapeHtml(cat.name)}</span>
                <input
                    type="text"
                    class="catalog-name-input hidden"
                    value="${escapeHtml(cat.name)}"
                >
                <button type="button" class="action-btn rename-btn" title="Rename">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                </button>
            </div>
            <label class="switch">
                <input type="checkbox" ${cat.enabled ? 'checked' : ''} data-catalog-id="${cat.id}">
                <span class="slider"></span>
            </label>
        </div>
        <div class="catalog-desc">${escapeHtml(cat.description || '')}</div>
    `;

    // Setup rename functionality
    setupRenameLogic(item, cat);

    // Setup switch toggle
    const switchInput = item.querySelector('.switch input');
    switchInput.addEventListener('change', (e) => {
        cat.enabled = e.target.checked;
        item.classList.toggle('disabled', !cat.enabled);
    });

    // Setup sort buttons
    const moveUpBtn = item.querySelector('.move-up');
    const moveDownBtn = item.querySelector('.move-down');

    moveUpBtn.addEventListener('click', (e) => {
        e.preventDefault();
        moveCatalogUp(index);
    });

    moveDownBtn.addEventListener('click', (e) => {
        e.preventDefault();
        moveCatalogDown(index);
    });

    return item;
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');

    // Create edit action buttons dynamically
    const editActions = document.createElement('div');
    editActions.className = 'edit-actions';
    editActions.innerHTML = `
        <button type="button" class="edit-btn save" title="Save">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </button>
        <button type="button" class="edit-btn cancel" title="Cancel">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
    `;
    nameContainer.appendChild(editActions);

    const saveBtn = editActions.querySelector('.save');
    const cancelBtn = editActions.querySelector('.cancel');

    function enableEdit() {
        nameContainer.classList.add('editing');
        nameText.classList.add('hidden');
        nameInput.classList.remove('hidden');
        renameBtn.style.visibility = 'hidden';
        nameInput.focus();
        const len = nameInput.value.length;
        nameInput.setSelectionRange(len, len);
    }

    function saveEdit() {
        const newName = nameInput.value.trim();
        if (newName) {
            cat.name = newName;
            nameText.textContent = newName;
            nameInput.value = newName;
        } else {
            nameInput.value = cat.name; // Revert if empty
        }
        closeEdit();
    }

    function cancelEdit() {
        nameInput.value = cat.name; // Revert value
        closeEdit();
    }

    function closeEdit() {
        nameContainer.classList.remove('editing');
        nameInput.classList.add('hidden');
        nameText.classList.remove('hidden');
        renameBtn.style.visibility = 'visible';
    }

    renameBtn.addEventListener('click', (e) => {
        e.preventDefault();
        enableEdit();
    });

    saveBtn.addEventListener('click', (e) => {
        e.preventDefault();
        saveEdit();
    });

    cancelBtn.addEventListener('click', (e) => {
        e.preventDefault();
        cancelEdit();
    });

    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveEdit();
        } else if (e.key === 'Escape') {
            cancelEdit();
        }
    });
}

// Form Submission
function initializeFormSubmission() {
    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const authMethodValue = authMethod.value;
        const username = document.getElementById('username')?.value.trim();
        const password = document.getElementById('password')?.value;
        const authKey = document.getElementById('authKey')?.value.trim();
        const recommendationSource = document.querySelector('input[name="recommendationSource"]:checked')?.value;

        // Validation
        if (authMethodValue === 'credentials') {
            if (!username || !password) {
                showError('Please provide both email and password.');
                return;
            }
        } else {
            if (!authKey) {
                showError('Please provide your Stremio auth key.');
                return;
            }
        }

        // Prepare catalog configs
        const catalogConfigs = catalogs.map(cat => ({
            id: cat.id,
            name: cat.name !== getDefaultCatalogName(cat.id) ? cat.name : null,
            enabled: cat.enabled
        }));

        // Prepare payload
        const payload = {
            includeWatched: recommendationSource === 'watched',
            catalogs: catalogConfigs
        };

        if (authMethodValue === 'credentials') {
            payload.username = username;
            payload.password = password;
        } else {
            payload.authKey = authKey;
        }

        // Submit
        setLoading(true);
        hideError();

        try {
            const response = await fetch('/tokens/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to create token');
            }

            showSuccess(data.manifestUrl);
        } catch (error) {
            showError(error.message || 'An error occurred. Please try again.');
        } finally {
            setLoading(false);
        }
    });
}

function getDefaultCatalogName(id) {
    const defaultCat = defaultCatalogs.find(c => c.id === id);
    return defaultCat ? defaultCat.name : '';
}

// Success Actions
function initializeSuccessActions() {
    const installDesktopBtn = document.getElementById('installDesktopBtn');
    const installWebBtn = document.getElementById('installWebBtn');
    const copyBtn = document.getElementById('copyBtn');
    const resetBtn = document.getElementById('resetBtn');

    if (installDesktopBtn) {
        installDesktopBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.location.href = `stremio://${url.replace(/^https?:\/\//, '')}`;
        });
    }

    if (installWebBtn) {
        installWebBtn.addEventListener('click', () => {
            const url = document.getElementById('addonUrl').textContent;
            window.open(`https://www.strem.io/s/addons?addon=${encodeURIComponent(url)}`, '_blank');
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
            const url = document.getElementById('addonUrl').textContent;
            try {
                await navigator.clipboard.writeText(url);
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    Copied!
                `;
                setTimeout(() => {
                    copyBtn.innerHTML = originalText;
                }, 2000);
            } catch (err) {
                showError('Failed to copy URL');
            }
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            configForm.reset();
            catalogs = [...defaultCatalogs];
            renderCatalogList();
            configForm.style.display = 'block';
            successMessage.style.display = 'none';
            hideError();
        });
    }
}

// UI Helpers
function setLoading(loading) {
    submitBtn.disabled = loading;
    if (loading) {
        btnText.style.opacity = '0';
        loader.classList.remove('hidden');
    } else {
        btnText.style.opacity = '1';
        loader.classList.add('hidden');
    }
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
}

function hideError() {
    errorMessage.style.display = 'none';
}

function showSuccess(manifestUrl) {
    configForm.style.display = 'none';
    successMessage.style.display = 'block';
    document.getElementById('addonUrl').textContent = manifestUrl;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
