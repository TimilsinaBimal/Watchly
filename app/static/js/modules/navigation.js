// Navigation and Section Management

// DOM Elements - will be initialized
let navItems = {};
let sections = {};
let mainEl = null;

export function initializeNavigation(domElements) {
    navItems = domElements.navItems;
    sections = domElements.sections;
    mainEl = domElements.mainEl;

    Object.keys(navItems).forEach(key => {
        if (navItems[key]) {
            navItems[key].addEventListener('click', () => {
                if (!navItems[key].classList.contains('disabled')) {
                    switchSection(key);
                }
            });
        }
    });
}

export function unlockNavigation() {
    Object.values(navItems).forEach(el => {
        if (el) el.classList.remove('disabled');
    });
}

export function lockNavigationForLoggedOut() {
    // Ensure welcome and login remain accessible; disable only config/catalogs/install
    if (navItems.welcome) navItems.welcome.classList.remove('disabled');
    if (navItems.login) navItems.login.classList.remove('disabled');
    if (navItems.config) navItems.config.classList.add('disabled');
    if (navItems.catalogs) navItems.catalogs.classList.add('disabled');
    if (navItems.install) navItems.install.classList.add('disabled');
}

export function initializeMobileNav() {
    const mobileToggle = document.getElementById('mobileNavToggle');
    const sidebar = document.getElementById('mainSidebar');
    const backdrop = document.getElementById('mobileNavBackdrop');
    if (!mobileToggle || !sidebar || !backdrop) return;

    const openNav = () => {
        sidebar.classList.remove('-translate-x-full');
        sidebar.classList.add('translate-x-0');
        backdrop.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
        // Animate hamburger to X
        mobileToggle.classList.add('is-active');
        mobileToggle.setAttribute('aria-expanded', 'true');
        mobileToggle.setAttribute('aria-label', 'Close navigation');
    };
    const closeNav = () => {
        sidebar.classList.remove('translate-x-0');
        sidebar.classList.add('-translate-x-full');
        backdrop.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
        // Reset hamburger
        mobileToggle.classList.remove('is-active');
        mobileToggle.setAttribute('aria-expanded', 'false');
        mobileToggle.setAttribute('aria-label', 'Open navigation');
    };

    mobileToggle.addEventListener('click', (e) => {
        e.preventDefault();
        // Toggle open/close for convenience
        const isOpen = sidebar.classList.contains('translate-x-0');
        if (isOpen) closeNav(); else openNav();
    });
    backdrop.addEventListener('click', closeNav);

    // Auto-close when a nav item is selected (mobile)
    Object.values(navItems).forEach(n => {
        if (!n) return;
        n.addEventListener('click', () => {
            if (!sidebar.classList.contains('hidden')) closeNav();
        });
    });
}

export function switchSection(sectionKey) {
    // Hide all sections
    Object.values(sections).forEach(el => {
        if (el) el.classList.add('hidden');
    });

    // Show target section
    if (sections[sectionKey]) {
        sections[sectionKey].classList.remove('hidden');
    }

    // Update Nav UI Logic
    // Reset all nav items
    Object.values(navItems).forEach(el => {
        if (el) {
            el.classList.remove('active', 'bg-blue-600/10', 'text-blue-400', 'border-l-2', 'border-blue-400');
        }
    });

    // Activate current if exists in nav
    if (navItems[sectionKey]) {
        navItems[sectionKey].classList.add('active');
    }

    // Ensure new section starts at top in the scroll container
    try {
        if (mainEl) {
            // Using scrollTo with behavior auto to avoid jank on iOS toolbars
            mainEl.scrollTo({ top: 0, behavior: 'auto' });
        } else {
            window.scrollTo({ top: 0, behavior: 'auto' });
        }
    } catch (e) { /* noop */ }
}

export function updateMobileLayout() {
    try {
        const headerEl = document.getElementById('mobileHeader');
        const isMobile = window.matchMedia('(max-width: 767.98px)').matches;
        if (!headerEl || !mainEl) return;
        const h = headerEl.offsetHeight || 0;
        document.documentElement.style.setProperty('--mobile-header', `${h}px`);

        const sidebarEl = document.getElementById('mainSidebar');
        if (!sidebarEl) return;

        if (isMobile) {
            if (mainEl) mainEl.style.paddingTop = `${h}px`;
            sidebarEl.style.top = `${h}px`;
            sidebarEl.style.height = `calc(100dvh - ${h}px)`;
        } else {
            if (mainEl) mainEl.style.paddingTop = '';
            sidebarEl.style.top = '0';
            sidebarEl.style.height = '100dvh';
        }
    } catch (e) { /* noop */ }
}
