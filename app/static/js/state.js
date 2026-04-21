import { defaultCatalogs } from './constants.js';

export function cloneDefaultCatalogs() {
    return JSON.parse(JSON.stringify(defaultCatalogs));
}

export function createAppState() {
    return {
        auth: {
            loggedIn: false,
            authKey: '',
            userDisplay: null
        },
        ui: {
            currentSection: 'welcome'
        },
        catalogs: cloneDefaultCatalogs()
    };
}

export function resetAppState(state) {
    state.auth.loggedIn = false;
    state.auth.authKey = '';
    state.auth.userDisplay = null;
    state.ui.currentSection = 'welcome';
    state.catalogs = cloneDefaultCatalogs();
}
