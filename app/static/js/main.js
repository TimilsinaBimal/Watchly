// Main entry point - initializes all modules

import { defaultCatalogs } from './constants.js';
import { showToast, initializeFooter, initializeKofi } from './modules/ui.js';
import { initializeNavigation, switchSection, lockNavigationForLoggedOut, initializeMobileNav, updateMobileLayout, unlockNavigation } from './modules/navigation.js';
import { initializeAuth, setStremioLoggedOutState } from './modules/auth.js';
import { initializeCatalogList, renderCatalogList, getCatalogs, setCatalogs } from './modules/catalog.js';
import { initializeForm, clearErrors } from './modules/form.js';

// Initialize catalogs state
let catalogsState = JSON.parse(JSON.stringify(defaultCatalogs));

// DOM Elements
const configForm = document.getElementById('configForm');
const catalogList = document.getElementById('catalogList');
const movieGenreList = document.getElementById('movieGenreList');
const seriesGenreList = document.getElementById('seriesGenreList');
const submitBtn = document.getElementById('submitBtn');
const stremioLoginBtn = document.getElementById('stremioLoginBtn');
const stremioLoginText = document.getElementById('stremioLoginText');
const emailInput = document.getElementById('emailInput');
const passwordInput = document.getElementById('passwordInput');
const emailPwdContinueBtn = document.getElementById('emailPwdContinueBtn');
const languageSelect = document.getElementById('languageSelect');
const configNextBtn = document.getElementById('configNextBtn');
const catalogsNextBtn = document.getElementById('catalogsNextBtn');
const successResetBtn = document.getElementById('successResetBtn');
const btnGetStarted = document.getElementById('btn-get-started');

const navItems = {
    welcome: document.getElementById('nav-welcome'),
    login: document.getElementById('nav-login'),
    config: document.getElementById('nav-config'),
    catalogs: document.getElementById('nav-catalogs'),
    install: document.getElementById('nav-install')
};

const sections = {
    welcome: document.getElementById('sect-welcome'),
    login: document.getElementById('sect-login'),
    config: document.getElementById('sect-config'),
    catalogs: document.getElementById('sect-catalogs'),
    install: document.getElementById('sect-install'),
    success: document.getElementById('sect-success')
};

// Main scroll container
const mainEl = document.querySelector('main');

// Reset App Function
function resetApp() {
    if (configForm) configForm.reset();
    clearErrors();

    // Reset Navigation is now Back to Welcome
    switchSection('welcome');

    // Lock Navs
    Object.keys(navItems).forEach(key => {
        if (key !== 'login' && key !== 'welcome') {
            if (navItems[key]) navItems[key].classList.add('disabled');
        }
    });

    // Reset Stremio State
    setStremioLoggedOutState();

    // Reset catalogs
    catalogsState = JSON.parse(JSON.stringify(defaultCatalogs));
    setCatalogs(catalogsState);
    renderCatalogList();

    // Show Form
    if (configForm) configForm.classList.remove('hidden');
    if (sections.success) sections.success.classList.add('hidden');
}

// Welcome Flow Logic
function initializeWelcomeFlow() {
    if (!btnGetStarted) return;

    // Support mobile taps reliably while avoiding double-fire (touch -> click)
    let touched = false;
    const handleGetStarted = (e) => {
        if (e.type === 'click' && touched) return;
        if (e.type === 'touchstart') touched = true;
        if (navItems.login) navItems.login.classList.remove('disabled');
        switchSection('login');
    };

    btnGetStarted.addEventListener('click', handleGetStarted);
    btnGetStarted.addEventListener('touchstart', handleGetStarted, { passive: true });
}

// Initialize everything
document.addEventListener('DOMContentLoaded', () => {
    // Start at Welcome
    switchSection('welcome');
    initializeWelcomeFlow();

    // Initialize all modules
    initializeNavigation({
        navItems,
        sections,
        mainEl
    });

    // By default, ensure logged-out users see only Welcome/Login
    lockNavigationForLoggedOut();

    // Initialize catalog management - set catalogs first
    setCatalogs(catalogsState);
    initializeCatalogList(
        { catalogList },
        {
            catalogs: catalogsState,
            renderCatalogList
        }
    );

    // Initialize authentication
    initializeAuth(
        {
            stremioLoginBtn,
            stremioLoginText,
            emailInput,
            passwordInput,
            emailPwdContinueBtn,
            languageSelect
        },
        {
            getCatalogs,
            renderCatalogList,
            resetApp
        }
    );

    // Initialize form handling
    initializeForm(
        {
            configForm,
            submitBtn,
            emailInput,
            passwordInput,
            languageSelect,
            movieGenreList,
            seriesGenreList
        },
        {
            getCatalogs,
            resetApp
        }
    );

    // Initialize mobile navigation
    initializeMobileNav();

    // Initialize UI components
    initializeFooter();
    initializeKofi();

    // Layout adjustments for fixed mobile header
    updateMobileLayout();
    window.addEventListener('resize', updateMobileLayout);
    window.addEventListener('orientationchange', updateMobileLayout);

    // Next Buttons
    if (configNextBtn) configNextBtn.addEventListener('click', () => switchSection('catalogs'));
    if (catalogsNextBtn) catalogsNextBtn.addEventListener('click', () => switchSection('install'));

    // Reset Buttons
    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn) resetBtn.addEventListener('click', resetApp);
    if (successResetBtn) successResetBtn.addEventListener('click', resetApp);
});

// Make resetApp available globally for auth module
window.resetApp = resetApp;
window.switchSection = switchSection;
window.unlockNavigation = unlockNavigation;
