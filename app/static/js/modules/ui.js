// UI Utilities: Toasts, Modals, Helpers

export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toast Notification System
export function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-notification transform translate-x-full opacity-0 transition-all duration-300 ease-out';

    // Icon and color based on type
    let icon, bgColor, borderColor, iconColor;
    switch (type) {
        case 'success':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>`;
            bgColor = 'bg-green-500/10';
            borderColor = 'border-green-500/30';
            iconColor = 'text-green-400';
            break;
        case 'error':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>`;
            bgColor = 'bg-red-500/10';
            borderColor = 'border-red-500/30';
            iconColor = 'text-red-400';
            break;
        case 'warning':
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>`;
            bgColor = 'bg-yellow-500/10';
            borderColor = 'border-yellow-500/30';
            iconColor = 'text-yellow-400';
            break;
        default: // info
            icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>`;
            bgColor = 'bg-white/5';
            borderColor = 'border-white/10';
            iconColor = 'text-slate-200';
    }

    toast.innerHTML = `
        <div class="flex items-start gap-3 p-4 ${bgColor} border ${borderColor} rounded-xl backdrop-blur-xl shadow-lg">
            <div class="${iconColor} flex-shrink-0 mt-0.5">${icon}</div>
            <div class="flex-1 text-sm text-slate-200 leading-relaxed">${escapeHtml(message)}</div>
            <button class="toast-close flex-shrink-0 text-slate-400 hover:text-white transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        </div>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            toast.classList.remove('translate-x-full', 'opacity-0');
        });
    });

    // Close button
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => removeToast(toast));

    // Auto remove
    if (duration > 0) {
        setTimeout(() => removeToast(toast), duration);
    }
}

function removeToast(toast) {
    toast.classList.add('translate-x-full', 'opacity-0');
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

// Confirmation Modal System
export function showConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        const modalContent = document.getElementById('confirmModalContent');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmModalConfirm');
        const cancelBtn = document.getElementById('confirmModalCancel');

        if (!modal || !modalContent) {
            // Fallback to native confirm if modal not found
            resolve(confirm(message));
            return;
        }

        // Set content
        titleEl.textContent = title;
        messageEl.textContent = message;

        // Show modal
        modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                modalContent.classList.remove('scale-95', 'opacity-0');
                modalContent.classList.add('scale-100', 'opacity-100');
            });
        });

        // Handle clicks
        const handleConfirm = () => {
            cleanup();
            resolve(true);
        };

        const handleCancel = () => {
            cleanup();
            resolve(false);
        };

        const handleBackdropClick = (e) => {
            if (e.target === modal) {
                handleCancel();
            }
        };

        const cleanup = () => {
            modalContent.classList.remove('scale-100', 'opacity-100');
            modalContent.classList.add('scale-95', 'opacity-0');
            setTimeout(() => {
                modal.classList.add('hidden');
            }, 200);

            confirmBtn.removeEventListener('click', handleConfirm);
            cancelBtn.removeEventListener('click', handleCancel);
            modal.removeEventListener('click', handleBackdropClick);
        };

        confirmBtn.addEventListener('click', handleConfirm);
        cancelBtn.addEventListener('click', handleCancel);
        modal.addEventListener('click', handleBackdropClick);
    });
}

export function initializeFooter() {
    const y = document.getElementById('currentYear');
    if (y) y.textContent = new Date().getFullYear();
}

// Donation Modal Logic
export function initializeKofi() {
    const kofiBtn = document.getElementById('kofiBtn');
    const homepageDonateBtn = document.getElementById('homepageDonateBtn');
    const donationModal = document.getElementById('donation-modal');
    const donationBackdrop = document.getElementById('donation-backdrop');
    const closeDonationBtn = document.getElementById('close-donation');

    if (!donationModal) return;

    // Open modal function
    const openModal = (e) => {
        if (e) e.preventDefault();
        donationModal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
    };

    // Close modal function
    const closeModal = () => {
        donationModal.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
    };

    // Open modal when navbar button is clicked
    if (kofiBtn) {
        kofiBtn.addEventListener('click', openModal);
    }

    // Open modal when homepage donate button is clicked
    if (homepageDonateBtn) {
        homepageDonateBtn.addEventListener('click', openModal);
    }

    // Close button
    if (closeDonationBtn) {
        closeDonationBtn.addEventListener('click', closeModal);
    }

    // Close on backdrop click
    if (donationBackdrop) {
        donationBackdrop.addEventListener('click', (e) => {
            if (e.target === donationBackdrop) {
                closeModal();
            }
        });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !donationModal.classList.contains('hidden')) {
            closeModal();
        }
    });
}

// Collapsible provider cards on the accounts page
export function initializeProviderCards() {
    document.querySelectorAll('[data-provider-toggle]').forEach((btn) => {
        const provider = btn.dataset.providerToggle;
        const body = document.querySelector(`[data-provider-body="${provider}"]`);
        const chevron = document.querySelector(`[data-provider-chevron="${provider}"]`);
        if (!body) return;
        btn.addEventListener('click', () => {
            const open = !body.classList.toggle('hidden');
            btn.setAttribute('aria-expanded', String(open));
            if (chevron) chevron.classList.toggle('rotate-180', open);
        });
    });
}

// Changelog Modal Logic
export function initializeChangelog() {
    const badge = document.getElementById('versionBadge');
    const modal = document.getElementById('changelog-modal');
    const backdrop = document.getElementById('changelog-backdrop');
    const closeBtn = document.getElementById('close-changelog');
    const content = document.getElementById('changelog-content');

    if (!badge || !modal) return;

    let loaded = false;
    const loadChangelog = async () => {
        if (loaded) return;
        try {
            const res = await fetch('/changelog');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
            const article = doc.querySelector('article');
            if (!article) throw new Error('changelog page had no article');
            // Same-origin markup rendered by our own /changelog endpoint, not user data.
            content.replaceChildren(...article.children);
            loaded = true;
        } catch (err) {
            content.textContent = 'Could not load the changelog.';
        }
    };

    const openModal = (e) => {
        e.preventDefault();
        modal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
        loadChangelog();
    };

    const closeModal = () => {
        modal.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
    };

    badge.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);
    backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });
}
