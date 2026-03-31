const STORAGE_KEY = 'watchly_auth';
const EXPIRY_DAYS = 30;

export function saveAuthToStorage(authData) {
    try {
        const expiryDate = new Date();
        expiryDate.setDate(expiryDate.getDate() + EXPIRY_DAYS);
        const data = {
            ...authData,
            expiresAt: expiryDate.getTime()
        };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
        console.warn('Failed to save auth to localStorage:', e);
    }
}

export function getAuthFromStorage() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (!stored) return null;

        const data = JSON.parse(stored);
        const now = Date.now();

        if (data.expiresAt && data.expiresAt < now) {
            clearAuthFromStorage();
            return null;
        }

        return data;
    } catch (e) {
        console.warn('Failed to read auth from localStorage:', e);
        clearAuthFromStorage();
        return null;
    }
}

export function clearAuthFromStorage() {
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
        console.warn('Failed to clear auth from localStorage:', e);
    }
}
