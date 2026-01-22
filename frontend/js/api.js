/**
 * API Module
 * Handles all API calls and WebSocket connections
 */

import { getToken, getApiBaseUrl, logout } from './auth.js';

const API_BASE_URL = getApiBaseUrl();
const WS_BASE_URL = API_BASE_URL.replace('http', 'ws');

// WebSocket connection
let wsConnection = null;
let wsReconnectTimer = null;
let wsEventHandlers = [];

/**
 * Make authenticated API request
 * @param {string} endpoint - API endpoint
 * @param {Object} options - Fetch options
 * @returns {Promise<any>}
 */
export async function apiRequest(endpoint, options = {}) {
    const token = getToken();
    if (!token) {
        throw new Error('Not authenticated');
    }

    const defaultHeaders = {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    };

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers
        }
    });

    // Handle unauthorized
    if (response.status === 401) {
        logout();
        window.location.href = '/pages/login.html';
        throw new Error('Unauthorized');
    }

    // Handle errors
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(errorData.detail || `Request failed with status ${response.status}`);
    }

    // Return JSON response
    return await response.json();
}

/**
 * List files in a directory
 * @param {string} path - Directory path
 * @param {number} offset - Pagination offset
 * @param {number} limit - Pagination limit
 * @returns {Promise<Array>}
 */
export async function listFiles(path, offset = 0, limit = 50) {
    const params = new URLSearchParams({ path, offset: offset.toString(), limit: limit.toString() });
    return await apiRequest(`/api/files/list?${params}`);
}

/**
 * Search files recursively
 * @param {string} path - Base path to search
 * @param {string} pattern - Search pattern
 * @returns {Promise<Array>}
 */
export async function searchFiles(path, pattern) {
    const params = new URLSearchParams({ path, pattern });
    return await apiRequest(`/api/files/search?${params}`);
}

/**
 * Create a new directory
 * @param {string} path - Directory path to create
 * @returns {Promise<Object>}
 */
export async function createDirectory(path) {
    return await apiRequest('/api/files/mkdir', {
        method: 'POST',
        body: JSON.stringify({ path })
    });
}

/**
 * Rename a file or directory
 * @param {string} oldPath - Current path
 * @param {string} newPath - New path
 * @returns {Promise<Object>}
 */
export async function renameFile(oldPath, newPath) {
    return await apiRequest('/api/files/rename', {
        method: 'POST',
        body: JSON.stringify({ old_path: oldPath, new_path: newPath })
    });
}

/**
 * Delete files or directories
 * @param {Array<string>} paths - Array of paths to delete
 * @returns {Promise<Object>}
 */
export async function deleteFiles(paths) {
    return await apiRequest('/api/files/delete', {
        method: 'POST',
        body: JSON.stringify({ paths })
    });
}

/**
 * Copy files from source to destination
 * @param {Array<string>} sourcePaths - Array of source paths
 * @param {string} destPath - Destination directory path
 * @returns {Promise<Object>}
 */
export async function copyFiles(sourcePaths, destPath) {
    return await apiRequest('/api/files/copy', {
        method: 'POST',
        body: JSON.stringify({
            source_paths: sourcePaths,
            dest_path: destPath
        })
    });
}

/**
 * Move files from source to destination
 * @param {Array<string>} sourcePaths - Array of source paths
 * @param {string} destPath - Destination directory path
 * @returns {Promise<Object>}
 */
export async function moveFiles(sourcePaths, destPath) {
    return await apiRequest('/api/files/move', {
        method: 'POST',
        body: JSON.stringify({
            source_paths: sourcePaths,
            dest_path: destPath
        })
    });
}

/**
 * Get operation status
 * @param {string} operationId - Operation ID
 * @returns {Promise<Object>}
 */
export async function getOperationStatus(operationId) {
    return await apiRequest(`/api/operations/status/${operationId}`);
}

/**
 * Get list of operations
 * @param {string} status - Filter by status (optional)
 * @returns {Promise<Array>}
 */
export async function getOperations(status = null) {
    const params = status ? `?status=${status}` : '';
    return await apiRequest(`/api/operations/list${params}`);
}

/**
 * Cancel an operation
 * @param {string} operationId - Operation ID
 * @returns {Promise<Object>}
 */
export async function cancelOperation(operationId) {
    return await apiRequest(`/api/operations/cancel/${operationId}`, {
        method: 'POST'
    });
}

// ==========================================
// Admin API endpoints
// ==========================================

/**
 * Get all users (admin only)
 * @returns {Promise<Array>}
 */
export async function getUsers() {
    return await apiRequest('/api/admin/users');
}

/**
 * Create a new user (admin only)
 * @param {Object} userData - User data
 * @returns {Promise<Object>}
 */
export async function createUser(userData) {
    return await apiRequest('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify(userData)
    });
}

/**
 * Update user (admin only)
 * @param {string} userId - User ID
 * @param {Object} userData - Updated user data
 * @returns {Promise<Object>}
 */
export async function updateUser(userId, userData) {
    return await apiRequest(`/api/admin/users/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(userData)
    });
}

/**
 * Delete user (admin only)
 * @param {string} userId - User ID
 * @returns {Promise<Object>}
 */
export async function deleteUser(userId) {
    return await apiRequest(`/api/admin/users/${userId}`, {
        method: 'DELETE'
    });
}

/**
 * Get all workers (admin only)
 * @returns {Promise<Array>}
 */
export async function getWorkers() {
    return await apiRequest('/api/admin/workers');
}

/**
 * Approve a pending worker (admin only)
 * @param {string} workerId - Worker ID
 * @returns {Promise<Object>}
 */
export async function approveWorker(workerId) {
    return await apiRequest(`/api/admin/workers/${workerId}/approve`, {
        method: 'POST'
    });
}

/**
 * Reject a pending worker (admin only)
 * @param {string} workerId - Worker ID
 * @returns {Promise<Object>}
 */
export async function rejectWorker(workerId) {
    return await apiRequest(`/api/admin/workers/${workerId}/reject`, {
        method: 'POST'
    });
}

/**
 * Remove a worker (admin only)
 * @param {string} workerId - Worker ID
 * @returns {Promise<Object>}
 */
export async function removeWorker(workerId) {
    return await apiRequest(`/api/admin/workers/${workerId}`, {
        method: 'DELETE'
    });
}

/**
 * Get system configuration (admin only)
 * @returns {Promise<Object>}
 */
export async function getConfig() {
    return await apiRequest('/api/admin/config');
}

/**
 * Update system configuration (admin only)
 * @param {Object} config - Configuration data
 * @returns {Promise<Object>}
 */
export async function updateConfig(config) {
    return await apiRequest('/api/admin/config', {
        method: 'PUT',
        body: JSON.stringify(config)
    });
}

/**
 * Get system logs (admin only)
 * @param {Object} params - Query parameters (level, search, offset, limit)
 * @returns {Promise<Array>}
 */
export async function getLogs(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.level) queryParams.append('level', params.level);
    if (params.search) queryParams.append('search', params.search);
    if (params.offset !== undefined) queryParams.append('offset', params.offset.toString());
    if (params.limit !== undefined) queryParams.append('limit', params.limit.toString());

    const query = queryParams.toString();
    return await apiRequest(`/api/admin/logs${query ? '?' + query : ''}`);
}

// ==========================================
// WebSocket Management
// ==========================================

/**
 * Connect to WebSocket for real-time updates
 * @returns {Promise<void>}
 */
export async function connectWebSocket() {
    const token = getToken();
    if (!token) {
        console.warn('Cannot connect WebSocket: Not authenticated');
        return;
    }

    // Close existing connection
    if (wsConnection) {
        wsConnection.close();
    }

    try {
        // Connect to WebSocket endpoint with token
        wsConnection = new WebSocket(`${WS_BASE_URL}/ws/operations?token=${token}`);

        wsConnection.onopen = () => {
            console.log('WebSocket connected');
            // Clear reconnect timer
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };

        wsConnection.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // Dispatch event to all registered handlers
                wsEventHandlers.forEach(handler => {
                    try {
                        handler(data);
                    } catch (error) {
                        console.error('Error in WebSocket event handler:', error);
                    }
                });
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
            }
        };

        wsConnection.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        wsConnection.onclose = () => {
            console.log('WebSocket disconnected');
            wsConnection = null;

            // Attempt to reconnect after 5 seconds
            if (!wsReconnectTimer) {
                wsReconnectTimer = setTimeout(() => {
                    console.log('Attempting to reconnect WebSocket...');
                    connectWebSocket();
                }, 5000);
            }
        };

    } catch (error) {
        console.error('Error connecting WebSocket:', error);
    }
}

/**
 * Disconnect WebSocket
 */
export function disconnectWebSocket() {
    if (wsConnection) {
        wsConnection.close();
        wsConnection = null;
    }

    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
}

/**
 * Register WebSocket event handler
 * @param {Function} handler - Event handler function
 * @returns {Function} Unregister function
 */
export function onWebSocketEvent(handler) {
    wsEventHandlers.push(handler);

    // Return unregister function
    return () => {
        const index = wsEventHandlers.indexOf(handler);
        if (index > -1) {
            wsEventHandlers.splice(index, 1);
        }
    };
}

/**
 * Check if WebSocket is connected
 * @returns {boolean}
 */
export function isWebSocketConnected() {
    return wsConnection && wsConnection.readyState === WebSocket.OPEN;
}

// ==========================================
// Polling fallback for real-time updates
// ==========================================

let pollingInterval = null;

/**
 * Start polling for operation updates (fallback if WebSocket not available)
 * @param {Function} callback - Callback function to handle updates
 * @param {number} interval - Polling interval in milliseconds (default: 5000)
 */
export function startPolling(callback, interval = 5000) {
    if (pollingInterval) {
        stopPolling();
    }

    pollingInterval = setInterval(async () => {
        try {
            const operations = await getOperations('in_progress');
            callback(operations);
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, interval);
}

/**
 * Stop polling
 */
export function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

// =============================================================================
// User Preferences API
// =============================================================================

/**
 * Get current user's preferences
 * @returns {Promise<Object>}
 */
export async function getPreferences() {
    return await apiRequest('/api/preferences/me');
}

/**
 * Update current user's preferences
 * @param {Object} preferences - Preferences to update
 * @returns {Promise<Object>}
 */
export async function updatePreferences(preferences) {
    return await apiRequest('/api/preferences/me', {
        method: 'PUT',
        body: JSON.stringify(preferences)
    });
}

/**
 * Reset preferences to defaults
 * @returns {Promise<Object>}
 */
export async function resetPreferences() {
    return await apiRequest('/api/preferences/me', {
        method: 'DELETE'
    });
}
