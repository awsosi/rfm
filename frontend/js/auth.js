/**
 * Authentication Module
 * Handles user authentication, session management, and token storage
 */

// API base URL - can be overridden by backend via window.API_URL_PUBLIC
// This is set by the Flask backend from the API_URL_PUBLIC environment variable
export const API_BASE_URL = window.API_URL_PUBLIC || (
    window.location.origin.includes('localhost')
        ? 'http://localhost:8000'
        : window.location.origin
);

// Storage keys. A remembered session lives in localStorage (survives closing
// the browser); any other session in sessionStorage (ends with the tab).
export const TOKEN_KEY = 'auth_token';
export const USER_KEY = 'current_user';
export const TOKEN_EXPIRY_KEY = 'token_expiry';
const TOKEN_LIFETIME_KEY = 'token_lifetime';
const SESSION_KEYS = [TOKEN_KEY, USER_KEY, TOKEN_EXPIRY_KEY, TOKEN_LIFETIME_KEY];

const LOGIN_PAGE = '/pages/login.html';

// Set when checkAuth() finds a session that has run out, so the login page
// can say why the user is there.
let sessionExpired = false;
// Several requests can fail at once; the first redirect decides where to go.
let redirecting = false;

function storages() {
    const list = [];
    for (const name of ['localStorage', 'sessionStorage']) {
        try {
            if (window[name]) list.push(window[name]);
        } catch (error) {
            /* Storage blocked (privacy settings): skip it */
        }
    }
    return list;
}

/** The storage holding the current session, or null. */
function sessionStore() {
    return storages().find(store => store.getItem(TOKEN_KEY)) || null;
}

/**
 * Store a session returned by /api/auth/login, /refresh or /me.
 * @param {Object} data - LoginResponse (access_token, expires_in, user_id, username, role, remember_me)
 */
export function storeSession(data) {
    clearSession();
    let store = null;
    try {
        store = data.remember_me ? window.localStorage : window.sessionStorage;
    } catch (error) {
        store = storages()[0];
    }
    if (!store) return;
    store.setItem(TOKEN_KEY, data.access_token);
    store.setItem(TOKEN_EXPIRY_KEY, String(Date.now() + data.expires_in * 1000));
    store.setItem(TOKEN_LIFETIME_KEY, String(data.expires_in * 1000));
    store.setItem(USER_KEY, JSON.stringify({
        id: data.user_id,
        username: data.username,
        role: data.role
    }));
}

function clearSession() {
    for (const store of storages()) {
        SESSION_KEYS.forEach(key => store.removeItem(key));
    }
}

/**
 * Login user with username and password
 * @param {string} username - Username
 * @param {string} password - Password
 * @param {string} authMethod - Authentication method: 'auto', 'polka', or 'local'
 * @param {boolean} rememberMe - Keep the session after the browser closes (ignored for admins)
 * @returns {Promise<{success: boolean, error?: string}>}
 */
export async function login(username, password, authMethod = 'auto', rememberMe = false) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password,
                auth_method: authMethod,
                remember_me: rememberMe
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const detail = errorData.error ?? errorData.detail;
            return {
                success: false,
                error: typeof detail === 'string' ? detail : 'Invalid credentials'
            };
        }

        storeSession(await response.json());
        return { success: true };

    } catch (error) {
        console.error('Login error:', error);
        return {
            success: false,
            error: 'Connection error. Please try again.'
        };
    }
}

/**
 * Logout current user: forget the session in this browser.
 */
export function logout() {
    clearSession();
}

/**
 * Check if user is authenticated
 * @returns {boolean}
 */
export function checkAuth() {
    const store = sessionStore();
    const expiry = store?.getItem(TOKEN_EXPIRY_KEY);

    if (!store || !expiry) {
        return false;
    }

    if (Date.now() > parseInt(expiry)) {
        sessionExpired = true;
        logout();
        return false;
    }

    return true;
}

/**
 * Get authentication token
 * @returns {string|null}
 */
export function getToken() {
    if (!checkAuth()) {
        return null;
    }
    return sessionStore().getItem(TOKEN_KEY);
}

/**
 * Get current user data
 * @returns {Object|null}
 */
export function getCurrentUser() {
    if (!checkAuth()) {
        return null;
    }

    const userData = sessionStore().getItem(USER_KEY);
    if (!userData) {
        return null;
    }

    try {
        return JSON.parse(userData);
    } catch (error) {
        console.error('Error parsing user data:', error);
        return null;
    }
}

/**
 * Check if current user is admin
 * @returns {boolean}
 */
export function isAdmin() {
    const user = getCurrentUser();
    // Backend returns uppercase role (ADMIN, USER)
    return user && user.role?.toUpperCase() === 'ADMIN';
}

/**
 * Send the user to the login page, coming back here after signing in.
 * The login page explains that the session expired when one was in use.
 */
export function redirectToLogin() {
    if (redirecting) return;
    const expired = sessionExpired || Boolean(sessionStore());
    logout();

    const here = new URL(window.location.href);
    if (here.pathname === LOGIN_PAGE) return;
    redirecting = true;
    here.searchParams.delete('token'); // a deep-link token must not be replayed

    const params = new URLSearchParams();
    if (expired) params.set('expired', '1');
    params.set('return', here.pathname + here.search + here.hash);
    window.location.href = `${LOGIN_PAGE}?${params}`;
}

/**
 * Where to go after signing in: the requested page when it is on this site,
 * otherwise the explorer.
 * @param {string|null} returnUrl
 * @returns {string}
 */
export function safeReturnUrl(returnUrl) {
    if (returnUrl) {
        try {
            const url = new URL(returnUrl, window.location.href);
            if (url.origin === window.location.origin && url.pathname !== LOGIN_PAGE) {
                return url.href;
            }
        } catch (error) {
            /* Malformed: fall through */
        }
    }
    return 'explorer.html';
}

/**
 * Refresh authentication token
 * @returns {Promise<boolean|null>} true refreshed, false session rejected, null not reachable
 */
export async function refreshToken() {
    const currentToken = getToken();
    if (!currentToken) {
        return false;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${currentToken}`
            }
        });

        if (response.status === 401) {
            return false;
        }
        if (!response.ok) {
            return null;
        }

        storeSession(await response.json());
        return true;

    } catch (error) {
        console.error('Token refresh error:', error);
        return null;
    }
}

/**
 * Keep an open page's session alive and leave it when the session ends.
 *
 * Once half of the session lifetime has passed the token is refreshed (the
 * server extends it by the current session policy). An expired or rejected
 * session sends the user to the login page. Checked every minute and whenever
 * the tab becomes visible again (timers are throttled in background tabs and
 * stop while the computer sleeps).
 */
export function setupAutoRefresh() {
    let busy = false;
    const check = async () => {
        if (busy) return;
        if (!checkAuth()) {
            redirectToLogin();
            return;
        }
        const store = sessionStore();
        const expiry = parseInt(store.getItem(TOKEN_EXPIRY_KEY));
        const lifetime = parseInt(store.getItem(TOKEN_LIFETIME_KEY)) || 0;
        if (expiry - Date.now() > lifetime / 2) return;

        busy = true;
        try {
            if (await refreshToken() === false) {
                redirectToLogin();
            }
        } finally {
            busy = false;
        }
    };

    setInterval(check, 60000);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') check();
    });
}

/**
 * Get API base URL
 * @returns {string}
 */
export function getApiBaseUrl() {
    return API_BASE_URL;
}
