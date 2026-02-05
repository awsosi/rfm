/**
 * Authentication Module
 * Handles user authentication, session management, and token storage
 */

// API base URL - adjust based on deployment
const API_BASE_URL = window.location.origin.includes('localhost')
    ? 'http://localhost:8000'
    : window.location.origin;

// Session storage keys
const TOKEN_KEY = 'auth_token';
const USER_KEY = 'current_user';
const TOKEN_EXPIRY_KEY = 'token_expiry';

/**
 * Login user with username and password
 * @param {string} username - Username
 * @param {string} password - Password
 * @param {string} authMethod - Authentication method: 'auto', 'remote', or 'local'
 * @returns {Promise<{success: boolean, error?: string}>}
 */
export async function login(username, password, authMethod = 'auto') {
    try {
        // Use JSON-based login endpoint to support auth_method parameter
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password,
                auth_method: authMethod
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Login failed' }));
            return {
                success: false,
                error: errorData.detail || 'Invalid credentials'
            };
        }

        const data = await response.json();

        // Store token and user data
        sessionStorage.setItem(TOKEN_KEY, data.access_token);

        // Calculate token expiry (default 30 minutes)
        const expiryTime = Date.now() + (30 * 60 * 1000);
        sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());

        // Fetch and store user data
        const userResponse = await fetch(`${API_BASE_URL}/api/auth/me`, {
            headers: {
                'Authorization': `Bearer ${data.access_token}`
            }
        });

        if (userResponse.ok) {
            const userData = await userResponse.json();
            sessionStorage.setItem(USER_KEY, JSON.stringify(userData));
        }

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
 * Logout current user
 * Clears session storage and redirects to login
 */
export function logout() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(TOKEN_EXPIRY_KEY);
}

/**
 * Check if user is authenticated
 * @returns {boolean}
 */
export function checkAuth() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    const expiry = sessionStorage.getItem(TOKEN_EXPIRY_KEY);

    if (!token || !expiry) {
        return false;
    }

    // Check if token is expired
    if (Date.now() > parseInt(expiry)) {
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
    return sessionStorage.getItem(TOKEN_KEY);
}

/**
 * Get current user data
 * @returns {Object|null}
 */
export function getCurrentUser() {
    if (!checkAuth()) {
        return null;
    }

    const userData = sessionStorage.getItem(USER_KEY);
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
 * Refresh authentication token
 * @returns {Promise<boolean>}
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

        if (!response.ok) {
            logout();
            return false;
        }

        const data = await response.json();
        sessionStorage.setItem(TOKEN_KEY, data.access_token);

        // Update expiry time
        const expiryTime = Date.now() + (30 * 60 * 1000);
        sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());

        return true;

    } catch (error) {
        console.error('Token refresh error:', error);
        return false;
    }
}

/**
 * Setup automatic token refresh
 * Refreshes token 5 minutes before expiry
 */
export function setupAutoRefresh() {
    // Check every minute if token needs refresh
    setInterval(async () => {
        const expiry = sessionStorage.getItem(TOKEN_EXPIRY_KEY);
        if (!expiry) {
            return;
        }

        const expiryTime = parseInt(expiry);
        const fiveMinutesFromNow = Date.now() + (5 * 60 * 1000);

        // Refresh if expiring in next 5 minutes
        if (expiryTime < fiveMinutesFromNow) {
            const refreshed = await refreshToken();
            if (!refreshed) {
                // Token refresh failed, redirect to login
                window.location.href = '/pages/login.html';
            }
        }
    }, 60000); // Check every minute
}

/**
 * Get API base URL
 * @returns {string}
 */
export function getApiBaseUrl() {
    return API_BASE_URL;
}
