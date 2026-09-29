import { defaultCatalogs } from './constants.js';

export function createAppState() {
    return {
        auth: {
            loggedIn: false,
            authKey: '',
            userDisplay: null,
            token: '',
            hasInstall: false
        },
        ui: {
            currentSection: 'welcome'
        },
        catalogs: structuredClone(defaultCatalogs)
    };
}

export function resetAppState(state) {
    Object.assign(state, createAppState());
}
