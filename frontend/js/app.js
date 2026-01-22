/**
 * Main Application Controller
 * Initializes and manages the file explorer application
 */

import { checkAuth, logout, getCurrentUser, isAdmin, setupAutoRefresh } from './auth.js';
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
    startPolling
} from './api.js';
import {
    renderFileList,
    showLoading,
    hideLoading,
    getSelectedFiles,
    clearSelection,
    navigateToDirectory,
    updateOperationStatus,
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
    setCurrentPath
} from './ui.js';
import { normalizePath, joinPath, debounce } from './utils.js';

// Application state
const state = {
    panes: {
        a: {
            currentPath: '/',
            files: [],
            offset: 0,
            isSearching: false
        },
        b: {
            currentPath: '/',
            files: [],
            offset: 0,
            isSearching: false
        }
    },
    operations: new Map(),
    refreshInterval: null
};

/**
 * Initialize application
 */
async function init() {
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

    // Setup auto token refresh
    setupAutoRefresh();

    // Setup event listeners
    setupEventListeners();

    // Initialize both panes
    await loadDirectory('a', '/');
    await loadDirectory('b', '/');

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

    console.log('Application initialized');
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Logout button
    document.getElementById('logout-btn').addEventListener('click', () => {
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

    // Setup pane controls
    setupPaneControls('a');
    setupPaneControls('b');

    // Setup operation buttons
    setupOperationButtons();

    // Setup select all checkboxes
    setupSelectAll('a');
    setupSelectAll('b');

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
    // Path go button
    document.getElementById(`path-go-${paneId}`).addEventListener('click', async () => {
        const path = document.getElementById(`path-input-${paneId}`).value;
        await loadDirectory(paneId, path);
    });

    // Path input enter key
    document.getElementById(`path-input-${paneId}`).addEventListener('keypress', async (e) => {
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
    document.getElementById(`search-btn-${paneId}`).addEventListener('click', async () => {
        await handleSearch(paneId);
    });

    // Search input enter key
    document.getElementById(`search-${paneId}`).addEventListener('keypress', async (e) => {
        if (e.key === 'Enter') {
            await handleSearch(paneId);
        }
    });

    // Search input with debounce
    const searchInput = document.getElementById(`search-${paneId}`);
    searchInput.addEventListener('input', debounce(async () => {
        if (searchInput.value) {
            await handleSearch(paneId);
        } else {
            await refreshPane(paneId);
        }
    }, 500));

    // Load more button
    document.getElementById(`load-more-${paneId}`).addEventListener('click', async () => {
        await loadMoreFiles(paneId);
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
 * Load directory contents
 * @param {string} paneId - Pane ID
 * @param {string} path - Directory path
 */
async function loadDirectory(paneId, path) {
    const normalizedPath = normalizePath(path);

    showLoading(paneId);
    state.panes[paneId].isSearching = false;
    state.panes[paneId].offset = 0;

    try {
        const files = await listFiles(normalizedPath, 0, 50);

        state.panes[paneId].currentPath = normalizedPath;
        state.panes[paneId].files = files;
        state.panes[paneId].offset = files.length;

        setCurrentPath(paneId, normalizedPath);
        renderFileList(paneId, files, false);

    } catch (error) {
        console.error(`Error loading directory for pane ${paneId}:`, error);
        showError(`Failed to load directory: ${error.message}`);
        hideLoading(paneId);
    }
}

/**
 * Refresh pane contents
 * @param {string} paneId - Pane ID
 */
async function refreshPane(paneId) {
    const currentPath = state.panes[paneId].currentPath;
    await loadDirectory(paneId, currentPath);
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

    } catch (error) {
        console.error(`Error loading more files for pane ${paneId}:`, error);
        showError(`Failed to load more files: ${error.message}`);
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
    const pattern = searchInput.value.trim();

    if (!pattern) {
        await refreshPane(paneId);
        return;
    }

    const currentPath = state.panes[paneId].currentPath;

    showLoading(paneId);
    state.panes[paneId].isSearching = true;

    try {
        const files = await searchFiles(currentPath, pattern);

        state.panes[paneId].files = files;
        renderFileList(paneId, files, false);

    } catch (error) {
        console.error(`Error searching files in pane ${paneId}:`, error);
        showError(`Search failed: ${error.message}`);
    } finally {
        hideLoading(paneId);
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
    console.log('WebSocket event:', data);

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
 * Check if WebSocket is connected
 * @returns {boolean}
 */
function isWebSocketConnected() {
    // Import from api.js if needed, or implement check here
    return false; // Placeholder
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
        document.getElementById('ui-theme').value = preferences.ui_theme || 'light';
        document.getElementById('pane-layout').value = preferences.pane_layout || 'horizontal';
        document.getElementById('show-hidden-files').checked = preferences.show_hidden_files || false;
        document.getElementById('default-sort-by').value = preferences.default_sort_by || 'name';
        document.getElementById('default-sort-order').value = preferences.default_sort_order || 'asc';
        document.getElementById('items-per-page').value = preferences.items_per_page || 100;
        document.getElementById('remember-last-paths').checked = preferences.remember_last_paths !== false;

        // Show modal
        settingsModal.classList.remove('hidden');

        // Save button handler
        const saveHandler = async () => {
            try {
                const updatedPreferences = {
                    ui_theme: document.getElementById('ui-theme').value,
                    pane_layout: document.getElementById('pane-layout').value,
                    show_hidden_files: document.getElementById('show-hidden-files').checked,
                    default_sort_by: document.getElementById('default-sort-by').value,
                    default_sort_order: document.getElementById('default-sort-order').value,
                    items_per_page: parseInt(document.getElementById('items-per-page').value),
                    remember_last_paths: document.getElementById('remember-last-paths').checked
                };

                await updatePreferences(updatedPreferences);
                showSuccess('Settings saved successfully');
                closeSettingsModal();

                // Apply theme immediately if changed
                if (updatedPreferences.ui_theme !== preferences.ui_theme) {
                    document.body.setAttribute('data-theme', updatedPreferences.ui_theme);
                }
            } catch (error) {
                showError('Failed to save settings: ' + error.message);
            }
        };

        // Reset button handler
        const resetHandler = async () => {
            if (confirm('Reset all settings to defaults?')) {
                try {
                    const defaultPrefs = await resetPreferences();
                    showSuccess('Settings reset to defaults');

                    // Re-populate form with defaults
                    document.getElementById('ui-theme').value = defaultPrefs.ui_theme;
                    document.getElementById('pane-layout').value = defaultPrefs.pane_layout;
                    document.getElementById('show-hidden-files').checked = defaultPrefs.show_hidden_files;
                    document.getElementById('default-sort-by').value = defaultPrefs.default_sort_by;
                    document.getElementById('default-sort-order').value = defaultPrefs.default_sort_order;
                    document.getElementById('items-per-page').value = defaultPrefs.items_per_page;
                    document.getElementById('remember-last-paths').checked = defaultPrefs.remember_last_paths;

                    // Apply theme
                    document.body.setAttribute('data-theme', defaultPrefs.ui_theme);
                } catch (error) {
                    showError('Failed to reset settings: ' + error.message);
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
        showError('Failed to load settings: ' + error.message);
        console.error('Settings error:', error);
    }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
