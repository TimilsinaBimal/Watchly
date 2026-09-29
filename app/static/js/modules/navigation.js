// Navigation and Section Management

// DOM Elements - will be initialized
let navItems = {};
let sections = {};
let appState = null;

const SETUP_STEPS = ['login', 'config', 'catalogs', 'install'];

// The step lives in the URL hash so a reload returns to it. Only step names go
// there, never anything from the form.
const HASH_FOR = { login: 'accounts', config: 'preferences', catalogs: 'catalogs', install: 'install', dashboard: 'dashboard' };
const SECTION_FOR = Object.fromEntries(Object.entries(HASH_FOR).map(([key, hash]) => [hash, key]));
// Read once at load, before the first switchSection rewrites the hash.
const requestedSection = SECTION_FOR[window.location.hash.slice(1)] || null;

// The section to open on load: the one in the URL, if it isn't locked.
export function initialSection(fallback) {
    // Accounts is always reachable: it's where Get started leads anyway.
    const open = requestedSection === 'login' || !navItems[requestedSection]?.classList.contains('disabled');
    return requestedSection && open ? requestedSection : fallback;
}

// After sign-in unlocks the steps: return to the step in the URL, if any.
export function resumeSection(fallback) {
    return SETUP_STEPS.includes(requestedSection) ? requestedSection : fallback;
}

export function initializeNavigation(domElements, state) {
    navItems = domElements.navItems;
    sections = domElements.sections;
    appState = state;

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

export function switchSection(sectionKey) {
    if (appState) {
        appState.ui.currentSection = sectionKey;
    }

    // Hide all sections
    Object.values(sections).forEach(el => {
        if (el) el.classList.add('hidden');
    });

    // Show target section
    if (sections[sectionKey]) {
        sections[sectionKey].classList.remove('hidden');
    }

    Object.values(navItems).forEach(el => {
        if (el) el.classList.remove('active', 'done');
    });
    if (navItems[sectionKey]) {
        navItems[sectionKey].classList.add('active');
    }
    const current = SETUP_STEPS.indexOf(sectionKey);
    SETUP_STEPS.slice(0, Math.max(current, 0)).forEach(key => navItems[key]?.classList.add('done'));

    const hash = HASH_FOR[sectionKey] ? `#${HASH_FOR[sectionKey]}` : '';
    window.history.replaceState(null, '', window.location.pathname + window.location.search + hash);

    window.scrollTo({ top: 0, behavior: 'auto' });
}
