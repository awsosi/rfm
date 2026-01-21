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

    if (!append) {
        tbody.innerHTML = '';
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
    row.dataset.isDir = file.is_directory;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'file-checkbox';
    checkbox.dataset.path = file.path;

    const checkboxCell = document.createElement('td');
    checkboxCell.appendChild(checkbox);

    const nameCell = document.createElement('td');
    const icon = document.createElement('span');
    icon.className = `file-icon ${file.is_directory ? 'folder' : 'file'}`;

    const nameSpan = document.createElement('span');
    nameSpan.className = `file-name ${file.is_directory ? 'folder' : ''}`;
    nameSpan.textContent = file.name;

    nameCell.appendChild(icon);
    nameCell.appendChild(nameSpan);

    const sizeCell = document.createElement('td');
    sizeCell.textContent = file.is_directory ? '-' : formatFileSize(file.size);

    const modifiedCell = document.createElement('td');
    modifiedCell.textContent = formatDate(file.modified);

    row.appendChild(checkboxCell);
    row.appendChild(nameCell);
    row.appendChild(sizeCell);
    row.appendChild(modifiedCell);

    // Add click handler for navigation
    if (file.is_directory) {
        row.style.cursor = 'pointer';
        row.addEventListener('dblclick', () => {
            navigateToDirectory(paneId, file.path);
        });
    }

    // Add context menu handler
    row.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY, file, paneId);
    });

    // Add row selection
    row.addEventListener('click', (e) => {
        if (e.target.type !== 'checkbox') {
            checkbox.checked = !checkbox.checked;
            row.classList.toggle('selected', checkbox.checked);
        } else {
            row.classList.toggle('selected', checkbox.checked);
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
 * Get selected files in pane
 * @param {string} paneId - Pane ID
 * @returns {Array<string>} Array of selected file paths
 */
export function getSelectedFiles(paneId) {
    const checkboxes = document.querySelectorAll(`#file-list-body-${paneId} .file-checkbox:checked`);
    return Array.from(checkboxes).map(cb => cb.dataset.path);
}

/**
 * Clear selection in pane
 * @param {string} paneId - Pane ID
 */
export function clearSelection(paneId) {
    const checkboxes = document.querySelectorAll(`#file-list-body-${paneId} .file-checkbox`);
    checkboxes.forEach(cb => {
        cb.checked = false;
        cb.closest('tr').classList.remove('selected');
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
    statusMessage.textContent = message;
    statusMessage.className = `status-message status-${type}`;
}

/**
 * Clear operation status
 */
export function clearOperationStatus() {
    const statusMessage = document.getElementById('status-message');
    statusMessage.textContent = '';
    statusMessage.className = 'status-message';
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
 * Setup select all checkbox
 * @param {string} paneId - Pane ID
 */
export function setupSelectAll(paneId) {
    const selectAll = document.getElementById(`select-all-${paneId}`);
    selectAll.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll(`#file-list-body-${paneId} .file-checkbox`);
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            cb.closest('tr').classList.toggle('selected', e.target.checked);
        });
    });
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
    return pathInput.value || '/';
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
