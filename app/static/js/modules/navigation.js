// Navigation and Section Management

// DOM Elements - will be initialized
let navItems = {};
let sections = {};
let appState = null;

const SETUP_STEPS = ['login', 'config', 'catalogs', 'install'];

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

    window.scrollTo({ top: 0, behavior: 'auto' });
}
