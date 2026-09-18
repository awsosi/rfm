/**
 * Main Application Controller
 * Initializes and manages the file explorer application
 */

import { checkAuth, logout, getCurrentUser, isAdmin, setupAutoRefresh, redirectToLogin } from './auth.js';
import { initI18n, translatePage, t, setLocale, getCurrentLocale } from './i18n.js';
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
    pushOperationBatch,
    getPushSettings,
    pullOperation,
    preflightCatalog,
    updateOperation,
    uploadUpdateFile,
    discardUpload,
    getOperationDetails,
    retryPimDelivery,
    recheckRemoteSync,
    stopPimDelivery,
    stopRemoteSync,
    getOperationHistory,
    searchOperations,
    listActiveWorkers,
    apiRequest
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
    formatOperationStatus,
    formatPimDelivery,
    formatRemoteSync,
    getSelectedOperationId,
    showQueueLoading,
    hideQueueLoading,
    filterDirectoriesOnly,
    markDirectoryRows,
    updatePushButtonState,
    updatePullButtonState,
    updateUpdateButtonState
} from './ui.js';
import { normalizePath, joinPath, debounce, showDialog, formatFileSize, formatDateTime } from './utils.js';
import {
    DIALOGS,
    confirmDialog,
    getSuppressedDialogs,
    resetDialogCache
} from './dialogs.js';

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
    workerId: null, // Dynamically set from first active worker on initialization
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
    const path = urlParams.get('path');           // Real Windows path (single)
    const pathsParam = urlParams.get('paths');    // Real Windows paths (pipe-delimited)
    const pathParams = urlParams.getAll('path');  // Real Windows paths (repeatable)
    const token = urlParams.get('token');         // JWT token

    // Token-based auto-login (if token provided and not already logged in)
    if (token && !checkAuth()) {
        const { API_BASE_URL, storeSession } = await import('./auth.js');

        // Validate token by fetching the session it belongs to
        try {
            const userResponse = await fetch(`${API_BASE_URL}/api/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (userResponse.ok) {
                storeSession(await userResponse.json());
            } else {
                redirectToLogin();
                return;
            }
        } catch (error) {
            console.error('Token validation failed:', error);
            redirectToLogin();
            return;
        }
    }

    // Check authentication
    if (!checkAuth()) {
        redirectToLogin();
        return;
    }

    // Get current user
    const user = getCurrentUser();
    if (!user) {
        redirectToLogin();
        return;
    }

    // Set user info in header
    document.getElementById('user-name').textContent = user.username;
    document.getElementById('user-role').textContent = user.role;

    // Avatar initials: first letters of a dotted/underscored username, else
    // the first two characters. Purely decorative - the name is still shown.
    const initials = String(user.username || '')
        .split(/[._\s-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map(part => part[0])
        .join('') || String(user.username || '?').slice(0, 2);
    document.getElementById('user-avatar').textContent = initials;

    // Show/hide admin button
    if (isAdmin()) {
        document.getElementById('admin-btn').hidden = false;
    }

    // Fetch active workers and set worker ID
    try {
        const workers = await listActiveWorkers();
        if (workers && workers.length > 0) {
            // Set workerId to first active worker
            state.workerId = workers[0].id;
            console.log(`Using worker ID: ${state.workerId} (${workers[0].name})`);
        } else {
            // No active workers available
            console.warn('No active workers found');
            showError(t('errors.noWorkersAvailable') || 'No active workers available. Please contact your administrator.');
            // Set to null to prevent operations from being attempted
            state.workerId = null;
        }
    } catch (error) {
        console.error('Failed to fetch active workers:', error);
        showError(t('errors.failedToLoadWorkers') || 'Failed to load workers. Some features may not work correctly.');
        // Keep default value of 1 as fallback
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

    // Only load directories if we have a valid worker
    if (state.workerId !== null) {
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
    } else {
        // No workers available - show error message in the file list area
        console.warn('Skipping directory load - no workers available');
        showError(t('errors.noWorkersAvailable') || 'No active workers available. The file explorer cannot function without an active worker. Please contact your administrator.');
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
    const targetPaths = [];
    if (pathsParam) {
        pathsParam.split('|').forEach(p => {
            const trimmed = p.trim();
            if (trimmed) targetPaths.push(trimmed);
        });
    }
    if (pathParams && pathParams.length > 0) {
        pathParams.forEach(p => {
            const trimmed = p.trim();
            if (trimmed) targetPaths.push(trimmed);
        });
    } else if (path) {
        targetPaths.push(path);
    }

    if (action && targetPaths.length > 0) {
        if (action === 'prepare') {
            await handlePrepareAction(targetPaths);
        } else if (action === 'push') {
            await handlePushAction(targetPaths);
        }

        // Clean URL parameters (prevent re-trigger on refresh)
        const url = new URL(window.location);
        url.searchParams.delete('action');
        url.searchParams.delete('path');
        url.searchParams.delete('paths');
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

    // Breadcrumb display: click to enter edit mode
    const breadcrumbDisplay = document.getElementById(`breadcrumb-display-${paneId}`);
    if (breadcrumbDisplay) {
        breadcrumbDisplay.addEventListener('click', () => {
            enterBreadcrumbEditMode(paneId);
        });
    }

    // Track user typing in path input to prevent refresh race conditions
    pathInput.addEventListener('input', () => {
        state.userInteraction.lastInputTime = Date.now();
        state.userInteraction.isTyping = true;
    });

    pathInput.addEventListener('focus', () => {
        state.userInteraction.isTyping = true;
    });

    pathInput.addEventListener('blur', async () => {
        state.userInteraction.isTyping = false;
        // Skip if navigation was already triggered by Enter key
        if (pathInput._navigatingFromEnter) return;
        // On blur: navigate to typed path and return to breadcrumb display mode
        const path = pathInput.value.trim();
        if (path) {
            await loadDirectory(paneId, path);
        } else {
            // Restore breadcrumb display without navigating
            updateBreadcrumbDisplay(paneId, state.panes[paneId].currentPath);
        }
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
            pathInput._navigatingFromEnter = true;
            pathInput.blur(); // trigger UI switch; blur handler will skip due to flag
            await loadDirectory(paneId, path);
            pathInput._navigatingFromEnter = false;
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
    // Skip if no worker is available
    if (state.workerId === null) {
        return;
    }

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
        updateBreadcrumbDisplay(paneId, normalizedPath);

        // Sort files using current sort settings
        const pane = state.panes[paneId];
        const sortedFiles = sortFiles(files, pane.sortBy, pane.sortOrder);
        renderFileList(paneId, sortedFiles, false);
        markDirectoryRows(paneId); // Apply directory styling for VF redesign
        updateVFButtonStates(); // the selection may be gone (e.g. a pushed folder)

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
 * Update breadcrumb display for a pane (Windows Explorer style)
 * Shows clickable path segments; hides raw input and shows display div.
 * @param {string} paneId - Pane ID ('a' or 'b')
 * @param {string} path - Current path (e.g. 'A:/Folder/SubFolder')
 */
function updateBreadcrumbDisplay(paneId, path) {
    const display = document.getElementById(`breadcrumb-display-${paneId}`);
    const input = document.getElementById(`path-input-${paneId}`);
    if (!display) return;

    // Build segments: split by '/' or '\', preserving drive letter like 'A:'
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    display.innerHTML = '';

    let builtPath = '';
    parts.forEach((segment, index) => {
        // Build the cumulative path for this segment
        if (index === 0) {
            builtPath = segment; // e.g. 'A:'
        } else {
            builtPath = builtPath + '/' + segment;
        }

        if (index > 0) {
            const sep = document.createElement('span');
            sep.className = 'breadcrumb-sep';
            sep.textContent = '›';
            display.appendChild(sep);
        }

        const seg = document.createElement('span');
        seg.className = 'breadcrumb-seg';
        seg.textContent = segment;
        const segPath = builtPath; // capture for closure
        seg.addEventListener('click', (e) => {
            e.stopPropagation();
            navigateToDirectory(paneId, segPath);
        });
        display.appendChild(seg);
    });

    // Show display, hide input
    display.classList.remove('hidden');
    if (input) input.classList.add('hidden');
}

/**
 * Switch breadcrumb to edit mode: hide display, show raw input, focus it.
 * @param {string} paneId - Pane ID
 */
function enterBreadcrumbEditMode(paneId) {
    const display = document.getElementById(`breadcrumb-display-${paneId}`);
    const input = document.getElementById(`path-input-${paneId}`);
    if (!display || !input) return;
    display.classList.add('hidden');
    input.classList.remove('hidden');
    input.focus();
    input.select();
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

        case 'push': {
            if (!file.is_directory || file.is_parent_dir) {
                showError(t('operations.selectDirectoryNotFile'));
                break;
            }
            // Push exactly the folder that was right-clicked
            clearSelection(paneId);
            const checkbox = Array.from(document.querySelectorAll(`#file-list-body-${paneId} .file-select`))
                .find(input => input.dataset.path === file.path);
            if (checkbox) {
                checkbox.checked = true;
                checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            }
            await handlePushOperation();
            break;
        }

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

            case 'operation_integration_update':
                // PIM delivery or image host sync changed; the operation itself did not
                loadOperationHistory(false).catch(err => {
                    console.error('Failed to refresh operation history:', err);
                });
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
 * Render one toggle per registered confirmation. Checked = shown.
 * @param {Object} suppressed - { dialogKey: true }
 */
function renderDialogSettings(suppressed) {
    const container = document.getElementById('settings-dialogs');
    if (!container) return;
    container.textContent = '';

    DIALOGS.forEach(({ key, labelKey, helpKey }) => {
        const id = `dialog-${key.replace(/\./g, '-')}`;

        const field = document.createElement('div');
        field.className = 'toggle-field';

        const copy = document.createElement('span');
        copy.className = 'toggle-copy';
        const title = document.createElement('label');
        title.className = 'toggle-title';
        title.htmlFor = id;
        title.textContent = t(labelKey);
        const help = document.createElement('span');
        help.className = 'toggle-help';
        help.textContent = t(helpKey);
        copy.append(title, help);

        const toggle = document.createElement('span');
        toggle.className = 'toggle';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.id = id;
        input.dataset.dialogKey = key;
        input.checked = !suppressed[key];
        const track = document.createElement('span');
        track.className = 'toggle-track';
        track.setAttribute('aria-hidden', 'true');
        toggle.append(input, track);

        field.append(copy, toggle);
        container.appendChild(field);
    });
}

/** @returns {Object} { dialogKey: true } for every confirmation switched off */
function readDialogSettings() {
    const suppressed = {};
    document.querySelectorAll('#settings-dialogs input[data-dialog-key]').forEach(input => {
        if (!input.checked) suppressed[input.dataset.dialogKey] = true;
    });
    return suppressed;
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

        renderDialogSettings(await getSuppressedDialogs());

        // Show modal
        settingsModal.classList.remove('hidden');

        // Save button handler
        const saveHandler = async () => {
            try {
                const updatedPreferences = {
                    ui_theme: document.getElementById('ui-theme').value,
                    ui_language: document.getElementById('ui-language').value,
                    remember_last_paths: document.getElementById('remember-last-paths').checked,
                    // Merge: other keys may live in custom_settings too
                    custom_settings: {
                        ...(preferences.custom_settings || {}),
                        suppressed_dialogs: readDialogSettings()
                    }
                };

                await updatePreferences(updatedPreferences);
                resetDialogCache();
                showSuccess(t('settings.settingsSaved'));
                closeSettingsModal();

                // Apply theme immediately if changed
                if (updatedPreferences.ui_theme !== preferences.ui_theme) {
                    applyTheme(updatedPreferences.ui_theme);
                }

                // Apply language immediately if the desired locale differs from the active one
                const { getLocaleFromPreference } = await import('./i18n.js');
                const desiredLocale = getLocaleFromPreference(updatedPreferences.ui_language);
                if (desiredLocale !== getCurrentLocale()) {
                    await setLocale(desiredLocale);
                }
            } catch (error) {
                showError(t('settings.settingsFailed', { error: error.message }));
            }
        };

        // Reset button handler
        const resetHandler = async () => {
            if (await confirmDialog('settings.confirmReset', t('settings.settingsResetConfirm'))) {
                try {
                    const defaultPrefs = await resetPreferences();
                    resetDialogCache();
                    renderDialogSettings({});
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

    // Update catalog button
    const updateBtn = document.getElementById('update-btn');
    if (updateBtn) {
        updateBtn.addEventListener('click', async () => {
            await openUpdateModal();
        });
    }

    const updateModalClose = document.getElementById('update-modal-close');
    const updateModalCancel = document.getElementById('update-modal-cancel');
    const updateModalApply = document.getElementById('update-modal-apply');
    [updateModalClose, updateModalCancel].forEach(el => {
        if (el) el.addEventListener('click', () => requestCloseUpdateModal());
    });
    if (updateModalApply) {
        updateModalApply.addEventListener('click', async () => {
            await handleUpdateOperation();
        });
    }
    const addFromA = document.getElementById('update-add-from-a');
    if (addFromA) addFromA.addEventListener('click', () => addFilesFromPathA());
    const addUpload = document.getElementById('update-add-upload');
    const uploadInput = document.getElementById('update-upload-input');
    if (addUpload && uploadInput) {
        addUpload.addEventListener('click', () => uploadInput.click());
        uploadInput.addEventListener('change', () => {
            addUploadedFiles(uploadInput.files);
            uploadInput.value = '';
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
            if (e.target.classList && e.target.classList.contains('file-select')) {
                updateVFButtonStates();
            }
        });
    }

    // Operation queue selection change handler to update Pull button state
    const queueTable = document.getElementById('queue-table-body');
    if (queueTable) {
        // Operation numbers and "updated by" references open the details view
        queueTable.addEventListener('click', (e) => {
            const link = e.target.closest('[data-details-id]');
            if (link) openOperationDetails(parseInt(link.dataset.detailsId, 10));
        });

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
        updateVFButtonStates(); // a pulled PUSH can no longer be selected

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
// =========================================================================
// UPDATE catalog
// =========================================================================

// Working state of the update modal.
//   changes:   entry name -> { action: 'rename', dest } | { action: 'delete' }
//                            | { action: 'replace', content }
//   additions: [{ dest, content }]
//   content:   { kind: 'path', path, removeSource }
//            | { kind: 'upload', name, size, uploadId, progress, failed }
// Keyed by entry name, so one entry can never carry two conflicting changes.
const updateState = {
    catalogPath: null,
    catalogName: null,
    pushOperationId: null,
    entries: [],
    changes: new Map(),
    additions: [],
    applying: false
};

function resetUpdateState() {
    updateState.catalogPath = null;
    updateState.catalogName = null;
    updateState.pushOperationId = null;
    updateState.entries = [];
    updateState.changes = new Map();
    updateState.additions = [];
    updateState.applying = false;
}

/** Every content source currently in the draft. */
function draftContents() {
    const contents = [];
    updateState.changes.forEach(change => {
        if (change.content) contents.push(change.content);
    });
    updateState.additions.forEach(addition => contents.push(addition.content));
    return contents;
}

/**
 * Open the update modal for the PUSH selected in the operation history.
 */
async function openUpdateModal() {
    const selectedOperationId = getSelectedOperationId();
    if (!selectedOperationId) {
        showError(t('update.selectCatalog'));
        return;
    }

    const operation = state.operationQueue.operations.find(
        op => op.id === selectedOperationId
    );
    if (!operation || !operation.dest_path) {
        showError(t('operations.operationNotFound'));
        return;
    }

    // dest_path is the catalog in PATH_B, e.g. "B:/TORBA HB0788 FA0542-910 SILVER"
    resetUpdateState();
    updateState.catalogPath = operation.dest_path;
    updateState.catalogName = operation.dest_path.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    updateState.pushOperationId = operation.id;

    try {
        updateOperationStatus(t('validation.checking'), 'info');
        // listFiles returns the items array, not the response object
        const items = await listFiles(updateState.catalogPath, 0, 1000, state.workerId);
        // Drop the ".." navigation entry the worker prepends
        updateState.entries = items.filter(item => item.name !== '..');
    } catch (error) {
        console.error('Failed to list catalog for update:', error);
        showError(t('errors.failedToLoadDirectory', { error: error.message }));
        return;
    } finally {
        clearOperationStatus();
    }

    document.getElementById('update-catalog-name').textContent = updateState.catalogName;
    renderUpdateEntries();
    renderUpdateAdditions();
    renderUpdatePending();
    document.getElementById('update-modal').classList.remove('hidden');
}

/**
 * Close the modal. Uploads that were not applied are discarded right away
 * (the server would also expire them); after an apply the server has
 * already released them.
 */
function closeUpdateModal({ discardUploads = true } = {}) {
    document.getElementById('update-modal').classList.add('hidden');
    draftContents().forEach(content => {
        content.detached = true;
        if (discardUploads && content.kind === 'upload' && content.uploadId) {
            discardUpload(content.uploadId).catch(() => {});
        }
    });
    resetUpdateState();
}

async function requestCloseUpdateModal() {
    if (updateState.applying) return;
    if (updateState.changes.size > 0 || updateState.additions.length > 0) {
        const discard = await confirmDialog('update.discardChanges', t('update.discardConfirm'));
        if (!discard) return;
    }
    closeUpdateModal();
}

/**
 * Upload a file into a content source, updating its label as it goes.
 * A modal closed mid-upload discards the finished upload immediately.
 */
function startUpload(file, content) {
    Object.assign(content, {
        kind: 'upload', name: file.name, size: file.size,
        uploadId: null, progress: 0, failed: false
    });
    uploadUpdateFile(file, percent => {
        content.progress = percent;
        refreshContentLabel(content);
    }).then(result => {
        if (content.detached) {
            discardUpload(result.id).catch(() => {});
            return;
        }
        content.uploadId = result.id;
        content.size = result.size_bytes;
        refreshContentLabel(content);
        renderUpdatePending();
    }).catch(error => {
        if (content.detached) return;
        content.failed = true;
        refreshContentLabel(content);
        renderUpdatePending();
        showError(t('update.uploadFailed', { name: file.name, error: error.message }));
    });
}

function contentLabelText(content) {
    if (content.kind === 'path') {
        return content.path;
    }
    if (content.failed) {
        return t('update.uploadFailedShort', { name: content.name });
    }
    if (!content.uploadId) {
        return t('update.uploading', { name: content.name, percent: content.progress || 0 });
    }
    return t('update.uploaded', { name: content.name, size: formatFileSize(content.size) });
}

function refreshContentLabel(content) {
    if (content.labelEl) {
        content.labelEl.textContent = contentLabelText(content);
        content.labelEl.classList.toggle('text-danger', Boolean(content.failed));
    }
}

/**
 * Label + "remove from Path A" checkbox for a chosen content source.
 * Built with createElement/textContent: names come from the filesystem.
 */
function buildContentView(content) {
    const wrapper = document.createElement('div');
    wrapper.className = 'update-content';

    const label = document.createElement('span');
    label.className = 'update-content-label';
    content.labelEl = label;
    refreshContentLabel(content);
    wrapper.appendChild(label);

    if (content.kind === 'path') {
        const option = document.createElement('label');
        option.className = 'update-remove-source';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = Boolean(content.removeSource);
        checkbox.addEventListener('change', () => {
            content.removeSource = checkbox.checked;
            renderUpdatePending();
        });
        option.append(checkbox, document.createTextNode(' ' + t('update.removeFromPathA')));
        wrapper.appendChild(option);
    }
    return wrapper;
}

/**
 * Buttons choosing the replacement for one catalog file: a Path A file or
 * an upload. Calls onChosen once a source has been picked.
 */
function buildContentPicker(onChosen) {
    const wrapper = document.createElement('div');
    wrapper.className = 'update-content-picker';

    const fromA = document.createElement('button');
    fromA.type = 'button';
    fromA.className = 'btn btn-secondary btn-sm';
    fromA.textContent = t('update.fromPathA');
    fromA.addEventListener('click', async () => {
        const picked = await pickPathAFiles({ multiple: false });
        if (picked && picked.length > 0) {
            onChosen({ kind: 'path', path: picked[0].path, removeSource: false });
        }
    });

    const upload = document.createElement('button');
    upload.type = 'button';
    upload.className = 'btn btn-secondary btn-sm';
    upload.textContent = t('update.uploadFile');
    const input = document.createElement('input');
    input.type = 'file';
    input.hidden = true;
    upload.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            const content = {};
            startUpload(input.files[0], content);
            onChosen(content);
        }
    });

    wrapper.append(fromA, upload, input);
    return wrapper;
}

/**
 * Render one row per catalog entry with its action selector.
 */
function renderUpdateEntries() {
    const container = document.getElementById('update-entries');
    container.textContent = '';

    const table = document.createElement('table');
    table.className = 'data-table';
    const tbody = document.createElement('tbody');

    updateState.entries.forEach(entry => {
        const row = document.createElement('tr');

        const nameCell = document.createElement('td');
        nameCell.textContent = entry.name;
        if (entry.is_directory) {
            const badge = document.createElement('span');
            badge.className = 'badge';
            badge.textContent = '/';
            nameCell.appendChild(document.createTextNode(' '));
            nameCell.appendChild(badge);
        }
        row.appendChild(nameCell);

        const actionCell = document.createElement('td');
        const select = document.createElement('select');
        select.className = 'form-control';
        const options = [['none', t('update.actionNone')], ['rename', t('update.actionRename')]];
        if (!entry.is_directory) options.push(['replace', t('update.actionReplace')]);
        options.push(['delete', t('update.actionDelete')]);
        options.forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        });
        const existing = updateState.changes.get(entry.name);
        select.value = existing ? existing.action : 'none';
        actionCell.appendChild(select);
        row.appendChild(actionCell);

        const detailCell = document.createElement('td');
        row.appendChild(detailCell);

        const renderDetail = () => {
            detailCell.textContent = '';
            const change = updateState.changes.get(entry.name);
            if (!change) return;

            if (change.action === 'rename') {
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control';
                input.placeholder = t('update.newNamePlaceholder');
                input.value = change.dest || '';
                input.addEventListener('input', () => {
                    change.dest = input.value;
                    renderUpdatePending();
                });
                detailCell.appendChild(input);
            } else if (change.action === 'replace') {
                if (change.content) {
                    detailCell.appendChild(buildContentView(change.content));
                } else {
                    detailCell.appendChild(buildContentPicker(content => {
                        change.content = content;
                        renderDetail();
                        renderUpdatePending();
                    }));
                }
            }
        };

        select.addEventListener('change', () => {
            const previous = updateState.changes.get(entry.name);
            if (previous?.content?.kind === 'upload' && previous.content.uploadId) {
                discardUpload(previous.content.uploadId).catch(() => {});
            }
            if (previous?.content) previous.content.detached = true;

            if (select.value === 'none') {
                updateState.changes.delete(entry.name);
            } else {
                updateState.changes.set(entry.name, { action: select.value });
            }
            renderDetail();
            renderUpdatePending();
        });

        renderDetail();
        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    container.appendChild(table);
}

/**
 * Render files queued to be added: name in the catalog, source, remove button.
 */
function renderUpdateAdditions() {
    const container = document.getElementById('update-additions');
    container.textContent = '';
    container.hidden = updateState.additions.length === 0;
    if (container.hidden) return;

    const table = document.createElement('table');
    table.className = 'data-table';
    const tbody = document.createElement('tbody');

    updateState.additions.forEach(addition => {
        const row = document.createElement('tr');

        const nameCell = document.createElement('td');
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control';
        input.value = addition.dest;
        input.setAttribute('aria-label', t('update.newNameLabel'));
        input.addEventListener('input', () => {
            addition.dest = input.value;
            renderUpdatePending();
        });
        nameCell.appendChild(input);

        const sourceCell = document.createElement('td');
        sourceCell.appendChild(buildContentView(addition.content));

        const removeCell = document.createElement('td');
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-ghost btn-sm';
        remove.textContent = '×';
        remove.title = t('update.removeAction');
        remove.setAttribute('aria-label', t('update.removeAction'));
        remove.addEventListener('click', () => {
            addition.content.detached = true;
            if (addition.content.kind === 'upload' && addition.content.uploadId) {
                discardUpload(addition.content.uploadId).catch(() => {});
            }
            updateState.additions = updateState.additions.filter(a => a !== addition);
            renderUpdateAdditions();
            renderUpdatePending();
        });
        removeCell.appendChild(remove);

        row.append(nameCell, sourceCell, removeCell);
        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    container.appendChild(table);
}

async function addFilesFromPathA() {
    const picked = await pickPathAFiles({ multiple: true });
    (picked || []).forEach(file => {
        updateState.additions.push({
            dest: file.name,
            content: { kind: 'path', path: file.path, removeSource: false }
        });
    });
    renderUpdateAdditions();
    renderUpdatePending();
}

function addUploadedFiles(files) {
    Array.from(files).forEach(file => {
        const content = {};
        startUpload(file, content);
        updateState.additions.push({ dest: file.name, content });
    });
    renderUpdateAdditions();
    renderUpdatePending();
}

function contentFields(content) {
    if (content.kind === 'path') {
        return { from_path: content.path, remove_source: Boolean(content.removeSource) };
    }
    // `upload` is only used to describe the action; the server records its own copy
    return { upload_id: content.uploadId, upload: { filename: content.name, size_bytes: content.size } };
}

/** The draft as API actions (including incomplete ones - see validateUpdateDraft). */
function buildUpdateActions() {
    const actions = [];
    updateState.changes.forEach((change, name) => {
        if (change.action === 'rename') {
            actions.push({ action: 'rename', source: name, dest: (change.dest || '').trim() });
        } else if (change.action === 'delete') {
            actions.push({ action: 'delete', source: name });
        } else if (change.action === 'replace' && change.content) {
            actions.push({ action: 'replace', source: name, ...contentFields(change.content) });
        }
    });
    updateState.additions.forEach(addition => {
        actions.push({ action: 'add', dest: addition.dest.trim(), ...contentFields(addition.content) });
    });
    return actions;
}

/** @returns {string|null} Localised problem with the draft, or null when it can be applied */
function validateUpdateDraft() {
    const finalNames = new Set();
    const claim = (name) => {
        if (finalNames.has(name)) return t('update.errorNameTaken', { name });
        finalNames.add(name);
        return null;
    };

    for (const entry of updateState.entries) {
        const change = updateState.changes.get(entry.name);
        if (!change || change.action === 'replace') {
            const problem = claim(entry.name);
            if (problem) return problem;
        }
    }
    for (const [name, change] of updateState.changes) {
        if (change.action === 'rename') {
            const dest = (change.dest || '').trim();
            if (!dest) return t('update.errorRenameEmpty', { name });
            const problem = claim(dest);
            if (problem) return problem;
        }
        if (change.action === 'replace' && !change.content) {
            return t('update.errorReplaceNoFile', { name });
        }
    }
    for (const addition of updateState.additions) {
        const dest = addition.dest.trim();
        if (!dest) return t('update.errorAddEmpty');
        const problem = claim(dest);
        if (problem) return problem;
    }
    for (const content of draftContents()) {
        if (content.kind === 'upload' && content.failed) {
            return t('update.uploadFailedShort', { name: content.name });
        }
        if (content.kind === 'upload' && !content.uploadId) {
            return t('update.errorUploading');
        }
    }
    return null;
}

/**
 * One line describing an UPDATE action - used for the pending list, the
 * confirmation and the history details, so all three read the same.
 */
function describeUpdateAction(action) {
    const upload = action.upload || {};
    const file = upload.filename
        ? t('update.describeUploadedFile', {
            name: upload.filename,
            size: upload.size_bytes != null ? formatFileSize(upload.size_bytes) : '?'
        })
        : null;

    let text;
    switch (action.action) {
        case 'rename':
        case 'move':
            text = t('update.describeRename', { source: action.source, dest: action.dest });
            break;
        case 'delete':
            text = t('update.describeDelete', { source: action.source });
            break;
        case 'replace':
            text = t('update.describeReplace', { source: action.source, from: action.from_path || file });
            break;
        case 'add':
            text = t('update.describeAdd', { dest: action.dest, from: action.from_path || file });
            break;
        default:
            text = JSON.stringify(action);
    }

    if (action.remove_source) {
        if (action.source_removed === true) {
            text += ' — ' + t('update.describeSourceRemoved');
        } else if (action.source_removed === false) {
            text += ' — ' + t('update.describeSourceNotRemoved');
        } else {
            text += ' — ' + t('update.describeSourceWillBeRemoved');
        }
    }
    if (upload.sha256) {
        text += ' — ' + t('update.describeChecksum', { sha: upload.sha256.slice(0, 16) });
    }
    return text;
}

function renderUpdatePending() {
    const container = document.getElementById('update-pending');
    container.textContent = '';

    const actions = buildUpdateActions();
    if (actions.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'text-muted';
        empty.textContent = t('update.noPending');
        container.appendChild(empty);
        return;
    }

    const list = document.createElement('ul');
    actions.forEach(action => {
        const item = document.createElement('li');
        item.textContent = describeUpdateAction(action);
        list.appendChild(item);
    });
    container.appendChild(list);
}

/**
 * Let the user choose files in Path A.
 * @param {Object} options - { multiple }
 * @returns {Promise<Array<{path: string, name: string}>|null>} null when cancelled
 */
function pickPathAFiles({ multiple }) {
    const modal = document.getElementById('path-picker-modal');
    const pathLabel = document.getElementById('path-picker-path');
    const list = document.getElementById('path-picker-list');
    const choose = document.getElementById('path-picker-choose');
    const cancel = document.getElementById('path-picker-cancel');
    const close = document.getElementById('path-picker-close');

    document.getElementById('path-picker-title').textContent =
        t(multiple ? 'update.pickerTitleMultiple' : 'update.pickerTitle');

    const selected = new Map(); // path -> { path, name }
    const syncChoose = () => {
        choose.disabled = selected.size === 0;
        choose.textContent = selected.size > 1
            ? t('update.pickerChooseCount', { count: selected.size })
            : t('update.pickerChoose');
    };

    const load = async (path) => {
        pathLabel.textContent = path;
        list.textContent = t('explorer.loading');
        let items;
        try {
            items = await listFiles(path, 0, 1000, state.workerId);
        } catch (error) {
            list.textContent = t('errors.failedToLoadDirectory', { error: error.message });
            return;
        }

        list.textContent = '';
        const table = document.createElement('table');
        table.className = 'data-table';
        const tbody = document.createElement('tbody');

        const addRow = (label, onActivate, control = null, isDir = false) => {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            if (control) cell.appendChild(control);
            const text = document.createElement(isDir ? 'button' : 'label');
            if (isDir) {
                text.type = 'button';
                text.className = 'link-button';
                text.addEventListener('click', onActivate);
            } else if (control) {
                text.htmlFor = control.id;
            }
            text.textContent = label;
            cell.appendChild(text);
            row.appendChild(cell);
            tbody.appendChild(row);
        };

        if (path.replace(/\/+$/, '').toUpperCase() !== 'A:') {
            const parent = path.replace(/\/+$/, '').replace(/\/[^/]*$/, '') || 'A:';
            addRow('..', () => load(parent), null, true);
        }

        const sorted = items
            .filter(item => item.name !== '..')
            .sort((a, b) => (b.is_directory - a.is_directory) || a.name.localeCompare(b.name));

        sorted.forEach((item, index) => {
            const itemPath = joinPath(path, item.name);
            if (item.is_directory) {
                addRow(item.name + '/', () => load(itemPath), null, true);
                return;
            }
            const control = document.createElement('input');
            control.type = multiple ? 'checkbox' : 'radio';
            control.name = 'path-picker-choice';
            control.id = `path-picker-${index}`;
            control.checked = selected.has(itemPath);
            control.addEventListener('change', () => {
                if (!multiple) selected.clear();
                if (control.checked) {
                    selected.set(itemPath, { path: itemPath, name: item.name });
                } else {
                    selected.delete(itemPath);
                }
                syncChoose();
            });
            addRow(` ${item.name} (${formatFileSize(item.size_bytes)})`, null, control);
        });

        if (sorted.length === 0) {
            list.textContent = t('update.pickerEmpty');
            return;
        }
        table.appendChild(tbody);
        list.appendChild(table);
    };

    return new Promise(resolve => {
        const finish = (result) => {
            modal.classList.add('hidden');
            choose.removeEventListener('click', onChoose);
            cancel.removeEventListener('click', onCancel);
            close.removeEventListener('click', onCancel);
            resolve(result);
        };
        const onChoose = () => finish(Array.from(selected.values()));
        const onCancel = () => finish(null);

        choose.addEventListener('click', onChoose);
        cancel.addEventListener('click', onCancel);
        close.addEventListener('click', onCancel);

        syncChoose();
        modal.classList.remove('hidden');
        load(state.panes.a.currentPath || 'A:');
    });
}

/**
 * Submit the draft as an UPDATE operation.
 */
async function handleUpdateOperation() {
    if (updateState.applying) return;

    const problem = validateUpdateDraft();
    if (problem) {
        showError(problem);
        return;
    }

    const actions = buildUpdateActions();
    if (actions.length === 0) {
        showError(t('update.emptyActions'));
        return;
    }

    const count = (predicate) => actions.filter(predicate).length;
    const deletions = count(a => a.action === 'delete');
    const replacements = count(a => a.action === 'replace');
    const removals = count(a => a.remove_source);

    const lines = [
        t('update.confirmTitle', { count: actions.length, name: updateState.catalogName }),
        '',
        ...actions.map(action => '• ' + describeUpdateAction(action))
    ];
    if (deletions > 0) lines.push('', t('update.confirmIrreversible', { count: deletions }));
    if (replacements > 0) lines.push(t('update.confirmReplaceIrreversible', { count: replacements }));
    if (removals > 0) lines.push(t('update.confirmRemoveFromPathA', { count: removals }));

    const destructive = deletions + replacements + removals > 0;
    const confirmed = await confirmDialog(
        destructive ? 'update.confirmDestructive' : 'update.confirm',
        lines.join('\n')
    );
    if (!confirmed) return;

    const catalogName = updateState.catalogName;
    const applyButton = document.getElementById('update-modal-apply');
    updateState.applying = true;
    applyButton.disabled = true;

    try {
        updateOperationStatus(t('update.applying'), 'info');
        const result = await updateOperation(
            updateState.catalogPath,
            state.workerId,
            updateState.pushOperationId,
            actions.map(({ upload, ...action }) => action)
        );
        closeUpdateModal({ discardUploads: false });

        const warnings = result?.params_json?.warnings || [];
        if (warnings.length > 0) {
            showError(t('update.succeededWithWarnings', { name: catalogName, warnings: warnings.join(' ') }));
        } else {
            showSuccess(t('update.succeeded', { name: catalogName }));
        }

        await loadOperationHistory();
        if (removals > 0) await refreshPane('a');
    } catch (error) {
        console.error('Update operation failed:', error);

        // Once an operation was created and ran, the server has released its
        // uploads: they must be uploaded again before retrying. Rejections
        // before that point (400, preflight 422) leave them usable.
        const operationRan = error.status >= 500 || error.status === 409 || error.detail?.content?.staged;
        if (operationRan) {
            draftContents().forEach(content => {
                if (content.kind === 'upload' && content.uploadId) {
                    content.uploadId = null;
                    content.failed = true;
                    refreshContentLabel(content);
                }
            });
            renderUpdatePending();
        }

        if (error.detail && error.detail.error === 'validation_failed') {
            await showValidationFailure(error.detail, catalogName);
        } else {
            showError(t('update.failed', { error: error.message }));
        }
        if (operationRan) await loadOperationHistory();
    } finally {
        updateState.applying = false;
        applyButton.disabled = false;
        clearOperationStatus();
    }
}

// =========================================================================
// Operation details
// =========================================================================

// Operation whose details dialog is open, so integration actions can refresh it
let detailsOperationId = null;

/**
 * PIM delivery and image host sync for one operation, with the actions a
 * user can take: stop a pending PIM notification or an active check, send
 * the PIM event again, check the image host again.
 */
function buildIntegrationDetails(operation) {
    const pim = operation.pim_delivery;
    const sync = operation.remote_sync;
    const block = document.createElement('div');
    block.className = 'integration-details';
    if (!pim && !sync) return block;

    const when = formatDateTime;
    const stoppedBy = job => t('integration.stoppedBy', { time: when(job.cancelled_at), user: job.cancelled_by });
    const facts = document.createElement('dl');
    facts.className = 'operation-facts';
    const fact = (labelKey, value) => {
        if (value === null || value === undefined || value === '') return;
        const dt = document.createElement('dt');
        dt.textContent = t(labelKey);
        const dd = document.createElement('dd');
        dd.textContent = value;
        facts.append(dt, dd);
    };
    const actionButton = (labelKey, run, confirmKey = null) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-secondary btn-sm';
        button.textContent = t(labelKey);
        button.addEventListener('click', async () => {
            if (confirmKey) {
                const { confirmed } = await showDialog({ title: t(labelKey), message: t(confirmKey), confirmLabel: t(labelKey) });
                if (!confirmed) return;
            }
            button.disabled = true;
            try {
                await run();
                showSuccess(t(labelKey + 'Done'));
            } catch (error) {
                showError(t('integration.actionFailed', { error: error.message }));
            }
            loadOperationHistory(false).catch(() => {});
            if (detailsOperationId !== null) openOperationDetails(detailsOperationId);
        });
        return button;
    };

    if (pim) {
        fact('integration.pimLabel', formatPimDelivery(pim));
        fact('integration.eventType', pim.event_type);
        fact('integration.tgId', pim.tg_id);
        fact('integration.attemptsLabel', String(pim.attempts));
        fact('integration.deliveredLabel', when(pim.delivered_at));
        if (pim.status === 'PENDING' && pim.attempts > 0) {
            fact('integration.nextAttemptLabel', when(pim.next_attempt_at));
        }
        if (pim.cancelled_by) fact('integration.stoppedLabel', stoppedBy(pim));
        if (pim.status !== 'DELIVERED') fact('integration.lastErrorLabel', pim.last_error);
    }
    if (sync) {
        fact('integration.syncLabel', formatRemoteSync(sync));
        fact('integration.syncStarted', when(sync.started_at));
        fact('integration.lastCheckedLabel', when(sync.last_checked_at));
        if (sync.status === 'CHECKING') fact('integration.nextCheckLabel', when(sync.next_check_at));
        if (sync.cancelled_by) {
            fact('integration.stoppedLabel', stoppedBy(sync));
        } else {
            fact('integration.syncCompleted', when(sync.completed_at));
        }
        fact('integration.lastErrorLabel', sync.last_error);
    }
    block.appendChild(facts);

    if (sync && sync.status !== 'WAITING' && (sync.files || []).length > 0) {
        const list = document.createElement('ul');
        list.className = 'sync-files';
        sync.files.forEach(file => {
            const item = document.createElement('li');
            item.className = file.synced ? 'synced' : 'missing';
            item.textContent = (file.synced ? '✓ ' : '✗ ') + file.name
                + (!file.synced && file.status_code ? ` (HTTP ${file.status_code})` : '');
            list.appendChild(item);
        });
        block.appendChild(list);
    }

    const actions = document.createElement('div');
    actions.className = 'integration-actions';
    if (pim && pim.status === 'PENDING') {
        actions.appendChild(actionButton('integration.stopPim', () => stopPimDelivery(operation.id),
            'integration.stopPimConfirm'));
    }
    if (pim && pim.status !== 'DELIVERED') {
        actions.appendChild(actionButton('integration.retryPim', () => retryPimDelivery(operation.id)));
    }
    if (sync && ['WAITING', 'CHECKING'].includes(sync.status)) {
        actions.appendChild(actionButton('integration.stopSync', () => stopRemoteSync(operation.id),
            'integration.stopSyncConfirm'));
    }
    // A check cancelled by a PULL stays cancelled: the catalog is gone
    if (sync && (['CHECKING', 'TIMEOUT', 'SYNCED'].includes(sync.status) || sync.cancelled_by)) {
        actions.appendChild(actionButton('integration.recheckSync', () => recheckRemoteSync(operation.id)));
    }
    if (actions.children.length > 0) block.appendChild(actions);

    return block;
}

/**
 * Who did what, when, and with which result, for one operation.
 */
function buildOperationSummary(operation) {
    const block = document.createElement('div');
    block.className = `operation-summary status-${String(operation.status).toLowerCase()}`;

    const heading = document.createElement('div');
    heading.className = 'operation-summary-heading';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'operation-type ' + String(operation.type).toLowerCase();
    typeBadge.textContent = operation.type;
    const title = document.createElement('strong');
    title.textContent = ` #${operation.id} `;
    const status = document.createElement('span');
    status.className = 'operation-status ' + String(operation.status).toLowerCase().replace('_', '-');
    status.textContent = formatOperationStatus(operation.status);
    const who = document.createElement('span');
    who.className = 'text-muted';
    who.textContent = ' ' + t('details.by', { user: operation.user_name || '?' });
    heading.append(typeBadge, title, status, who);
    block.appendChild(heading);

    const facts = document.createElement('dl');
    facts.className = 'operation-facts';
    const fact = (labelKey, value) => {
        if (value === null || value === undefined || value === '') return;
        const dt = document.createElement('dt');
        dt.textContent = t(labelKey);
        const dd = document.createElement('dd');
        dd.textContent = value;
        facts.append(dt, dd);
    };
    const when = formatDateTime;
    fact('details.created', when(operation.created_at));
    fact('details.started', when(operation.started_at));
    fact('details.completed', when(operation.completed_at));
    fact('details.source', operation.source_path);
    if (operation.dest_path !== operation.source_path) fact('details.destination', operation.dest_path);
    fact('details.archive', operation.archive_path);
    if (operation.type !== 'UPDATE') fact('details.fileCount', operation.file_count);
    fact('details.error', operation.error_msg);
    block.appendChild(facts);
    block.appendChild(buildIntegrationDetails(operation));

    const params = operation.params_json || {};
    if (operation.type === 'UPDATE' && Array.isArray(params.actions)) {
        const list = document.createElement('ul');
        list.className = 'operation-actions';
        params.actions.forEach(action => {
            const item = document.createElement('li');
            item.textContent = describeUpdateAction(action);
            list.appendChild(item);
        });
        block.appendChild(list);
    }
    if (operation.type === 'PULL' && (params.update_operation_ids || []).length > 0) {
        const note = document.createElement('p');
        note.textContent = t('details.pullIncludedUpdates', {
            ids: params.update_operation_ids.map(id => '#' + id).join(', ')
        });
        block.appendChild(note);
    }
    (params.warnings || []).forEach(warning => {
        const note = document.createElement('p');
        note.className = 'text-danger';
        note.textContent = '⚠ ' + warning;
        block.appendChild(note);
    });

    return block;
}

async function openOperationDetails(operationId) {
    let details;
    try {
        details = await getOperationDetails(operationId);
    } catch (error) {
        showError(t('details.loadFailed', { error: error.message }));
        return;
    }

    detailsOperationId = operationId;
    const modal = document.getElementById('operation-details-modal');
    const body = document.getElementById('operation-details-body');
    body.textContent = '';

    const main = details.operation;
    document.getElementById('operation-details-title').textContent =
        t('details.titleFor', { type: main.type, id: main.id });

    const section = (headingText, children) => {
        const heading = document.createElement('h4');
        heading.textContent = headingText;
        body.appendChild(heading);
        children.forEach(child => body.appendChild(child));
    };

    body.appendChild(buildOperationSummary(main));

    if (details.push) {
        section(t('details.pushHeader'), [buildOperationSummary(details.push)]);
    }
    if (details.updates.length > 0) {
        section(t('details.updatesHeader', { count: details.updates.length }),
            details.updates.map(buildOperationSummary));
    } else if (main.type === 'PUSH') {
        const none = document.createElement('p');
        none.className = 'text-muted';
        none.textContent = t('details.noUpdates');
        section(t('details.updatesHeader', { count: 0 }), [none]);
    }
    if (details.pull && details.pull.id !== main.id) {
        section(t('details.pullHeader'), [buildOperationSummary(details.pull)]);
    }

    const closeButtons = [
        document.getElementById('operation-details-close'),
        document.getElementById('operation-details-ok')
    ];
    const close = () => {
        detailsOperationId = null;
        modal.classList.add('hidden');
        closeButtons.forEach(button => button.removeEventListener('click', close));
    };
    closeButtons.forEach(button => button.addEventListener('click', close));
    modal.classList.remove('hidden');
}

/**
 * The file name forms PIM accepts, as examples the user can copy.
 *
 * ``allowed_name_suffixes`` is configurable (Admin Panel -> Directory Content
 * Validation), so the message must be built from what the server sent rather
 * than hard-coding "3.png" in every locale.
 *
 * @param {Object} content - the content gate result from the 422 detail
 * @returns {string} e.g. "3.png, 3_ai.png"
 */
function acceptedNameForms(content) {
    const suffixes = Array.isArray(content?.allowed_name_suffixes)
        ? content.allowed_name_suffixes
        : [];
    return ['3.png', ...suffixes.map(suffix => `3${suffix}.png`)].join(', ');
}

/**
 * Turn a structured validation rejection into readable, localised text.
 *
 * The backend returns i18n keys (never English prose) plus the numbers and
 * names needed to fill them, so both gates render correctly in pl-PL and
 * en-US without the server knowing the user's locale.
 *
 * @param {Object} validation - { catalog, content } from the 422 detail
 * @returns {string} Multi-line message ready for the modal
 */
function formatValidationFailure(validation) {
    const lines = [];
    const catalog = validation?.catalog || {};
    const content = validation?.content || {};

    if (catalog.valid === false) {
        lines.push(t('validation.catalogTitle'));
        if (catalog.reason) {
            lines.push(t(`validation.${catalog.reason}`, { name: catalog.catalog_name || '' }));
        }
        if (Array.isArray(catalog.suggestions) && catalog.suggestions.length > 0) {
            lines.push('');
            lines.push(t('validation.suggestionsHeader'));
            catalog.suggestions.forEach(name => lines.push(`  • ${name}`));
        } else if (catalog.reason === 'catalogValidation.noMatch') {
            lines.push(t('validation.noSuggestions'));
        }
    }

    if (content.valid === false && content.staged) {
        // New content for an UPDATE was rejected after staging; nothing changed
        if (lines.length > 0) lines.push('');
        lines.push(t('validation.contentTitle'));
        const names = [
            ...(content.missing || []),
            ...(content.invalid_files || []).map(f => f.name)
        ].join(', ');
        lines.push(t(`validation.${content.reason}`, { names }));
        return lines.join('\n');
    }

    if (content.valid === false) {
        if (lines.length > 0) lines.push('');
        lines.push(t('validation.contentTitle'));
        const badNames = content.invalid_names || [];
        const nameRule = 'contentValidation.invalidFileNames';
        const forms = acceptedNameForms(content);
        if (content.reason) {
            const names = content.reason === nameRule
                ? badNames.join(', ')
                : (content.invalid_files || []).map(f => f.name).join(', ');
            lines.push(t(`validation.${content.reason}`, {
                images: content.image_count ?? 0,
                required: content.min_required ?? 0,
                names: names,
                forms: forms
            }));
        }
        if (content.reason !== nameRule && badNames.length > 0) {
            // Reported alongside another failure, so the user can fix both at once
            lines.push(t(`validation.${nameRule}`, {
                names: badNames.join(', '),
                forms: forms
            }));
        }
        lines.push('');
        lines.push(t('validation.summary', {
            images: content.image_count ?? 0,
            required: content.min_required ?? 0,
            total: content.total_files ?? 0
        }));
        // A file already listed as a bad name will not be sent anywhere
        const garbage = (content.non_image_files || []).filter(name => !badNames.includes(name));
        if (garbage.length > 0) {
            lines.push(t('validation.garbageNote', {
                count: garbage.length,
                names: garbage.slice(0, 10).join(', ')
            }));
        }
    }

    return lines.join('\n');
}

/**
 * Present a validation rejection. Informational only - these gates are hard
 * blocks with no override, so there is nothing to confirm.
 *
 * @param {Object} validation - { catalog, content }
 * @param {string} [pathLabel] - Directory the rejection applies to
 */
async function showValidationFailure(validation, pathLabel) {
    const body = formatValidationFailure(validation);
    const title = pathLabel
        ? `${t('validation.title')} — ${pathLabel}`
        : t('validation.title');
    await showDialog({ title, message: body, hideCancel: true, confirmLabel: t('modal.close') });
}

async function handlePushOperation() {
    const selectedFiles = getSelectedFiles('a');

    if (selectedFiles.length === 0) {
        showError(t('operations.selectDirectory'));
        return;
    }

    // Ensure it's a directory
    if (selectedFiles.some(file => !file.is_directory)) {
        showError(t('operations.selectDirectoryNotFile'));
        return;
    }

    // Fetch push settings for dynamic confirmation dialog
    let pushSettings;
    try {
        pushSettings = await getPushSettings();
    } catch (e) {
        pushSettings = { flatten: false, archive: false, ignore_masks: 'Thumbs.db' };
    }

    // Build dynamic confirmation message
    const selectedNames = selectedFiles.map(file => file.name);
    const confirmMsg = buildPushConfirmMessage(selectedNames, pushSettings);
    const confirmed = await confirmDialog('push.confirm', confirmMsg);

    if (!confirmed) {
        return;
    }

    try {
        updateOperationStatus(t('operations.pushingDirectory'), 'info');

        const sourcePaths = selectedFiles.map(file => joinPath(state.panes.a.currentPath, file.name));
        const result = await pushOperationBatch(sourcePaths, state.workerId);

        const failures = (result?.results || []).filter(item => !item.success);
        const successes = (result?.results || []).filter(item => item.success);

        if (successes.length > 0) {
            showSuccess(t('operations.pushBatchStarted', { count: successes.length }));
        }

        if (failures.length > 0) {
            // A validation rejection carries structured detail; show it in full
            // so the user sees the reason and any name suggestions, rather than
            // a truncated toast.
            const rejected = failures.filter(item => item.validation);
            const other = failures.filter(item => !item.validation);

            if (other.length > 0) {
                const preview = other
                    .slice(0, 3)
                    .map(item => `${item.source_path}: ${item.error || t('errors.unknown')}`)
                    .join('; ');
                showError(t('operations.pushBatchFailed', { count: other.length, errors: preview }));
            }

            for (const item of rejected) {
                await showValidationFailure(item.validation, item.source_path);
            }
        }

        clearSelection('a');
        updateVFButtonStates();

        // Refresh operation history
        await loadOperationHistory();

        // Refresh Path A (directory will be archived/deleted)
        await refreshPane('a');

    } catch (error) {
        console.error('Push operation failed:', error);
        if (error.detail && error.detail.error === 'validation_failed') {
            await showValidationFailure(error.detail);
        } else {
            showError(t('operations.pushFailed', { error: error.message }));
        }
    } finally {
        clearOperationStatus();
    }
}

/**
 * Build dynamic PUSH confirmation message based on current settings
 */
function buildPushConfirmMessage(name, settings) {
    const steps = [];
    let stepNum = 1;

    if (settings.flatten) {
        steps.push(`${stepNum++}. ${t('operations.pushStepCopyFlat')}`);
    } else {
        steps.push(`${stepNum++}. ${t('operations.pushStepCopyAll')}`);
    }

    if (settings.flatten) {
        steps.push(`${stepNum++}. ${t('operations.pushStepDestroySubfolders')}`);
    }

    if (settings.ignore_masks) {
        steps.push(`${stepNum++}. ${t('operations.pushStepDestroyIgnored', { masks: settings.ignore_masks })}`);
    }

    if (settings.archive) {
        steps.push(`${stepNum++}. ${t('operations.pushStepArchive')}`);
    } else {
        steps.push(`${stepNum++}. ${t('operations.pushStepDeleteSource')}`);
    }

    const names = Array.isArray(name) ? name : [name];
    const isMulti = names.length > 1;

    let msg = isMulti
        ? t('operations.pushConfirmTitleMulti', { count: names.length })
        : t('operations.pushConfirmTitle', { name: names[0] });

    msg += '\n\n';
    msg += t('operations.pushConfirmStepsHeader') + '\n';
    msg += steps.join('\n');

    if (isMulti) {
        const limit = 5;
        const shown = names.slice(0, limit);
        msg += '\n\n' + t('operations.pushConfirmListHeader') + '\n';
        msg += shown.map(item => `- ${item}`).join('\n');
        if (names.length > limit) {
            msg += '\n' + t('operations.pushConfirmListMore', { count: names.length - limit });
        }
    }

    if (!settings.archive) {
        msg += '\n\n' + t('operations.pushWarningNoArchive');
    }

    return msg;
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

    // A catalog changed by UPDATE comes back as it is now, not as it was
    // pushed: say so explicitly, in a confirmation of its own.
    const updateIds = operation.update_operation_ids || [];
    const confirmed = updateIds.length > 0
        ? await confirmDialog('pull.confirmAfterUpdate', t('operations.pullAfterUpdate', {
            id: operation.id,
            path: operation.original_path,
            updates: updateIds.map(id => '#' + id).join(', ')
        }))
        : await confirmDialog('pull.confirm', t('operations.pullOperation', {
            id: operation.id,
            path: operation.original_path
        }));

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
    const hasDirectorySelection =
        selectedFiles.length > 0 &&
        selectedFiles.every(file => file.is_directory);
    updatePushButtonState(hasDirectorySelection);

    // Update Pull button
    const selectedOperationId = getSelectedOperationId();
    updatePullButtonState(!!selectedOperationId);

    // Update button: a completed PUSH/UPDATE selected in the operation queue.
    // This layout has a single file pane plus the queue, so the catalog to
    // update is identified by the operation that created it - same entry
    // point as Pull.
    const selectedOperation = selectedOperationId
        ? state.operationQueue.operations.find(op => op.id === selectedOperationId)
        : null;
    updateUpdateButtonState(
        !!selectedOperation &&
        ['PUSH', 'UPDATE'].includes(selectedOperation.type) &&
        selectedOperation.status === 'COMPLETED' &&
        !!selectedOperation.dest_path
    );
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
async function resolveWindowsPath(targetPath) {
    return await apiRequest('/api/path/resolve', {
        method: 'POST',
        body: JSON.stringify({
            windows_path: targetPath,
            worker_id: state.workerId
        })
    });
}

async function handlePrepareAction(targetPaths) {
    const paths = Array.isArray(targetPaths) ? targetPaths : [targetPaths];
    console.log('Deep link: Preparing to select folders from paths:', paths);

    try {
        const resolved = [];
        for (const targetPath of paths) {
            try {
                console.log('Deep link: Calling path resolution API for:', targetPath);
                const pathInfo = await resolveWindowsPath(targetPath);
                console.log('Deep link: Path resolved:', pathInfo);
                resolved.push(pathInfo);
            } catch (error) {
                console.error('Deep link: Path resolution failed:', error);
                showError(t('errors.pathNotAllowed') + ': ' + error.message);
            }
        }

        if (resolved.length === 0) {
            throw new Error(t('errors.noPathsResolved'));
        }

        const parentPath = resolved[0].parent_path;
        const selectable = resolved.filter(info => info.parent_path === parentPath);
        const skipped = resolved.filter(info => info.parent_path !== parentPath);

        if (skipped.length > 0) {
            console.warn('Deep link: Skipping paths with different parent directories');
        }

        if (parentPath !== state.panes.a.currentPath) {
            console.log('Deep link: Navigating to parent directory:', parentPath);
            await loadDirectory('a', parentPath);
        } else {
            console.log('Deep link: Already at parent directory:', parentPath);
        }

        return new Promise((resolve, reject) => {
            setTimeout(() => {
                const fileListBody = document.getElementById('file-list-body-a');
                if (!fileListBody) {
                    console.error('Deep link: File list body not found');
                    showError(t('errors.pathNotAllowed'));
                    reject(new Error('File list body not found'));
                    return;
                }

                clearSelection('a');

                const rows = fileListBody.querySelectorAll('tr');
                const nameSet = new Set(selectable.map(info => info.folder_name));
                let foundCount = 0;
                let firstRow = null;

                for (const row of rows) {
                    const rowName = row.dataset.name || row.querySelector('.file-name')?.textContent?.trim();
                    if (!rowName || !nameSet.has(rowName)) {
                        continue;
                    }

                    const checkbox = row.querySelector('input[type="checkbox"]');
                    if (checkbox) {
                        checkbox.checked = true;
                        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                        if (!firstRow) {
                            firstRow = row;
                        }
                        foundCount++;
                    }
                }

                if (firstRow) {
                    firstRow.scrollIntoView({ behavior: 'smooth', block: 'center' });

                    const originalBg = firstRow.style.backgroundColor;
                    firstRow.style.backgroundColor = 'var(--color-primary-light, #dbeafe)';
                    setTimeout(() => {
                        firstRow.style.backgroundColor = originalBg;
                    }, 2000);
                }

                if (foundCount === 0) {
                    console.warn('Deep link: No matching folders found in directory');
                    showError(t('errors.pathNotAllowed') + ': ' + t('errors.folderNotFound'));
                    reject(new Error(t('errors.folderNotFound')));
                    return;
                }

                console.log(`Deep link: Successfully selected ${foundCount} folder(s)`);
                resolve();
            }, 1000);
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
async function handlePushAction(targetPaths) {
    console.log('Deep link: Auto-triggering push for paths:', targetPaths);

    try {
        // First, select the item (await completion)
        console.log('Deep link: Step 1 - Selecting folder...');
        await handlePrepareAction(targetPaths);

        console.log('Deep link: Step 2 - Folder selected, preparing to trigger push operation...');

        // Wait for selection to register, then trigger push
        await new Promise((resolve) => setTimeout(resolve, 500));

        const selectedFiles = getSelectedFiles('a');
        console.log('Deep link: Selected files:', selectedFiles);

        if (selectedFiles.length > 0 && selectedFiles.every(file => file.is_directory)) {
            console.log('Deep link: Triggering push operation for directories:', selectedFiles.map(f => f.name));
            try {
                await handlePushOperation();
                console.log('Deep link: Push operation triggered successfully');
            } catch (error) {
                console.error('Deep link: Push operation failed:', error);
                showError(t('operations.pushFailed', { error: error.message }));
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
        showError(t('operations.pushFailed', { error: error.message }));
    }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
