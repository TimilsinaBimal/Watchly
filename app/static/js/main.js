// Main entry point - initializes all modules

import { createAppState, resetAppState } from './state.js';
import { initializeChangelog, initializeKofi, initializeProviderCards } from './modules/ui.js';
import { initializeNavigation, switchSection, lockNavigationForLoggedOut, initializeMobileNav, updateMobileLayout } from './modules/navigation.js';
import { initializeAuth, setStremioLoggedOutState } from './modules/auth.js';
import { initializeCatalogList, renderCatalogList } from './modules/catalog.js';
import { initializeForm, clearErrors } from './modules/form.js';
import { initializeAccountsUI } from './modules/accounts.js';
import { initializeDashboard } from './modules/dashboard.js';

const appState = createAppState();

const configForm = document.getElementById('configForm');
const catalogList = document.getElementById('catalogList');
const movieGenreList = document.getElementById('movieGenreList');
const seriesGenreList = document.getElementById('seriesGenreList');
const submitBtn = document.getElementById('submitBtn');
const stremioLoginBtn = document.getElementById('stremioLoginBtn');
const emailInput = document.getElementById('emailInput');
const passwordInput = document.getElementById('passwordInput');
const emailPwdContinueBtn = document.getElementById('emailPwdContinueBtn');
const languageSelect = document.getElementById('languageSelect');
const accountsNextBtn = document.getElementById('accountsNextBtn');
const configNextBtn = document.getElementById('configNextBtn');
const catalogsNextBtn = document.getElementById('catalogsNextBtn');
const successResetBtn = document.getElementById('successResetBtn');
const btnGetStarted = document.getElementById('btn-get-started');

const navItems = {
    welcome: document.getElementById('nav-welcome'),
    login: document.getElementById('nav-login'),
    config: document.getElementById('nav-config'),
    catalogs: document.getElementById('nav-catalogs'),
    install: document.getElementById('nav-install'),
    dashboard: document.getElementById('nav-dashboard')
};

const sections = {
    welcome: document.getElementById('sect-welcome'),
    login: document.getElementById('sect-login'),
    config: document.getElementById('sect-config'),
    catalogs: document.getElementById('sect-catalogs'),
    install: document.getElementById('sect-install'),
    success: document.getElementById('sect-success'),
    dashboard: document.getElementById('sect-dashboard')
};

const mainEl = document.querySelector('main');

function resetApp() {
    if (configForm) configForm.reset();
    resetAppState(appState);
    clearErrors();

    setStremioLoggedOutState();

    renderCatalogList();

    switchSection(appState.ui.currentSection);
    lockNavigationForLoggedOut();

    if (configForm) configForm.classList.remove('hidden');
    if (sections.success) sections.success.classList.add('hidden');
}

// Welcome Flow Logic
function initializeWelcomeFlow() {
    if (!btnGetStarted) return;

    btnGetStarted.addEventListener('click', () => {
        if (navItems.login) navItems.login.classList.remove('disabled');
        switchSection('login');
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initializeWelcomeFlow();

    initializeNavigation({
        navItems,
        sections,
        mainEl
    }, appState);

    // By default, ensure logged-out users see only Welcome/Login
    lockNavigationForLoggedOut();

    initializeAccountsUI();

    initializeCatalogList({ catalogList }, appState);

    const updateYearSlider = initializeForm(
        {
            submitBtn,
            emailInput,
            passwordInput,
            languageSelect,
            movieGenreList,
            seriesGenreList
        },
        appState,
        { resetApp }
    );

    initializeAuth(
        {
            stremioLoginBtn,
            emailInput,
            passwordInput,
            emailPwdContinueBtn,
            languageSelect
        },
        appState,
        {
            resetApp,
            updateYearSlider
        }
    );

    // Initialize the Dashboard nav section
    initializeDashboard(appState);

    // Initialize mobile navigation
    initializeMobileNav();

    // Initialize UI components
    initializeKofi();
    initializeChangelog();
    initializeProviderCards();

    // Layout adjustments for fixed mobile header
    updateMobileLayout();
    window.addEventListener('resize', updateMobileLayout);
    window.addEventListener('orientationchange', updateMobileLayout);

    if (accountsNextBtn) accountsNextBtn.addEventListener('click', () => {
        if (!accountsNextBtn.disabled) switchSection('config');
    });
    if (configNextBtn) configNextBtn.addEventListener('click', () => switchSection('catalogs'));
    if (catalogsNextBtn) catalogsNextBtn.addEventListener('click', () => switchSection('install'));

    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn) resetBtn.addEventListener('click', resetApp);
    if (successResetBtn) successResetBtn.addEventListener('click', resetApp);
});
