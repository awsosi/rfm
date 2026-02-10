/**
 * Main Application Controller
 * Initializes and manages the file explorer application
 */

import { checkAuth, logout, getCurrentUser, isAdmin, setupAutoRefresh } from './auth.js';
import { initI18n, translatePage, t, setLocale } from './i18n.js';
import {
    listFiles,
    searchFiles,
    createDirectory,
    renameFile,
    deleteFiles,
    copyFiles,
    moveFiles,
    getOperations,
    cancelOperation,
    connectWebSocket,
    disconnectWebSocket,
    onWebSocketEvent,
    isWebSocketConnected,
    startPolling,
    pushOperation,
    pullOperation,
    getOperationHistory,
    searchOperations
} from './api.js';
import {
    renderFileList,
    showLoading,
    hideLoading,
    getSelectedFiles,
    clearSelection,
    navigateToDirectory,
    updateOperationStatus,
    clearOperationStatus,
    updateProgress,
    hideProgress,
    addOperationToQueue,
    updateOperationInQueue,
    removeOperationFromQueue,
    setupSelectAll,
    showError,
    showSuccess,
    showInfo,
    confirmAction,
    promptUser,
    disableOperationButtons,
    enableOperationButtons,
    getCurrentPath,
    setCurrentPath,
    renderOperationQueue,
    updateOperationInQueueTable,
    getSelectedOperationId,
    showQueueLoading,
    hideQueueLoading,
    filterDirectoriesOnly,
    markDirectoryRows,
    updatePushButtonState,
    updatePullButtonState
} from './ui.js';
import { normalizePath, joinPath, debounce } from './utils.js';

// Application state
const state = {
    panes: {
        a: {
            currentPath: 'A:',
            files: [],
            offset: 0,
            isSearching: false,
            sortBy: 'modified',
            sortOrder: 'desc',
            isLoading: false // Track if directory load is in progress
        },
        b: {
            currentPath: 'B:',
            files: [],
            offset: 0,
            isSearching: false,
            sortBy: 'modified',
            sortOrder: 'desc',
            isLoading: false
        }
    },
    operations: new Map(),
    refreshInterval: null,
    // VF Redesign: Operation queue state
    operationQueue: {
        operations: [],
        offset: 0,
        filters: {
            status: null,
            type: null
        },
        searchQuery: null,
        sortBy: 'timestamp',
        sortOrder: 'desc'
    },
    // VF Redesign: Worker ID (for single worker operations)
    workerId: 1, // Default to first worker, can be updated from settings
    // VF Redesign: Auto-refresh intervals
    autoRefreshIntervals: {
        operationHistory: null,
        fileList: null
    },
    // User interaction tracking to prevent refresh race conditions
    userInteraction: {
        lastInputTime: 0, // Timestamp of last user input in path field
        isTyping: false // Whether user is currently typing
    }
};

/**
 * Initialize application
 */
async function init() {
    // Initialize i18n first
    await initI18n();
    translatePage();

    // Update page title
    document.title = t('explorer.pageTitle');

    // Parse URL parameters for deep linking (Windows client integration)
    const urlParams = new URLSearchParams(window.location.search);
    const action = urlParams.get('action');       // 'prepare' or 'push'
    const path = urlParams.get('path');           // Real Windows path
    const token = urlParams.get('token');         // JWT token

    // Token-based auto-login (if token provided and not already logged in)
    if (token && !checkAuth()) {
        const { TOKEN_KEY, USER_KEY, TOKEN_EXPIRY_KEY, API_BASE_URL } = await import('./auth.js');
        sessionStorage.setItem(TOKEN_KEY, token);

        // Validate token by fetching user data
        try {
            const userResponse = await fetch(`${API_BASE_URL}/api/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (userResponse.ok) {
                const userData = await userResponse.json();
                sessionStorage.setItem(USER_KEY, JSON.stringify({
                    id: userData.user_id,
                    username: userData.username,
                    role: userData.role
                }));
                // Set token expiry
                const expiryTime = Date.now() + userData.expires_in * 1000;
                sessionStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());
            } else {
                // Invalid token, redirect to login
                window.location.href = 'login.html';
                return;
            }
        } catch (error) {
            console.error('Token validation failed:', error);
            window.location.href = 'login.html';
            return;
        }
    }

    // Check authentication
    if (!checkAuth()) {
        window.location.href = 'login.html';
        return;
    }

    // Get current user
    const user = getCurrentUser();
    if (!user) {
        window.location.href = 'login.html';
        return;
    }

    // Set user info in header
    document.getElementById('user-name').textContent = user.username;
    document.getElementById('user-role').textContent = user.role;

    // Show/hide admin button
    if (isAdmin()) {
        document.getElementById('admin-btn').style.display = 'block';
    }

    // Load and apply user theme preference
    try {
        const { getPreferences } = await import('./api.js');
        const preferences = await getPreferences();
        applyTheme(preferences.ui_theme || 'system');
    } catch (error) {
        console.error('Failed to load theme preference:', error);
        // Fall back to system theme if preferences fail to load
        applyTheme('system');
    }

    // Setup listener for system theme changes
    setupSystemThemeListener();

    // Setup listener for locale changes
    document.addEventListener('localechange', () => {
        translatePage();
        document.title = t('explorer.pageTitle');
    });

    // Setup auto token refresh
    setupAutoRefresh();

    // Setup event listeners
    setupEventListeners();

    // VF Redesign: Check if we're on the redesigned layout
    const isVFRedesign = document.body.classList.contains('vf-redesign');

    // Determine initial path for Path A (use last visited if remember_last_paths is enabled)
    let initialPathA = 'A:';
    try {
        const { getPreferences } = await import('./api.js');
        const preferences = await getPreferences();
        if (preferences.remember_last_paths && preferences.last_path_a) {
            initialPathA = preferences.last_path_a;
        }
    } catch (error) {
        console.error('Failed to load last path preference:', error);
    }

    if (isVFRedesign) {
        // Initialize single pane (Path A only)
        try {
            await loadDirectory('a', initialPathA);
        } catch (error) {
            console.error('Failed to load last path, falling back to root:', error);
            // Graceful fallback: if last path doesn't exist, load root
            await loadDirectory('a', 'A:');
        }

        // Load operation history
        await loadOperationHistory();
    } else {
        // Initialize both panes (legacy dual-pane)
        try {
            await loadDirectory('a', initialPathA);
        } catch (error) {
            console.error('Failed to load last path, falling back to root:', error);
            await loadDirectory('a', 'A:');
        }
        await loadDirectory('b', 'B:');
    }

    // Connect WebSocket for real-time updates
    await connectWebSocket();

    // Setup WebSocket event handler
    onWebSocketEvent(handleWebSocketEvent);

    // Fallback: Start polling if WebSocket not connected after 5 seconds
    setTimeout(() => {
        if (!isWebSocketConnected()) {
            console.log('WebSocket not connected, falling back to polling');
            startPolling(handlePollingUpdate, 5000);
        }
    }, 5000);

    // Load active operations
    await loadActiveOperations();

    // VF Redesign: Start auto-refresh for operation history and file list
    if (isVFRedesign) {
        startAutoRefresh();
    }

    // Handle deep link actions (Windows client integration)
    if (action && path) {
        if (action === 'prepare') {
            handlePrepareAction(path);
        } else if (action === 'push') {
            await handlePushAction(path);
        }

        // Clean URL parameters (prevent re-trigger on refresh)
        const url = new URL(window.location);
        url.searchParams.delete('action');
        url.searchParams.delete('path');
        url.searchParams.delete('token');
        window.history.replaceState({}, '', url);
    }

    console.log('Application initialized');
}

/**
 * Start auto-refresh for Operation History and file listings (VF Redesign)
 *
 * CRITICAL: Polling runs SILENTLY in the background without showing loading indicators.
 * - WebSocket provides instant updates for operations
 * - Polling (5s) detects external file changes (files added/modified outside the app)
 * - No visual interruption: no loading spinners, no flicker, typing is not interrupted
 * - Only user-initiated actions (clicking refresh, navigating) show loading indicators
 */
function startAutoRefresh() {
    // Silent background polling: Refresh Operation History every 10 seconds
    // Primary updates come via WebSocket 'operation_update' events
    // Polling is slower here because operations always go through the API (always trigger WebSocket)
    state.autoRefreshIntervals.operationHistory = setInterval(async () => {
        try {
            // Note: loadOperationHistory doesn't show loading indicator anyway
            await loadOperationHistory(false);
        } catch (error) {
            console.error('[Polling] Auto-refresh operation history failed:', error);
        }
    }, 10000);

    // Silent background polling: Refresh Path A file listing every 5 seconds
    // This is CRITICAL for detecting external file changes (files added/modified outside the app)
    // Uses silent mode - no loading indicator, no visual interruption
    state.autoRefreshIntervals.fileList = setInterval(async () => {
        try {
            // Skip refresh if user is actively typing in path or search input
            if (shouldSkipAutoRefresh('a')) {
                return;
            }
            // SILENT refresh - updates data without showing loading indicator
            await refreshPane('a', true);  // silent = true
        } catch (error) {
            console.error('[Polling] Auto-refresh file list failed:', error);
        }
    }, 5000);

    console.log('Silent background polling started (5s for files, 10s for operations). No loading indicators, no flicker.');
}

/**
 * Determine if auto-refresh should be skipped to prevent race conditions
 * @param {string} paneId - Pane ID
 * @returns {boolean} True if refresh should be skipped
 */
function shouldSkipAutoRefresh(paneId) {
    const pane = state.panes[paneId];

    // Skip if navigation/loading is already in progress
    if (pane.isLoading) {
        return true;
    }

    // Skip if user is currently typing in the path input
    const pathInput = document.getElementById(`path-input-${paneId}`);
    if (pathInput && document.activeElement === pathInput) {
        return true;
    }

    // Skip if user recently typed (within last 2 seconds)
    const timeSinceLastInput = Date.now() - state.userInteraction.lastInputTime;
    if (timeSinceLastInput < 2000) {
        return true;
    }

    // Skip if search input has focus (user might be typing search query)
    const searchInput = document.getElementById(`search-${paneId}`);
    if (searchInput && document.activeElement === searchInput) {
        return true;
    }

    return false;
}

/**
 * Stop auto-refresh (VF Redesign)
 */
function stopAutoRefresh() {
    if (state.autoRefreshIntervals.operationHistory) {
        clearInterval(state.autoRefreshIntervals.operationHistory);
        state.autoRefreshIntervals.operationHistory = null;
    }

    if (state.autoRefreshIntervals.fileList) {
        clearInterval(state.autoRefreshIntervals.fileList);
        state.autoRefreshIntervals.fileList = null;
    }

    console.log('Auto-refresh stopped');
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Logout button
    document.getElementById('logout-btn').addEventListener('click', () => {
        stopAutoRefresh();
        disconnectWebSocket();
        logout();
        window.location.href = 'login.html';
    });

    // Admin button
    document.getElementById('admin-btn').addEventListener('click', () => {
        window.location.href = 'admin.html';
    });

    // Settings button
    document.getElementById('settings-btn').addEventListener('click', async () => {
        await openSettingsModal();
    });

    // VF Redesign: Check if we're on the redesigned layout
    const isVFRedesign = document.body.classList.contains('vf-redesign');

    if (isVFRedesign) {
        // Setup single pane controls (Path A only)
        setupPaneControls('a');
        setupSelectAll('a');

        // Setup VF redesign buttons and filters
        setupVFRedesignControls();
    } else {
        // Setup dual pane controls (legacy)
        setupPaneControls('a');
        setupPaneControls('b');
        setupSelectAll('a');
        setupSelectAll('b');

        // Setup operation buttons (legacy)
        setupOperationButtons();
    }

    // Path change event
    document.addEventListener('pathchange', async (e) => {
        const { paneId, path } = e.detail;
        await loadDirectory(paneId, path);
    });

    // Context menu action event
    document.addEventListener('contextmenuaction', async (e) => {
        const { action, file, paneId } = e.detail;
        await handleContextMenuAction(action, file, paneId);
    });

    // Cancel operation event
    document.addEventListener('canceloperation', async (e) => {
        const { operationId } = e.detail;
        await handleCancelOperation(operationId);
    });
}

/**
 * Setup pane controls
 * @param {string} paneId - Pane ID
 */
function setupPaneControls(paneId) {
    const pathInput = document.getElementById(`path-input-${paneId}`);

    // Track user typing in path input to prevent refresh race conditions
    pathInput.addEventListener('input', () => {
        state.userInteraction.lastInputTime = Date.now();
        state.userInteraction.isTyping = true;
    });

    pathInput.addEventListener('focus', () => {
        state.userInteraction.isTyping = true;
    });

    pathInput.addEventListener('blur', () => {
        state.userInteraction.isTyping = false;
    });

    // Path go button
    document.getElementById(`path-go-${paneId}`).addEventListener('click', async () => {
        const path = pathInput.value;
        await loadDirectory(paneId, path);
    });

    // Path input enter key
    pathInput.addEventListener('keypress', async (e) => {
        if (e.key === 'Enter') {
            const path = e.target.value;
            await loadDirectory(paneId, path);
        }
    });

    // Refresh button
    document.getElementById(`refresh-${paneId}`).addEventListener('click', async () => {
        await refreshPane(paneId);
    });

    // Search button
    const searchBtn = document.getElementById(`search-btn-${paneId}`);
    if (searchBtn) {
        searchBtn.addEventListener('click', async () => {
            await handleSearch(paneId);
        });
    }

    // Search input enter key and debounced input
    const searchInput = document.getElementById(`search-${paneId}`);
    if (searchInput) {
        searchInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
                await handleSearch(paneId);
            }
        });

        // Search input with debounce
        searchInput.addEventListener('input', debounce(async () => {
            if (searchInput.value) {
                await handleSearch(paneId);
            } else {
                await refreshPane(paneId);
            }
        }, 500));
    }

    // Load more button
    document.getElementById(`load-more-${paneId}`).addEventListener('click', async () => {
        await loadMoreFiles(paneId);
    });

    // Column sorting
    setupColumnSorting(paneId);
}

/**
 * Setup column sorting for file list
 * @param {string} paneId - Pane ID
 */
function setupColumnSorting(paneId) {
    const fileList = document.getElementById(`file-list-${paneId}`);
    if (!fileList) return;

    const sortableHeaders = fileList.querySelectorAll('th.sortable');
    sortableHeaders.forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
            const sortBy = header.dataset.sortBy;
            handleColumnSort(paneId, sortBy);
        });
    });
}

/**
 * Handle column sort
 * @param {string} paneId - Pane ID
 * @param {string} sortBy - Column to sort by
 */
function handleColumnSort(paneId, sortBy) {
    const pane = state.panes[paneId];

    // Toggle sort order if clicking same column
    if (pane.sortBy === sortBy) {
        pane.sortOrder = pane.sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        pane.sortBy = sortBy;
        pane.sortOrder = 'asc';
    }

    // Re-sort and re-render files
    const sortedFiles = sortFiles(pane.files, pane.sortBy, pane.sortOrder);
    renderFileList(paneId, sortedFiles, false);
    markDirectoryRows(paneId);

    // Update sort arrows in header
    updateSortArrows(paneId, pane.sortBy, pane.sortOrder);
}

/**
 * Update sort arrows in table header
 * @param {string} paneId - Pane ID
 * @param {string} sortBy - Current sort column
 * @param {string} sortOrder - Current sort order
 */
function updateSortArrows(paneId, sortBy, sortOrder) {
    const fileList = document.getElementById(`file-list-${paneId}`);
    if (!fileList) return;

    const headers = fileList.querySelectorAll('th.sortable');
    headers.forEach(header => {
        const arrow = header.querySelector('.sort-arrow');
        if (!arrow) return;

        if (header.dataset.sortBy === sortBy) {
            header.classList.add(sortOrder === 'asc' ? 'sorted-asc' : 'sorted-desc');
            header.classList.remove(sortOrder === 'asc' ? 'sorted-desc' : 'sorted-asc');
            arrow.textContent = sortOrder === 'asc' ? '▲' : '▼';
        } else {
            header.classList.remove('sorted-asc', 'sorted-desc');
            arrow.textContent = '';
        }
    });
}

/**
 * Setup operation buttons
 */
function setupOperationButtons() {
    // Copy A to B
    document.getElementById('copy-a-to-b').addEventListener('click', async () => {
        await handleOperation('copy', 'a', 'b');
    });

    // Move A to B
    document.getElementById('move-a-to-b').addEventListener('click', async () => {
        await handleOperation('move', 'a', 'b');
    });

    // Copy B to A
    document.getElementById('copy-b-to-a').addEventListener('click', async () => {
        await handleOperation('copy', 'b', 'a');
    });

    // Move B to A
    document.getElementById('move-b-to-a').addEventListener('click', async () => {
        await handleOperation('move', 'b', 'a');
    });

    // New folder button
    document.getElementById('new-folder-btn').addEventListener('click', async () => {
        await handleNewFolder();
    });

    // Delete button
    document.getElementById('delete-btn').addEventListener('click', async () => {
        await handleDelete();
    });
}

/**
 * Validate Path A path
 * @param {string} path - Path to validate
 * @returns {boolean} True if valid
 * @throws {Error} If path is invalid
 */
function validatePathA(path) {
    if (!path) {
        throw new Error(t('errors.pathEmpty'));
    }

    const pathUpper = path.toUpperCase();

    // Path must start with A:
    if (!pathUpper.startsWith('A:')) {
        throw new Error(t('errors.pathInvalid'));
    }

    // Check for other drive letters in the path (B:, C:, D:, etc.)
    const pathAfterA = path.substring(2);
    const driveLetterRegex = /[B-Z]:/i;
    if (driveLetterRegex.test(pathAfterA)) {
        const match = pathAfterA.match(driveLetterRegex);
        if (match) {
            throw new Error(t('errors.driveLetterNotAllowed', { letter: match[0] }));
        }
    }

    return true;
}

/**
 * Load directory contents
 * @param {string} paneId - Pane ID
 * @param {string} path - Directory path
 * @param {boolean} silent - If true, don't show loading indicator (for background polling)
 */
async function loadDirectory(paneId, path, silent = false) {
    const normalizedPath = normalizePath(path);

    // Validate Path A
    try {
        validatePathA(normalizedPath);
    } catch (error) {
        showError(error.message);
        if (!silent) hideLoading(paneId);
        return;
    }

    // Set loading flag to prevent race conditions with auto-refresh
    state.panes[paneId].isLoading = true;

    // Only show loading indicator if not silent (user-initiated actions only)
    if (!silent) {
        showLoading(paneId);
    }
    state.panes[paneId].isSearching = false;
    state.panes[paneId].offset = 0;

    try {
        let files = await listFiles(normalizedPath, 0, 50, state.workerId);

        // Filter out any ".." entries that might come from the backend
        files = files.filter(file => file.name !== '..' && !file.is_parent_dir);

        // Add parent directory (..) if not at root
        const isRoot = normalizedPath === 'A:' || normalizedPath === 'B:' ||
                       normalizedPath === 'A:/' || normalizedPath === 'B:/';

        if (!isRoot) {
            const parentPath = getParentPath(normalizedPath);
            files = [
                {
                    name: '..',
                    path: parentPath,
                    is_directory: true,
                    size_bytes: 0,
                    modified_at: null,
                    is_parent_dir: true
                },
                ...files
            ];
        }

        state.panes[paneId].currentPath = normalizedPath;
        state.panes[paneId].files = files;
        state.panes[paneId].offset = files.length;

        setCurrentPath(paneId, normalizedPath);

        // Sort files using current sort settings
        const pane = state.panes[paneId];
        const sortedFiles = sortFiles(files, pane.sortBy, pane.sortOrder);
        renderFileList(paneId, sortedFiles, false);
        markDirectoryRows(paneId); // Apply directory styling for VF redesign

        // Update sort arrows in header
        updateSortArrows(paneId, pane.sortBy, pane.sortOrder);

        // Save last visited path if remember_last_paths is enabled (for Path A only)
        if (paneId === 'a') {
            try {
                const { getPreferences, updatePreferences } = await import('./api.js');
                const preferences = await getPreferences();
                if (preferences.remember_last_paths) {
                    // Only update if path has changed to avoid unnecessary API calls
                    if (preferences.last_path_a !== normalizedPath) {
                        await updatePreferences({ last_path_a: normalizedPath });
                    }
                }
            } catch (error) {
                // Silently fail - this is a convenience feature, not critical
                console.debug('Failed to save last path preference:', error);
            }
        }

    } catch (error) {
        console.error(`Error loading directory for pane ${paneId}:`, error);
        showError(t('errors.failedToLoadDirectory', { error: error.message }));
        if (!silent) hideLoading(paneId);
    } finally {
        // Clear loading flag after navigation completes
        state.panes[paneId].isLoading = false;
        // Always hide loading indicator on completion (even in silent mode, in case it was shown before)
        if (!silent) hideLoading(paneId);
    }
}

/**
 * Get parent directory path
 * @param {string} path - Current path
 * @returns {string} Parent path
 */
function getParentPath(path) {
    // Remove trailing slash if present
    let cleanPath = path.replace(/\/$/, '');

    // Split by / and remove last segment
    const parts = cleanPath.split('/');

    if (parts.length <= 1) {
        // Already at root (e.g., 'A:' or 'B:')
        return cleanPath;
    }

    // Remove last part
    parts.pop();

    // If only drive letter remains, return it
    if (parts.length === 1) {
        return parts[0];
    }

    return parts.join('/');
}

/**
 * Sort files by column
 * @param {Array} files - Files array
 * @param {string} sortBy - Sort column (name, size, modified)
 * @param {string} sortOrder - Sort order (asc, desc)
 * @returns {Array} Sorted files
 */
function sortFiles(files, sortBy, sortOrder) {
    const sorted = [...files];

    // Separate parent directory (..) from other files
    const parentDir = sorted.find(f => f.is_parent_dir);
    const regularFiles = sorted.filter(f => !f.is_parent_dir);

    regularFiles.sort((a, b) => {
        let comparison = 0;

        switch (sortBy) {
            case 'name':
                comparison = a.name.localeCompare(b.name);
                break;
            case 'size':
                // Directories come first when sorting by size
                if (a.is_directory && !b.is_directory) return -1;
                if (!a.is_directory && b.is_directory) return 1;
                comparison = (a.size_bytes || 0) - (b.size_bytes || 0);
                break;
            case 'modified':
                const aTime = a.modified_at ? new Date(a.modified_at).getTime() : 0;
                const bTime = b.modified_at ? new Date(b.modified_at).getTime() : 0;
                comparison = aTime - bTime;
                break;
        }

        return sortOrder === 'asc' ? comparison : -comparison;
    });

    // Parent directory always comes first
    return parentDir ? [parentDir, ...regularFiles] : regularFiles;
}

/**
 * Refresh pane contents
 * @param {string} paneId - Pane ID
 * @param {boolean} silent - If true, don't show loading indicator (for background polling)
 */
async function refreshPane(paneId, silent = false) {
    const currentPath = state.panes[paneId].currentPath;
    await loadDirectory(paneId, currentPath, silent);
}

/**
 * Load more files (pagination)
 * @param {string} paneId - Pane ID
 */
async function loadMoreFiles(paneId) {
    const pane = state.panes[paneId];

    showLoading(paneId);

    try {
        const files = await listFiles(pane.currentPath, pane.offset, 50);

        pane.files.push(...files);
        pane.offset += files.length;

        renderFileList(paneId, files, true);
        markDirectoryRows(paneId); // Apply directory styling for VF redesign

    } catch (error) {
        console.error(`Error loading more files for pane ${paneId}:`, error);
        showError(t('errors.failedToLoadMore', { error: error.message }));
    } finally {
        hideLoading(paneId);
    }
}

/**
 * Handle search
 * @param {string} paneId - Pane ID
 */
async function handleSearch(paneId) {
    const searchInput = document.getElementById(`search-${paneId}`);
    if (!searchInput) {
        return;
    }

    const pattern = searchInput.value.trim();

    if (!pattern) {
        await refreshPane(paneId);
        return;
    }

    const currentPath = state.panes[paneId].currentPath;

    // Set loading flag to prevent race conditions with auto-refresh
    state.panes[paneId].isLoading = true;

    showLoading(paneId);
    state.panes[paneId].isSearching = true;

    try {
        // Pass workerId explicitly to search function
        const files = await searchFiles(currentPath, pattern, state.workerId);

        state.panes[paneId].files = files;

        // Apply current sorting to search results
        const pane = state.panes[paneId];
        const sortedFiles = sortFiles(files, pane.sortBy, pane.sortOrder);
        renderFileList(paneId, sortedFiles, false);
        markDirectoryRows(paneId);

        // Update sort arrows
        updateSortArrows(paneId, pane.sortBy, pane.sortOrder);

    } catch (error) {
        console.error(`Error searching files in pane ${paneId}:`, error);
        showError(t('errors.searchFailed', { error: error.message }));
    } finally {
        hideLoading(paneId);
        // Clear loading flag after search completes
        state.panes[paneId].isLoading = false;
    }
}

/**
 * Handle file operation (copy/move)
 * @param {string} operation - Operation type ('copy' or 'move')
 * @param {string} sourcePane - Source pane ID
 * @param {string} destPane - Destination pane ID
 */
async function handleOperation(operation, sourcePane, destPane) {
    const selectedFiles = getSelectedFiles(sourcePane);

    if (selectedFiles.length === 0) {
        showError('Please select files to ' + operation);
        return;
    }

    const destPath = state.panes[destPane].currentPath;

    // Confirm operation
    const confirmed = await confirmAction(
        `${operation === 'copy' ? 'Copy' : 'Move'} ${selectedFiles.length} file(s) to ${destPath}?`
    );

    if (!confirmed) {
        return;
    }

    disableOperationButtons();

    try {
        let result;
        if (operation === 'copy') {
            result = await copyFiles(selectedFiles, destPath);
        } else {
            result = await moveFiles(selectedFiles, destPath);
        }

        // Add to operation queue
        addOperationToQueue({
            operation_id: result.operation_id,
            operation_type: operation,
            status: 'in_progress',
            source_count: selectedFiles.length
        });

        showSuccess(`${operation === 'copy' ? 'Copy' : 'Move'} operation started`);

        // Clear selection
        clearSelection(sourcePane);

    } catch (error) {
        console.error(`Error starting ${operation} operation:`, error);
        showError(`Failed to start ${operation}: ${error.message}`);
    } finally {
        enableOperationButtons();
    }
}

/**
 * Handle new folder creation
 */
async function handleNewFolder() {
    // Ask which pane
    const paneOptions = await promptUser('Create folder in pane A or B?', 'a');

    if (!paneOptions || !['a', 'b'].includes(paneOptions.toLowerCase())) {
        return;
    }

    const paneId = paneOptions.toLowerCase();
    const currentPath = state.panes[paneId].currentPath;

    // Ask for folder name
    const folderName = await promptUser('Enter folder name:', 'New Folder');

    if (!folderName) {
        return;
    }

    const newPath = joinPath(currentPath, folderName);

    try {
        await createDirectory(newPath);
        showSuccess(`Folder created: ${folderName}`);
        await refreshPane(paneId);

    } catch (error) {
        console.error('Error creating folder:', error);
        showError(`Failed to create folder: ${error.message}`);
    }
}

/**
 * Handle file deletion
 */
async function handleDelete() {
    // Check both panes for selection
    const selectedA = getSelectedFiles('a');
    const selectedB = getSelectedFiles('b');
    const allSelected = [...selectedA, ...selectedB];

    if (allSelected.length === 0) {
        showError('Please select files to delete');
        return;
    }

    // Confirm deletion
    const confirmed = await confirmAction(
        `Delete ${allSelected.length} file(s)? This action cannot be undone.`
    );

    if (!confirmed) {
        return;
    }

    disableOperationButtons();

    try {
        await deleteFiles(allSelected);
        showSuccess(`Deleted ${allSelected.length} file(s)`);

        // Refresh both panes
        if (selectedA.length > 0) {
            await refreshPane('a');
        }
        if (selectedB.length > 0) {
            await refreshPane('b');
        }

    } catch (error) {
        console.error('Error deleting files:', error);
        showError(`Failed to delete files: ${error.message}`);
    } finally {
        enableOperationButtons();
    }
}

/**
 * Handle context menu action
 * @param {string} action - Action name
 * @param {Object} file - File object
 * @param {string} paneId - Pane ID
 */
async function handleContextMenuAction(action, file, paneId) {
    switch (action) {
        case 'open':
            if (file.is_directory) {
                navigateToDirectory(paneId, file.path);
            }
            break;

        case 'rename':
            await handleRename(file, paneId);
            break;

        case 'copy':
            // Copy to other pane
            const destPane = paneId === 'a' ? 'b' : 'a';
            const destPath = state.panes[destPane].currentPath;
            try {
                const result = await copyFiles([file.path], destPath);
                addOperationToQueue({
                    operation_id: result.operation_id,
                    operation_type: 'copy',
                    status: 'in_progress',
                    source_count: 1
                });
                showSuccess('Copy operation started');
            } catch (error) {
                showError(`Failed to copy: ${error.message}`);
            }
            break;

        case 'move':
            // Move to other pane
            const moveDestPane = paneId === 'a' ? 'b' : 'a';
            const moveDestPath = state.panes[moveDestPane].currentPath;
            try {
                const result = await moveFiles([file.path], moveDestPath);
                addOperationToQueue({
                    operation_id: result.operation_id,
                    operation_type: 'move',
                    status: 'in_progress',
                    source_count: 1
                });
                showSuccess('Move operation started');
                await refreshPane(paneId);
            } catch (error) {
                showError(`Failed to move: ${error.message}`);
            }
            break;

        case 'delete':
            const confirmed = await confirmAction(`Delete ${file.name}?`);
            if (confirmed) {
                try {
                    await deleteFiles([file.path]);
                    showSuccess('File deleted');
                    await refreshPane(paneId);
                } catch (error) {
                    showError(`Failed to delete: ${error.message}`);
                }
            }
            break;
    }
}

/**
 * Handle file rename
 * @param {Object} file - File object
 * @param {string} paneId - Pane ID
 */
async function handleRename(file, paneId) {
    const newName = await promptUser('Enter new name:', file.name);

    if (!newName || newName === file.name) {
        return;
    }

    const newPath = joinPath(state.panes[paneId].currentPath, newName);

    try {
        await renameFile(file.path, newPath);
        showSuccess('File renamed');
        await refreshPane(paneId);

    } catch (error) {
        console.error('Error renaming file:', error);
        showError(`Failed to rename: ${error.message}`);
    }
}

/**
 * Handle cancel operation
 * @param {string} operationId - Operation ID
 */
async function handleCancelOperation(operationId) {
    try {
        await cancelOperation(operationId);
        showSuccess('Operation cancelled');
        removeOperationFromQueue(operationId);

    } catch (error) {
        console.error('Error cancelling operation:', error);
        showError(`Failed to cancel operation: ${error.message}`);
    }
}

/**
 * Load active operations
 */
async function loadActiveOperations() {
    try {
        const operations = await getOperations('in_progress');

        operations.forEach(op => {
            addOperationToQueue(op);
        });

    } catch (error) {
        console.error('Error loading active operations:', error);
    }
}

/**
 * Handle WebSocket event
 * @param {Object} data - Event data
 */
function handleWebSocketEvent(data) {
    // VF Redesign: Check if we're on the redesigned layout
    const isVFRedesign = document.body.classList.contains('vf-redesign');

    if (isVFRedesign) {
        // Handle VF redesign events (real-time WebSocket updates)
        switch (data.event_type || data.type) {
            case 'operation_update':
                // Real-time operation status updates from backend
                handleVFOperationUpdate(data);
                break;

            case 'operation_started':
            case 'operation_progress':
            case 'operation_completed':
                // Legacy event types, handle same as operation_update
                handleVFOperationUpdate(data);
                break;

            case 'file_list_changed':
                // Real-time file listing change notification
                handleFileListChanged(data);
                break;

            case 'file_changed':
                // Legacy file change event
                if (data.path && data.path.startsWith(state.panes.a.currentPath)) {
                    refreshPane('a', true);  // silent refresh
                }
                break;

            case 'connected':
                // WebSocket connection established
                break;

            case 'heartbeat':
                // Heartbeat/ping from server (no action needed)
                break;
        }
    } else {
        // Legacy dual-pane event handling
        switch (data.type) {
            case 'operation_started':
                addOperationToQueue(data.operation);
                break;

            case 'operation_progress':
                updateOperationInQueue(data.operation);
                if (data.operation.progress !== undefined) {
                    updateProgress(data.operation.progress);
                }
                break;

            case 'operation_completed':
                updateOperationInQueue(data.operation);
                removeOperationFromQueue(data.operation.operation_id);
                hideProgress();

                if (data.operation.status === 'completed') {
                    showSuccess(`Operation completed: ${data.operation.operation_type}`);
                    // Refresh panes
                    refreshPane('a');
                    refreshPane('b');
                } else if (data.operation.status === 'failed') {
                    showError(`Operation failed: ${data.operation.error || 'Unknown error'}`);
                }
                break;

            case 'file_changed':
                // Refresh affected pane
                if (data.path) {
                    ['a', 'b'].forEach(paneId => {
                        if (data.path.startsWith(state.panes[paneId].currentPath)) {
                            refreshPane(paneId);
                        }
                    });
                }
                break;
        }
    }
}

/**
 * Handle polling update
 * @param {Array} operations - Array of operations
 */
function handlePollingUpdate(operations) {
    operations.forEach(op => {
        updateOperationInQueue(op);

        if (op.status === 'completed' || op.status === 'failed') {
            setTimeout(() => {
                removeOperationFromQueue(op.operation_id);
            }, 3000);
        }
    });
}


/**
 * Open settings modal and load current preferences
 */
/**
 * Detect system theme preference (light or dark)
 */
function getSystemTheme() {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

/**
 * Apply theme to the page
 */
function applyTheme(theme) {
    const effectiveTheme = theme === 'system' ? getSystemTheme() : theme;
    document.body.setAttribute('data-theme', effectiveTheme);

    // Store current theme setting for system theme change listener
    window._currentThemeSetting = theme;
}

/**
 * Setup system theme change listener
 * If user has selected 'system' theme, automatically update when OS/browser theme changes
 */
function setupSystemThemeListener() {
    if (window.matchMedia) {
        const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        darkModeQuery.addEventListener('change', (e) => {
            // Only apply if user has system theme selected
            if (window._currentThemeSetting === 'system') {
                document.body.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    }
}

/**
 * Open settings modal and load current preferences
 */
async function openSettingsModal() {
    try {
        const { getPreferences, updatePreferences, resetPreferences } = await import('./api.js');

        // Get settings modal elements
        const settingsModal = document.getElementById('settings-modal');
        const settingsForm = document.getElementById('settings-form');
        const settingsSave = document.getElementById('settings-save');
        const settingsCancel = document.getElementById('settings-cancel');
        const settingsReset = document.getElementById('settings-reset');
        const settingsClose = document.getElementById('settings-modal-close');

        // Load current preferences
        const preferences = await getPreferences();

        // Populate form with current preferences
        document.getElementById('ui-theme').value = preferences.ui_theme || 'system';

        // Normalize language preference (handle legacy 2-letter codes)
        let langValue = preferences.ui_language || 'auto';
        const langNormalizationMap = {
            'en': 'en-US',
            'pl': 'pl-PL',
            'en-US': 'en-US',
            'pl-PL': 'pl-PL',
            'auto': 'auto'
        };
        langValue = langNormalizationMap[langValue] || 'auto';
        document.getElementById('ui-language').value = langValue;

        document.getElementById('remember-last-paths').checked = preferences.remember_last_paths !== false;

        // Show modal
        settingsModal.classList.remove('hidden');

        // Save button handler
        const saveHandler = async () => {
            try {
                const updatedPreferences = {
                    ui_theme: document.getElementById('ui-theme').value,
                    ui_language: document.getElementById('ui-language').value,
                    remember_last_paths: document.getElementById('remember-last-paths').checked
                };

                await updatePreferences(updatedPreferences);
                showSuccess(t('settings.settingsSaved'));
                closeSettingsModal();

                // Apply theme immediately if changed
                if (updatedPreferences.ui_theme !== preferences.ui_theme) {
                    applyTheme(updatedPreferences.ui_theme);
                }

                // Apply language immediately if changed
                if (updatedPreferences.ui_language !== preferences.ui_language) {
                    const { getLocaleFromPreference } = await import('./i18n.js');
                    const locale = getLocaleFromPreference(updatedPreferences.ui_language);
                    await setLocale(locale);
                }
            } catch (error) {
                showError(t('settings.settingsFailed', { error: error.message }));
            }
        };

        // Reset button handler
        const resetHandler = async () => {
            if (confirm(t('settings.settingsResetConfirm'))) {
                try {
                    const defaultPrefs = await resetPreferences();
                    showSuccess(t('settings.settingsReset'));

                    // Re-populate form with defaults
                    document.getElementById('ui-theme').value = defaultPrefs.ui_theme || 'system';

                    // Normalize language preference (handle legacy 2-letter codes)
                    let defaultLangValue = defaultPrefs.ui_language || 'auto';
                    const langNormalizationMap = {
                        'en': 'en-US',
                        'pl': 'pl-PL',
                        'en-US': 'en-US',
                        'pl-PL': 'pl-PL',
                        'auto': 'auto'
                    };
                    defaultLangValue = langNormalizationMap[defaultLangValue] || 'auto';
                    document.getElementById('ui-language').value = defaultLangValue;

                    document.getElementById('remember-last-paths').checked = defaultPrefs.remember_last_paths !== false;

                    // Apply theme
                    applyTheme(defaultPrefs.ui_theme || 'system');

                    // Apply language
                    const { getLocaleFromPreference } = await import('./i18n.js');
                    const locale = getLocaleFromPreference(defaultPrefs.ui_language || 'auto');
                    await setLocale(locale);
                } catch (error) {
                    showError(t('settings.settingsResetFailed', { error: error.message }));
                }
            }
        };

        // Close handlers
        const closeSettingsModal = () => {
            settingsModal.classList.add('hidden');
            settingsSave.removeEventListener('click', saveHandler);
            settingsCancel.removeEventListener('click', closeSettingsModal);
            settingsReset.removeEventListener('click', resetHandler);
            settingsClose.removeEventListener('click', closeSettingsModal);
        };

        // Attach event listeners
        settingsSave.addEventListener('click', saveHandler);
        settingsCancel.addEventListener('click', closeSettingsModal);
        settingsReset.addEventListener('click', resetHandler);
        settingsClose.addEventListener('click', closeSettingsModal);

    } catch (error) {
        showError(t('settings.settingsLoadFailed', { error: error.message }));
        console.error('Settings error:', error);
    }
}

/* ==========================================
   VF REDESIGN - Push/Pull Operations & Queue
   ========================================== */

/**
 * Setup VF redesign controls (Push/Pull buttons and filters)
 */
function setupVFRedesignControls() {
    // Push button
    const pushBtn = document.getElementById('push-btn');
    if (pushBtn) {
        pushBtn.addEventListener('click', async () => {
            await handlePushOperation();
        });
    }

    // Pull button
    const pullBtn = document.getElementById('pull-btn');
    if (pullBtn) {
        pullBtn.addEventListener('click', async () => {
            await handlePullOperation();
        });
    }

    // Refresh queue button
    const refreshQueueBtn = document.getElementById('refresh-queue');
    if (refreshQueueBtn) {
        refreshQueueBtn.addEventListener('click', async () => {
            await loadOperationHistory();
        });
    }

    // Queue filter - status
    const statusFilter = document.getElementById('queue-filter-status');
    if (statusFilter) {
        statusFilter.addEventListener('change', async () => {
            state.operationQueue.filters.status = statusFilter.value || null;
            state.operationQueue.offset = 0;
            await loadOperationHistory();
        });
    }

    // Queue filter - type
    const typeFilter = document.getElementById('queue-filter-type');
    if (typeFilter) {
        typeFilter.addEventListener('change', async () => {
            state.operationQueue.filters.type = typeFilter.value || null;
            state.operationQueue.offset = 0;
            await loadOperationHistory();
        });
    }

    // Load more queue button
    const loadMoreQueue = document.getElementById('load-more-queue');
    if (loadMoreQueue) {
        loadMoreQueue.addEventListener('click', async () => {
            await loadOperationHistory(true);
        });
    }

    // Queue search button
    const queueSearchBtn = document.getElementById('queue-search-btn');
    const queueSearchInput = document.getElementById('queue-search-input');
    if (queueSearchBtn && queueSearchInput) {
        queueSearchBtn.addEventListener('click', async () => {
            state.operationQueue.searchQuery = queueSearchInput.value.trim();
            state.operationQueue.offset = 0;
            await loadOperationHistory();
        });

        // Also trigger search on Enter key
        queueSearchInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
                state.operationQueue.searchQuery = queueSearchInput.value.trim();
                state.operationQueue.offset = 0;
                await loadOperationHistory();
            }
        });
    }

    // Queue clear search button
    const queueClearSearchBtn = document.getElementById('queue-clear-search-btn');
    if (queueClearSearchBtn && queueSearchInput) {
        queueClearSearchBtn.addEventListener('click', async () => {
            queueSearchInput.value = '';
            state.operationQueue.searchQuery = null;
            state.operationQueue.offset = 0;
            await loadOperationHistory();
        });
    }

    // File selection change handler to update Push button state
    const fileListA = document.getElementById('file-list-body-a');
    if (fileListA) {
        fileListA.addEventListener('change', (e) => {
            if (e.target.type === 'radio') {
                updateVFButtonStates();
            }
        });
    }

    // Operation queue selection change handler to update Pull button state
    const queueTable = document.getElementById('queue-table-body');
    if (queueTable) {
        queueTable.addEventListener('change', (e) => {
            if (e.target.type === 'radio') {
                updateVFButtonStates();
            }
        });
    }

    // Operation History column sorting
    setupOperationQueueSorting();
}

/**
 * Setup column sorting for operation history table
 */
function setupOperationQueueSorting() {
    const queueTable = document.getElementById('queue-table');
    if (!queueTable) return;

    const sortableHeaders = queueTable.querySelectorAll('th.sortable');
    sortableHeaders.forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
            const sortBy = header.dataset.sortBy;
            handleOperationQueueSort(sortBy);
        });
    });
}

/**
 * Handle operation queue column sort
 * @param {string} sortBy - Column to sort by
 */
function handleOperationQueueSort(sortBy) {
    const queue = state.operationQueue;

    // Toggle sort order if clicking same column
    if (queue.sortBy === sortBy) {
        queue.sortOrder = queue.sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        queue.sortBy = sortBy;
        queue.sortOrder = 'asc';
    }

    // Re-sort and re-render operations
    const sortedOps = sortOperations(queue.operations, queue.sortBy, queue.sortOrder);
    renderOperationQueue(sortedOps, false);

    // Update sort arrows in header
    updateOperationQueueSortArrows(queue.sortBy, queue.sortOrder);
}

/**
 * Sort operations by column
 * @param {Array} operations - Operations array
 * @param {string} sortBy - Sort column
 * @param {string} sortOrder - Sort order (asc, desc)
 * @returns {Array} Sorted operations
 */
function sortOperations(operations, sortBy, sortOrder) {
    const sorted = [...operations];

    sorted.sort((a, b) => {
        let comparison = 0;

        switch (sortBy) {
            case 'id':
                comparison = (a.id || 0) - (b.id || 0);
                break;
            case 'type':
                comparison = (a.operation_type || '').localeCompare(b.operation_type || '');
                break;
            case 'status':
                comparison = (a.status || '').localeCompare(b.status || '');
                break;
            case 'directory':
                comparison = (a.original_path || '').localeCompare(b.original_path || '');
                break;
            case 'user':
                comparison = (a.username || '').localeCompare(b.username || '');
                break;
            case 'timestamp':
                const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
                const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
                comparison = aTime - bTime;
                break;
        }

        return sortOrder === 'asc' ? comparison : -comparison;
    });

    return sorted;
}

/**
 * Update sort arrows in operation queue table header
 * @param {string} sortBy - Current sort column
 * @param {string} sortOrder - Current sort order
 */
function updateOperationQueueSortArrows(sortBy, sortOrder) {
    const queueTable = document.getElementById('queue-table');
    if (!queueTable) return;

    const headers = queueTable.querySelectorAll('th.sortable');
    headers.forEach(header => {
        const arrow = header.querySelector('.sort-arrow');
        if (!arrow) return;

        if (header.dataset.sortBy === sortBy) {
            header.classList.add(sortOrder === 'asc' ? 'sorted-asc' : 'sorted-desc');
            header.classList.remove(sortOrder === 'asc' ? 'sorted-desc' : 'sorted-asc');
            arrow.textContent = sortOrder === 'asc' ? '▲' : '▼';
        } else {
            header.classList.remove('sorted-asc', 'sorted-desc');
            arrow.textContent = '';
        }
    });
}

/**
 * Load operation history (VF Redesign)
 */
async function loadOperationHistory(append = false) {
    showQueueLoading();

    try {
        const hasSearchQuery = state.operationQueue.searchQuery && state.operationQueue.searchQuery.trim() !== '';
        let operations;

        if (hasSearchQuery) {
            // Use search API with Elasticsearch
            const searchParams = {
                q: state.operationQueue.searchQuery,
                limit: 100,
                offset: append ? state.operationQueue.offset : 0,
                operation_type: state.operationQueue.filters.type,
                status: state.operationQueue.filters.status
            };

            const result = await searchOperations(searchParams);
            operations = result.operations;
        } else {
            // Use regular history API
            const filters = {
                limit: 100,
                offset: append ? state.operationQueue.offset : 0,
                operation_type: state.operationQueue.filters.type,
                status: state.operationQueue.filters.status
            };

            operations = await getOperationHistory(filters);
        }

        if (append) {
            state.operationQueue.operations.push(...operations);
            state.operationQueue.offset += operations.length;
        } else {
            state.operationQueue.operations = operations;
            state.operationQueue.offset = operations.length;
        }

        // Sort operations using current sort settings
        const queue = state.operationQueue;
        const sortedOps = sortOperations(queue.operations, queue.sortBy, queue.sortOrder);
        renderOperationQueue(sortedOps, append);

        // Update sort arrows in header
        updateOperationQueueSortArrows(queue.sortBy, queue.sortOrder);

        // Show/hide load more button
        const loadMoreBtn = document.getElementById('load-more-queue');
        if (loadMoreBtn) {
            if (operations.length < 100) {
                loadMoreBtn.classList.add('hidden');
            } else {
                loadMoreBtn.classList.remove('hidden');
            }
        }

    } catch (error) {
        console.error('Failed to load operation history:', error);
        showError(t('errors.failedToLoadOperationHistory', { error: error.message }));
    } finally {
        hideQueueLoading();
    }
}

/**
 * Handle Push operation (VF Redesign)
 */
async function handlePushOperation() {
    const selectedFiles = getSelectedFiles('a');

    if (selectedFiles.length === 0) {
        showError(t('operations.selectDirectory'));
        return;
    }

    if (selectedFiles.length > 1) {
        showError(t('operations.selectOneDirectory'));
        return;
    }

    const selectedFile = selectedFiles[0];

    // Ensure it's a directory
    if (!selectedFile.is_directory) {
        showError(t('operations.selectDirectoryNotFile'));
        return;
    }

    // Confirm operation
    const confirmed = await confirmAction(
        t('operations.pushDirectory', { name: selectedFile.name })
    );

    if (!confirmed) {
        return;
    }

    try {
        updateOperationStatus(t('operations.pushingDirectory'), 'info');

        const sourcePath = joinPath(state.panes.a.currentPath, selectedFile.name);
        const operation = await pushOperation(sourcePath, state.workerId);

        showSuccess(t('operations.pushStarted'));
        clearSelection('a');

        // Refresh operation history
        await loadOperationHistory();

        // Refresh Path A (directory will be archived)
        await refreshPane('a');

    } catch (error) {
        console.error('Push operation failed:', error);
        showError(t('operations.pushFailed', { error: error.message }));
    } finally {
        clearOperationStatus();
    }
}

/**
 * Handle Pull operation (VF Redesign)
 */
async function handlePullOperation() {
    const selectedOperationId = getSelectedOperationId();

    if (!selectedOperationId) {
        showError(t('operations.selectOperation'));
        return;
    }

    // Find the selected operation
    const operation = state.operationQueue.operations.find(op => op.id === selectedOperationId);

    if (!operation) {
        showError(t('operations.operationNotFound'));
        return;
    }

    // Confirm operation
    const confirmed = await confirmAction(
        t('operations.pullOperation', { id: operation.id, path: operation.original_path })
    );

    if (!confirmed) {
        return;
    }

    try {
        updateOperationStatus(t('operations.pullingOperation'), 'info');

        await pullOperation(selectedOperationId, state.workerId);

        showSuccess(t('operations.pullStarted'));

        // Refresh operation history
        await loadOperationHistory();

        // Refresh Path A if we're in the same directory
        if (operation.original_path) {
            if (state.panes.a.currentPath === operation.original_path ||
                operation.original_path.startsWith(state.panes.a.currentPath)) {
                await refreshPane('a');
            }
        }

    } catch (error) {
        console.error('Pull operation failed:', error);
        showError(t('operations.pullFailed', { error: error.message }));
    } finally {
        clearOperationStatus();
    }
}

/**
 * Update VF button states based on selections
 */
function updateVFButtonStates() {
    // Update Push button
    const selectedFiles = getSelectedFiles('a');
    const hasDirectorySelection = selectedFiles.length === 1 && selectedFiles[0].is_directory;
    updatePushButtonState(hasDirectorySelection);

    // Update Pull button
    const selectedOperationId = getSelectedOperationId();
    updatePullButtonState(!!selectedOperationId);
}

/**
 * Handle WebSocket operation updates for VF redesign (REAL-TIME)
 */
function handleVFOperationUpdate(data) {
    // Real-time refresh: Update operation history when ANY operation status changes
    loadOperationHistory(false).catch(err => {
        console.error('Failed to refresh operation history:', err);
    });

    // Update individual operation in queue if it exists (for instant UI feedback)
    if (data.operation_id) {
        const opIndex = state.operationQueue.operations.findIndex(
            op => op.id === data.operation_id
        );

        if (opIndex !== -1) {
            // Update local state
            state.operationQueue.operations[opIndex] = {
                ...state.operationQueue.operations[opIndex],
                status: data.status,
                ...data
            };

            // Update UI
            updateOperationInQueueTable(state.operationQueue.operations[opIndex]);
        }
    }
}

/**
 * Handle WebSocket file list changed events for VF redesign (REAL-TIME)
 * @param {Object} data - File list changed event data
 */
function handleFileListChanged(data) {
    // Check if the changed path affects the currently displayed directory
    const currentPath = state.panes.a.currentPath;

    // Refresh if:
    // 1. Changed path matches current path exactly, OR
    // 2. Changed path is a parent of current path (affects current view), OR
    // 3. Current path is a parent of changed path (subdirectory changed)
    const shouldRefresh =
        currentPath === data.path ||
        currentPath.startsWith(data.path) ||
        data.path.startsWith(currentPath);

    if (shouldRefresh) {
        // Skip refresh if user is actively interacting
        if (shouldSkipAutoRefresh('a')) {
            return;
        }

        // Use silent mode - no loading indicator for real-time updates
        refreshPane('a', true).catch(err => {
            console.error('Failed to refresh file listing:', err);
        });
    }
}

/**
 * Handle "prepare" action from Windows client deep link
 * Pre-select item in file list based on real Windows path
 *
 * @param {string} targetPath - Real Windows path (e.g., "\\server\share\folder" or "G:\folder")
 */
async function handlePrepareAction(targetPath) {
    console.log('Deep link: Preparing to select folder from path:', targetPath);

    try {
        // Call path resolution API to convert Windows path to virtual path
        const { API_BASE_URL, getToken } = await import('./auth.js');
        const token = getToken();

        console.log('Deep link: Calling path resolution API...');
        const response = await fetch(`${API_BASE_URL}/api/path/resolve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                windows_path: targetPath,
                worker_id: state.workerId
            })
        });

        if (!response.ok) {
            const error = await response.json();
            console.error('Deep link: Path resolution failed:', error);
            throw new Error(error.detail || 'Failed to resolve path');
        }

        const pathInfo = await response.json();
        console.log('Deep link: Path resolved:', pathInfo);
        console.log('  Virtual path:', pathInfo.virtual_path);
        console.log('  Parent path:', pathInfo.parent_path);
        console.log('  Folder name:', pathInfo.folder_name);

        // Navigate to parent directory first
        if (pathInfo.parent_path !== state.panes.a.currentPath) {
            console.log('Deep link: Navigating to parent directory:', pathInfo.parent_path);
            await loadDirectory('a', pathInfo.parent_path);
        } else {
            console.log('Deep link: Already at parent directory:', pathInfo.parent_path);
        }

        // Wait for directory to load, then select the folder
        // Return a promise so callers can await completion
        return new Promise((resolve, reject) => {
            setTimeout(() => {
                const fileListBody = document.getElementById('file-list-body-a');
                if (!fileListBody) {
                    console.error('Deep link: File list body not found');
                    showError(t('errors.pathNotAllowed'));
                    reject(new Error('File list body not found'));
                    return;
                }

                const rows = fileListBody.querySelectorAll('tr');
                console.log(`Deep link: Searching for folder "${pathInfo.folder_name}" in ${rows.length} rows`);
                let found = false;

                for (const row of rows) {
                    const nameCell = row.querySelector('.file-name');
                    if (nameCell && nameCell.textContent.trim() === pathInfo.folder_name) {
                        const radio = row.querySelector('input[type="radio"]');
                        if (radio) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', { bubbles: true }));
                            row.scrollIntoView({ behavior: 'smooth', block: 'center' });

                            // Brief highlight
                            const originalBg = row.style.backgroundColor;
                            row.style.backgroundColor = 'var(--color-primary-light, #dbeafe)';
                            setTimeout(() => {
                                row.style.backgroundColor = originalBg;
                            }, 2000);

                            found = true;
                            console.log('Deep link: Successfully selected folder:', pathInfo.folder_name);
                            showSuccess(`Folder "${pathInfo.folder_name}" selected`);
                            resolve();
                            break;
                        }
                    }
                }

                if (!found) {
                    console.warn('Deep link: Folder not found in directory:', pathInfo.folder_name);
                    showError(t('errors.pathNotAllowed') + ': Folder not found');
                    reject(new Error('Folder not found'));
                }
            }, 1000); // Increased delay to ensure directory has fully loaded
        });

    } catch (error) {
        console.error('Deep link: Failed to resolve path:', error);
        showError(t('errors.pathNotAllowed') + ': ' + error.message);
        throw error;
    }
}

/**
 * Handle "push" action from Windows client deep link
 * Auto-trigger push operation after pre-selecting item
 *
 * @param {string} targetPath - Real Windows path
 */
async function handlePushAction(targetPath) {
    console.log('Deep link: Auto-triggering push for path:', targetPath);

    try {
        // First, select the item (await completion)
        console.log('Deep link: Step 1 - Selecting folder...');
        await handlePrepareAction(targetPath);

        console.log('Deep link: Step 2 - Folder selected, preparing to trigger push operation...');

        // Wait for selection to register, then trigger push
        await new Promise((resolve) => setTimeout(resolve, 500));

        const selectedFiles = getSelectedFiles('a');
        console.log('Deep link: Selected files:', selectedFiles);

        if (selectedFiles.length === 1 && selectedFiles[0].is_directory) {
            console.log('Deep link: Triggering push operation for directory:', selectedFiles[0].name);
            try {
                await handlePushOperation();
                console.log('Deep link: Push operation triggered successfully');
                showSuccess(`Push operation started for "${selectedFiles[0].name}"`);
            } catch (error) {
                console.error('Deep link: Push operation failed:', error);
                showError(t('operations.pushFailed').replace('{error}', error.message));
            }
        } else if (selectedFiles.length === 0) {
            console.error('Deep link: No directory selected for push');
            showError(t('operations.selectDirectory'));
        } else {
            console.error('Deep link: Selected item is not a directory');
            showError(t('operations.selectDirectoryNotFile'));
        }
    } catch (error) {
        console.error('Deep link: Failed to prepare push action:', error);
        showError(t('operations.pushFailed') + ': ' + error.message);
    }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
