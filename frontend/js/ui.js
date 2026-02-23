/**
 * UI Module
 * Handles DOM updates and UI interactions
 */

import { formatFileSize, formatDate, escapeHtml, showConfirm, showPrompt, showToast } from './utils.js';

/**
 * Render file list in pane
 * @param {string} paneId - Pane ID ('a' or 'b')
 * @param {Array} files - Array of file objects
 * @param {boolean} append - Append to existing list
 */
export function renderFileList(paneId, files, append = false) {
    const tbody = document.getElementById(`file-list-body-${paneId}`);
    const noFiles = document.getElementById(`no-files-${paneId}`);
    const loading = document.getElementById(`loading-${paneId}`);

    // Hide loading indicator
    loading.classList.add('hidden');

    // Save selected path before clearing to restore selection after refresh (single selection)
    let selectedPath = null;
    if (!append) {
        const selectedRadio = document.querySelector(`#file-list-body-${paneId} .file-radio:checked`);
        if (selectedRadio && selectedRadio.dataset.path) {
            selectedPath = selectedRadio.dataset.path;
        }
        tbody.innerHTML = '';
    }

    // Ensure files is an array
    if (!Array.isArray(files)) {
        files = [];
    }

    if (files.length === 0 && !append) {
        noFiles.classList.remove('hidden');
        return;
    }

    noFiles.classList.add('hidden');

    files.forEach(file => {
        const row = createFileRow(file, paneId);
        tbody.appendChild(row);
    });

    // Restore selection after rendering (single selection)
    if (selectedPath) {
        // Find radio by iterating (more robust than CSS selector with special chars in path)
        const radios = tbody.querySelectorAll('.file-radio');
        for (const radio of radios) {
            if (radio.dataset.path === selectedPath) {
                radio.checked = true;
                const row = radio.closest('tr');
                if (row) {
                    row.classList.add('selected');
                }
                // Dispatch change event to update button states
                radio.dispatchEvent(new Event('change', { bubbles: true }));
                break;
            }
        }
    }

    // Update load more button visibility
    const loadMoreBtn = document.getElementById(`load-more-${paneId}`);
    if (files.length >= 50) {
        loadMoreBtn.classList.remove('hidden');
    } else if (!append) {
        loadMoreBtn.classList.add('hidden');
    }
}

/**
 * Create file row element
 * @param {Object} file - File object
 * @param {string} paneId - Pane ID
 * @returns {HTMLElement} Table row element
 */
function createFileRow(file, paneId) {
    const row = document.createElement('tr');
    row.dataset.path = file.path;
    row.dataset.isDirectory = file.is_directory;
    row.dataset.isParentDir = file.is_parent_dir || false;
    row.dataset.sizeBytes = file.size_bytes || 0;
    row.dataset.modified = file.modified_at || '';
    row.dataset.name = file.name || '';

    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = `file-select-${paneId}`; // All radios in same pane share name
    radio.className = 'file-radio';
    radio.dataset.path = file.path;
    radio.dataset.isDirectory = file.is_directory;

    // Disable radio for parent directory (..)
    if (file.is_parent_dir) {
        radio.disabled = true;
        radio.style.visibility = 'hidden';
    }

    const radioCell = document.createElement('td');
    radioCell.appendChild(radio);

    const nameCell = document.createElement('td');
    const icon = document.createElement('span');
    icon.className = `file-icon ${file.is_directory ? 'folder' : 'file'}`;

    const nameSpan = document.createElement('span');
    nameSpan.className = `file-name ${file.is_directory ? 'folder' : ''}`;
    nameSpan.textContent = file.name;

    nameCell.appendChild(icon);
    nameCell.appendChild(nameSpan);

    const sizeCell = document.createElement('td');
    // Show human-readable size for files, '-' for directories
    if (file.is_directory || file.is_parent_dir) {
        sizeCell.textContent = '-';
    } else {
        sizeCell.textContent = formatFileSize(file.size_bytes || file.size || 0);
    }

    const modifiedCell = document.createElement('td');
    modifiedCell.textContent = file.modified_at ? formatDate(file.modified_at) : '-';

    row.appendChild(radioCell);
    row.appendChild(nameCell);
    row.appendChild(sizeCell);
    row.appendChild(modifiedCell);

    // Make directories clickable (single click on name cell to navigate)
    if (file.is_directory) {
        row.style.cursor = 'pointer';
        nameCell.style.cursor = 'pointer';

        // Single click on name cell to navigate
        nameCell.addEventListener('click', (e) => {
            // Don't navigate if clicking radio
            if (e.target.type !== 'radio') {
                navigateToDirectory(paneId, file.path);
            }
        });
    }

    // Add context menu handler
    row.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY, file, paneId);
    });

    // Add row selection (only for non-directory rows or when not clicking on name)
    row.addEventListener('click', (e) => {
        // Don't toggle radio if:
        // 1. Already clicking radio
        // 2. Clicking on name cell of a directory (navigation)
        // 3. Row is parent directory
        if (file.is_parent_dir) {
            return;
        }

        if (e.target.type !== 'radio' && !e.target.closest('td:nth-child(2)')) {
            // Clear all other selections first
            document.querySelectorAll(`#file-list-body-${paneId} tr`).forEach(r => {
                r.classList.remove('selected');
            });

            radio.checked = true;
            radio.dispatchEvent(new Event('change', { bubbles: true }));
            row.classList.add('selected');
        }
    });

    // Also handle radio change events
    radio.addEventListener('change', () => {
        // Clear all other row selections
        document.querySelectorAll(`#file-list-body-${paneId} tr`).forEach(r => {
            r.classList.remove('selected');
        });
        if (radio.checked) {
            row.classList.add('selected');
        }
    });

    return row;
}

/**
 * Navigate to directory
 * @param {string} paneId - Pane ID
 * @param {string} path - Directory path
 */
export function navigateToDirectory(paneId, path) {
    const pathInput = document.getElementById(`path-input-${paneId}`);
    pathInput.value = path;

    // Trigger path change event
    const event = new CustomEvent('pathchange', { detail: { paneId, path } });
    document.dispatchEvent(event);
}

/**
 * Show loading indicator
 * @param {string} paneId - Pane ID
 */
export function showLoading(paneId) {
    const loading = document.getElementById(`loading-${paneId}`);
    const noFiles = document.getElementById(`no-files-${paneId}`);

    loading.classList.remove('hidden');
    noFiles.classList.add('hidden');
}

/**
 * Hide loading indicator
 * @param {string} paneId - Pane ID
 */
export function hideLoading(paneId) {
    const loading = document.getElementById(`loading-${paneId}`);
    loading.classList.add('hidden');
}

/**
 * Get selected file in pane (single selection with radio button)
 * @param {string} paneId - Pane ID
 * @returns {Array<Object>} Array with single selected file object, or empty array
 */
export function getSelectedFiles(paneId) {
    const selectedRadio = document.querySelector(`#file-list-body-${paneId} .file-radio:checked`);
    if (!selectedRadio) {
        return [];
    }

    const row = selectedRadio.closest('tr');
    return [{
        path: selectedRadio.dataset.path,
        name: row.dataset.name,
        is_directory: row.dataset.isDirectory === 'true',
        size_bytes: parseInt(row.dataset.sizeBytes) || 0
    }];
}

/**
 * Clear selection in pane
 * @param {string} paneId - Pane ID
 */
export function clearSelection(paneId) {
    const radios = document.querySelectorAll(`#file-list-body-${paneId} .file-radio`);
    radios.forEach(r => {
        r.checked = false;
        r.closest('tr').classList.remove('selected');
    });
}

/**
 * Show context menu
 * @param {number} x - X position
 * @param {number} y - Y position
 * @param {Object} file - File object
 * @param {string} paneId - Pane ID
 */
function showContextMenu(x, y, file, paneId) {
    const contextMenu = document.getElementById('context-menu');

    // Position menu
    contextMenu.style.left = `${x}px`;
    contextMenu.style.top = `${y}px`;
    contextMenu.classList.remove('hidden');

    // Remove existing event listeners
    const newMenu = contextMenu.cloneNode(true);
    contextMenu.parentNode.replaceChild(newMenu, contextMenu);

    // Add event listeners
    const menuItems = newMenu.querySelectorAll('li[data-action]');
    menuItems.forEach(item => {
        item.addEventListener('click', () => {
            handleContextMenuAction(item.dataset.action, file, paneId);
            hideContextMenu();
        });
    });

    // Hide menu on outside click
    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
    }, 0);
}

/**
 * Hide context menu
 */
function hideContextMenu() {
    const contextMenu = document.getElementById('context-menu');
    contextMenu.classList.add('hidden');
}

/**
 * Handle context menu action
 * @param {string} action - Action name
 * @param {Object} file - File object
 * @param {string} paneId - Pane ID
 */
function handleContextMenuAction(action, file, paneId) {
    const event = new CustomEvent('contextmenuaction', {
        detail: { action, file, paneId }
    });
    document.dispatchEvent(event);
}

/**
 * Update operation status display
 * @param {string} message - Status message
 * @param {string} type - Message type (success, error, info)
 */
export function updateOperationStatus(message, type = 'info') {
    const statusMessage = document.getElementById('status-message');
    if (statusMessage) {
        statusMessage.textContent = message;
        statusMessage.className = `status-message status-${type}`;
    }
}

/**
 * Clear operation status
 */
export function clearOperationStatus() {
    const statusMessage = document.getElementById('status-message');
    if (statusMessage) {
        statusMessage.textContent = '';
        statusMessage.className = 'status-message';
    }
}

/**
 * Update progress bar
 * @param {number} percent - Progress percentage (0-100)
 */
export function updateProgress(percent) {
    const progressContainer = document.getElementById('progress-container');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    progressContainer.classList.remove('hidden');
    progressFill.style.width = `${percent}%`;
    progressText.textContent = `${Math.round(percent)}%`;
}

/**
 * Hide progress bar
 */
export function hideProgress() {
    const progressContainer = document.getElementById('progress-container');
    progressContainer.classList.add('hidden');
}

/**
 * Add operation to queue display
 * @param {Object} operation - Operation object
 */
export function addOperationToQueue(operation) {
    const queueList = document.getElementById('queue-list');
    const emptyMessage = queueList.querySelector('.queue-empty');

    if (emptyMessage) {
        emptyMessage.remove();
    }

    const queueItem = createQueueItem(operation);
    queueList.appendChild(queueItem);
}

/**
 * Update operation in queue
 * @param {Object} operation - Updated operation object
 */
export function updateOperationInQueue(operation) {
    const queueItem = document.querySelector(`[data-operation-id="${operation.operation_id}"]`);
    if (queueItem) {
        const newItem = createQueueItem(operation);
        queueItem.replaceWith(newItem);
    }
}

/**
 * Remove operation from queue
 * @param {string} operationId - Operation ID
 */
export function removeOperationFromQueue(operationId) {
    const queueItem = document.querySelector(`[data-operation-id="${operationId}"]`);
    if (queueItem) {
        queueItem.remove();
    }

    // Show empty message if no operations
    const queueList = document.getElementById('queue-list');
    if (queueList.children.length === 0) {
        const emptyMessage = document.createElement('p');
        emptyMessage.className = 'queue-empty';
        emptyMessage.textContent = 'No operations in queue';
        queueList.appendChild(emptyMessage);
    }
}

/**
 * Create queue item element
 * @param {Object} operation - Operation object
 * @returns {HTMLElement} Queue item element
 */
function createQueueItem(operation) {
    const item = document.createElement('div');
    item.className = 'queue-item';
    item.dataset.operationId = operation.operation_id;

    const info = document.createElement('div');
    info.className = 'queue-item-info';

    const title = document.createElement('div');
    title.className = 'queue-item-title';
    title.textContent = `${operation.operation_type}: ${operation.source_count || 0} file(s)`;

    const details = document.createElement('div');
    details.className = 'queue-item-details';
    details.textContent = `Status: ${operation.status}`;

    info.appendChild(title);
    info.appendChild(details);

    const status = document.createElement('div');
    status.className = 'queue-item-status';

    const statusBadge = document.createElement('span');
    statusBadge.className = `status-badge status-${operation.status}`;
    statusBadge.textContent = operation.status;

    status.appendChild(statusBadge);

    if (operation.status === 'in_progress') {
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-sm btn-danger';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            const event = new CustomEvent('canceloperation', {
                detail: { operationId: operation.operation_id }
            });
            document.dispatchEvent(event);
        });
        status.appendChild(cancelBtn);
    }

    item.appendChild(info);
    item.appendChild(status);

    return item;
}

/**
 * Setup select all checkbox - REMOVED for single selection with radio buttons
 * This function is kept for backward compatibility but does nothing
 * @param {string} paneId - Pane ID
 */
export function setupSelectAll(paneId) {
    // No-op: Radio buttons don't support select-all
    // Kept for backward compatibility
}

/**
 * Show error message
 * @param {string} message - Error message
 */
export function showError(message) {
    showToast(message, 'error', 5000);
    updateOperationStatus(message, 'error');
}

/**
 * Show success message
 * @param {string} message - Success message
 */
export function showSuccess(message) {
    showToast(message, 'success', 3000);
    updateOperationStatus(message, 'success');
}

/**
 * Show info message
 * @param {string} message - Info message
 */
export function showInfo(message) {
    showToast(message, 'info', 3000);
    updateOperationStatus(message, 'info');
}

/**
 * Confirm action with user
 * @param {string} message - Confirmation message
 * @returns {Promise<boolean>}
 */
export async function confirmAction(message) {
    return await showConfirm(message);
}

/**
 * Prompt user for input
 * @param {string} message - Prompt message
 * @param {string} defaultValue - Default value
 * @returns {Promise<string|boolean>}
 */
export async function promptUser(message, defaultValue = '') {
    return await showPrompt(message, defaultValue);
}

/**
 * Disable operation buttons
 */
export function disableOperationButtons() {
    const buttons = document.querySelectorAll('.operations-buttons .btn');
    buttons.forEach(btn => btn.disabled = true);
}

/**
 * Enable operation buttons
 */
export function enableOperationButtons() {
    const buttons = document.querySelectorAll('.operations-buttons .btn');
    buttons.forEach(btn => btn.disabled = false);
}

/**
 * Get current path from pane
 * @param {string} paneId - Pane ID
 * @returns {string} Current path
 */
export function getCurrentPath(paneId) {
    const pathInput = document.getElementById(`path-input-${paneId}`);
    const defaultPath = paneId === 'a' ? 'A:' : 'B:';
    return pathInput.value || defaultPath;
}

/**
 * Set current path in pane
 * @param {string} paneId - Pane ID
 * @param {string} path - Path to set
 */
export function setCurrentPath(paneId, path) {
    const pathInput = document.getElementById(`path-input-${paneId}`);
    pathInput.value = path;
}

/* ==========================================
   VF REDESIGN - Operation Queue Table Rendering
   ========================================== */

/**
 * Render operation history in queue table (VF REDESIGN)
 */
export function renderOperationQueue(operations, append = false) {
    const tbody = document.getElementById('queue-table-body');
    const loadingIndicator = document.getElementById('loading-queue');
    const noOperationsMsg = document.getElementById('no-operations');

    if (!tbody) return;

    if (loadingIndicator) {
        loadingIndicator.classList.add('hidden');
    }

    // Save currently selected operation ID before clearing
    let selectedOperationId = null;
    if (!append) {
        selectedOperationId = getSelectedOperationId();
        tbody.innerHTML = '';
    }

    // Ensure operations is an array
    if (!Array.isArray(operations)) {
        operations = [];
    }

    if (operations.length === 0 && !append) {
        if (noOperationsMsg) {
            noOperationsMsg.classList.remove('hidden');
        }
        return;
    }

    if (noOperationsMsg) {
        noOperationsMsg.classList.add('hidden');
    }

    operations.forEach(operation => {
        const row = createOperationTableRow(operation);
        tbody.appendChild(row);
    });

    // Restore previously selected operation if it still exists
    if (selectedOperationId) {
        const checkbox = tbody.querySelector(`input[type="radio"][value="${selectedOperationId}"]`);
        if (checkbox && !checkbox.disabled) {
            checkbox.checked = true;
            const row = checkbox.closest('tr');
            if (row) {
                row.classList.add('selected');
            }
        }
    }
}

function createOperationTableRow(operation) {
    const row = document.createElement('tr');
    row.dataset.operationId = operation.id;
    row.dataset.operationType = operation.type;

    if (operation.selected) {
        row.classList.add('selected');
    }

    const checkboxCell = document.createElement('td');
    checkboxCell.className = 'col-select';
    const checkbox = document.createElement('input');
    checkbox.type = 'radio';
    checkbox.name = 'selected-operation';
    checkbox.value = operation.id;
    checkbox.dataset.operationType = operation.type;

    if (operation.type === 'PUSH' && operation.status === 'COMPLETED' && !operation.has_been_pulled) {
        checkbox.addEventListener('change', (e) => {
            document.querySelectorAll('#queue-table-body tr').forEach(r => {
                r.classList.remove('selected');
            });
            if (e.target.checked) {
                row.classList.add('selected');
            }
        });
    } else {
        checkbox.disabled = true;
        checkbox.style.visibility = 'hidden';
    }

    checkboxCell.appendChild(checkbox);
    row.appendChild(checkboxCell);

    const idCell = document.createElement('td');
    idCell.className = 'col-id';
    idCell.textContent = operation.id;
    row.appendChild(idCell);

    const typeCell = document.createElement('td');
    typeCell.className = 'col-type';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'operation-type ' + operation.type.toLowerCase();
    typeBadge.textContent = operation.type;
    typeCell.appendChild(typeBadge);
    row.appendChild(typeCell);

    const statusCell = document.createElement('td');
    statusCell.className = 'col-status';
    const statusBadge = document.createElement('span');
    statusBadge.className = 'operation-status ' + operation.status.toLowerCase().replace('_', '-');
    statusBadge.textContent = formatStatus(operation.status);
    statusCell.appendChild(statusBadge);
    row.appendChild(statusCell);

    const directoryCell = document.createElement('td');
    directoryCell.className = 'col-directory';
    const fullDirPath = getOperationDirectory(operation);
    const lastSegment = fullDirPath.split(/[\\/]/).filter(Boolean).pop() || fullDirPath;
    directoryCell.textContent = lastSegment;
    directoryCell.title = fullDirPath;
    row.appendChild(directoryCell);

    const userCell = document.createElement('td');
    userCell.className = 'col-user';
    userCell.textContent = operation.user_name || 'Unknown';
    row.appendChild(userCell);

    const timestampCell = document.createElement('td');
    timestampCell.className = 'col-timestamp';
    timestampCell.textContent = formatTimestamp(operation.created_at);
    timestampCell.title = new Date(operation.created_at).toLocaleString();
    row.appendChild(timestampCell);

    return row;
}

function getOperationDirectory(operation) {
    if (operation.type === 'PUSH') {
        return operation.source_path || operation.original_path || 'N/A';
    } else if (operation.type === 'PULL') {
        return operation.dest_path || operation.original_path || 'N/A';
    }
    return operation.source_path || 'N/A';
}

function formatStatus(status) {
    return status.replace('_', ' ').toLowerCase()
        .replace(/\b\w/g, char => char.toUpperCase());
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return diffMins + 'm ago';
    if (diffHours < 24) return diffHours + 'h ago';
    if (diffDays < 7) return diffDays + 'd ago';

    return date.toLocaleDateString();
}

export function updateOperationInQueueTable(operation) {
    const row = document.querySelector('#queue-table-body tr[data-operation-id="' + operation.id + '"]');
    if (row) {
        const newRow = createOperationTableRow(operation);
        row.replaceWith(newRow);
    } else {
        const tbody = document.getElementById('queue-table-body');
        if (tbody) {
            const newRow = createOperationTableRow(operation);
            tbody.insertBefore(newRow, tbody.firstChild);
        }
    }
}

export function getSelectedOperationId() {
    const selectedCheckbox = document.querySelector('#queue-table-body input[type="radio"]:checked');
    return selectedCheckbox ? parseInt(selectedCheckbox.value) : null;
}

export function showQueueLoading() {
    const loadingIndicator = document.getElementById('loading-queue');
    if (loadingIndicator) {
        loadingIndicator.classList.remove('hidden');
    }
}

export function hideQueueLoading() {
    const loadingIndicator = document.getElementById('loading-queue');
    if (loadingIndicator) {
        loadingIndicator.classList.add('hidden');
    }
}

export function filterDirectoriesOnly(files) {
    return files.filter(file => file.is_directory);
}

export function markDirectoryRows(paneId) {
    const tbody = document.getElementById('file-list-body-' + paneId);
    if (!tbody) return;

    const rows = tbody.querySelectorAll('tr');
    rows.forEach(row => {
        const isDirectory = row.dataset.isDirectory === 'true';
        if (isDirectory) {
            row.classList.add('directory');
        } else {
            row.classList.remove('directory');
        }
    });
}

export function updatePushButtonState(hasSelection) {
    const pushBtn = document.getElementById('push-btn');
    if (pushBtn) {
        pushBtn.disabled = !hasSelection;
    }
}

export function updatePullButtonState(hasSelection) {
    const pullBtn = document.getElementById('pull-btn');
    if (pullBtn) {
        pullBtn.disabled = !hasSelection;
    }
}
