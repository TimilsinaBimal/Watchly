const LOADING_ICON = '<svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

export function setValidationMessage(validationMessage, message, type) {
    if (!validationMessage) return;
    validationMessage.textContent = message;
    validationMessage.className = `mt-2 text-xs ${type === 'success' ? 'text-green-400' : 'text-red-400'}`;
    validationMessage.classList.remove('hidden');
}

export function clearValidationMessage(validationMessage) {
    if (validationMessage) {
        validationMessage.classList.add('hidden');
    }
}

export function initializeEyeToggle({ input, toggleBtn, eyeIcon, eyeOffIcon }) {
    if (!input || !toggleBtn || !eyeIcon || !eyeOffIcon) return;

    toggleBtn.addEventListener('click', () => {
        // A saved key reaches the page as an opaque marker, never the key itself,
        // so there is nothing worth revealing — showing it would just leak an
        // internal string at the user.
        if (input.value === window.STORED_SECRET) return;

        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        eyeIcon.classList.toggle('hidden', !isPassword);
        eyeOffIcon.classList.toggle('hidden', isPassword);
    });
}

// Fields holding a saved key show its last few characters instead of the key, so
// the user can tell which one is on file. The reveal button is hidden until they
// start typing a replacement, since there is nothing to reveal before then.
export function markFieldAsSaved({ input, toggleBtn, hintEl, hint }) {
    if (!input) return;

    input.value = window.STORED_SECRET;
    input.type = 'password';
    if (toggleBtn) toggleBtn.classList.add('hidden');

    if (hintEl) {
        hintEl.textContent = hint
            ? `Saved key ending …${hint}. Type to replace it, or clear the field to remove it.`
            : 'A saved key is in use. Type to replace it, or clear the field to remove it.';
        hintEl.className = 'mt-2 text-xs text-slate-500';
    }

    const onEdit = () => {
        if (input.value === window.STORED_SECRET) return;
        if (toggleBtn) toggleBtn.classList.remove('hidden');
        if (hintEl) hintEl.classList.add('hidden');
        input.removeEventListener('input', onEdit);
    };
    input.addEventListener('input', onEdit);
}

export function initializePasswordToggleButton(selector = '.toggle-btn') {
    document.querySelectorAll(selector).forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (!input) return;
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            if (isHidden) {
                btn.setAttribute('title', 'Hide');
                btn.setAttribute('aria-label', 'Hide password');
                btn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a21.77 21.77 0 0 1 5.06-6.17M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a21.8 21.8 0 0 1-3.22 4.31"/><path d="M1 1l22 22"/><path d="M14.12 14.12A3 3 0 0 1 9.88 9.88"/></svg>';
            } else {
                btn.setAttribute('title', 'Show');
                btn.setAttribute('aria-label', 'Show password');
                btn.innerHTML = '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';
            }
        });
    });
}

export function initializeValidatedSecretField({
    input,
    validateBtn,
    validationMessage,
    toggleBtn,
    eyeIcon,
    eyeOffIcon,
    emptyMessage,
    successMessage,
    request,
    getErrorMessage,
    onValid,
    onInvalid,
    onErrorMessage = 'Validation failed. Please try again.'
}) {
    if (!input || !validateBtn || !validationMessage) {
        return async () => false;
    }

    initializeEyeToggle({ input, toggleBtn, eyeIcon, eyeOffIcon });

    async function validate() {
        const value = input.value.trim();
        if (!value) {
            setValidationMessage(validationMessage, emptyMessage, 'error');
            return false;
        }

        if (value === window.STORED_SECRET) {
            // Placeholder for the saved key, which the server never sends back.
            setValidationMessage(validationMessage, 'Using your saved key', 'success');
            return true;
        }

        validateBtn.disabled = true;
        validateBtn.classList.add('opacity-50', 'cursor-not-allowed');
        const originalHTML = validateBtn.innerHTML;
        validateBtn.innerHTML = LOADING_ICON;

        try {
            const data = await request(value);
            if (data.valid) {
                setValidationMessage(validationMessage, successMessage, 'success');
                if (onValid) onValid(data);
                return true;
            }

            setValidationMessage(validationMessage, getErrorMessage ? getErrorMessage(data) : 'Invalid API key', 'error');
            if (onInvalid) onInvalid(data);
            return false;
        } catch (error) {
            setValidationMessage(validationMessage, onErrorMessage, 'error');
            return false;
        } finally {
            validateBtn.disabled = false;
            validateBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            validateBtn.innerHTML = originalHTML;
        }
    }

    validateBtn.addEventListener('click', validate);
    input.addEventListener('input', () => clearValidationMessage(validationMessage));

    return validate;
}
