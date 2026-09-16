/**
 * Utility Functions
 * Helper functions for common tasks
 */

/**
 * Format file size in human-readable format
 * @param {number} bytes - File size in bytes
 * @returns {string} Formatted size
 */
export function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    if (!bytes) return 'N/A';

    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + units[i];
}

/**
 * Format date in human-readable format
 * @param {string|Date} date - Date to format
 * @returns {string} Formatted date
 */
export function formatDate(date) {
    if (!date) return 'N/A';

    const dateObj = typeof date === 'string' ? new Date(date) : date;

    if (isNaN(dateObj.getTime())) {
        return 'Invalid date';
    }

    const now = new Date();
    const diffMs = now - dateObj;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    // Show relative time for recent dates
    if (diffMins < 1) {
        return 'Just now';
    } else if (diffMins < 60) {
        return `${diffMins} min${diffMins !== 1 ? 's' : ''} ago`;
    } else if (diffHours < 24) {
        return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
    } else if (diffDays < 7) {
        return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
    }

    // Show full date for older dates
    return dateObj.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Format relative date (e.g., "2 minutes ago")
 * @param {string|Date} date - Date to format
 * @returns {string} Relative date string
 */
export function formatRelativeDate(date) {
    return formatDate(date);
}

/**
 * Debounce function execution
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function execution
 * @param {Function} func - Function to throttle
 * @param {number} limit - Time limit in milliseconds
 * @returns {Function} Throttled function
 */
export function throttle(func, limit) {
    let inThrottle;
    return function executedFunction(...args) {
        if (!inThrottle) {
            func(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Get file extension from filename
 * @param {string} filename - Filename
 * @returns {string} File extension
 */
export function getFileExtension(filename) {
    if (!filename) return '';
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

/**
 * Get filename without extension
 * @param {string} filename - Filename
 * @returns {string} Filename without extension
 */
export function getBaseName(filename) {
    if (!filename) return '';
    const parts = filename.split('.');
    if (parts.length > 1) {
        parts.pop();
    }
    return parts.join('.');
}

/**
 * Extract directory path from full path
 * @param {string} path - Full path
 * @returns {string} Directory path
 */
export function getDirectoryPath(path) {
    if (!path) return '';
    const parts = path.split('/');
    parts.pop();
    return parts.join('/') || '/';
}

/**
 * Extract filename from full path
 * @param {string} path - Full path
 * @returns {string} Filename
 */
export function getFileName(path) {
    if (!path) return '';
    const parts = path.split('/');
    return parts[parts.length - 1];
}

/**
 * Join path components
 * @param {...string} parts - Path parts
 * @returns {string} Joined path
 */
export function joinPath(...parts) {
    if (parts.length === 0) return 'A:';

    // Extract prefix from first part if present
    const firstPart = parts[0] || '';
    let prefix = 'A:';
    let pathParts = parts;

    if (/^[ABC]:/i.test(firstPart)) {
        prefix = firstPart.substring(0, 2).toUpperCase();
        pathParts = [firstPart.substring(2), ...parts.slice(1)];
    }

    const joined = pathParts
        .filter(part => part)
        .join('/')
        .replace(/\\/g, '/')
        .replace(/\/+/g, '/')
        .replace(/\/$/, '');

    return prefix + (joined ? '/' + joined.replace(/^\//, '') : '');
}

/**
 * Normalize path (remove redundant separators, etc.)
 * @param {string} path - Path to normalize
 * @returns {string} Normalized path
 */
export function normalizePath(path) {
    if (!path) return 'A:';

    // If path is just a prefix (A:, B:, C:), return as is
    if (/^[ABC]:$/i.test(path)) {
        return path.toUpperCase();
    }

    // Ensure path has a prefix
    if (!/^[ABC]:/i.test(path)) {
        // If it starts with /, prepend A:
        if (path.startsWith('/')) {
            path = 'A:' + path;
        } else {
            path = 'A:/' + path;
        }
    }

    // Normalize the path part after the prefix
    const prefix = path.substring(0, 2).toUpperCase();
    const pathPart = path.substring(2);

    // Replace backslashes with forward slashes and remove redundant separators
    const normalizedPath = pathPart.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '');

    return prefix + normalizedPath;
}

/**
 * Show the shared #modal dialog.
 *
 * @param {Object} options
 * @param {string} options.title - Dialog title
 * @param {string} options.message - Plain text; newlines are kept
 * @param {string} [options.confirmLabel] - Replaces the confirm button text
 * @param {boolean} [options.hideCancel] - Single-button (informational) dialog
 * @param {boolean} [options.dontAskAgain] - Show the "Don't ask again" checkbox
 * @param {string|null} [options.input] - Initial value; shows a text input
 * @returns {Promise<{confirmed: boolean, value: string|null, dontAskAgain: boolean}>}
 */
export function showDialog({ title, message, confirmLabel, hideCancel = false, dontAskAgain = false, input = null }) {
    return new Promise((resolve) => {
        const modal = document.getElementById('modal');
        const modalTitle = document.getElementById('modal-title');
        const modalMessage = document.getElementById('modal-message');
        const modalInputContainer = document.getElementById('modal-input-container');
        const modalInput = document.getElementById('modal-input');
        const modalConfirm = document.getElementById('modal-confirm');
        const modalCancel = document.getElementById('modal-cancel');
        const modalClose = document.getElementById('modal-close');
        // Only present on pages that use suppressible dialogs
        const dontAsk = document.getElementById('modal-dont-ask');
        const dontAskCheckbox = document.getElementById('modal-dont-ask-checkbox');

        const originalConfirmLabel = modalConfirm.textContent;
        const showInput = input !== null;

        modalTitle.textContent = title;
        // textContent keeps this XSS-safe for user-supplied catalog and file
        // names; pre-line makes embedded newlines render as line breaks.
        modalMessage.style.whiteSpace = 'pre-line';
        modalMessage.textContent = message;
        if (confirmLabel) modalConfirm.textContent = confirmLabel;
        modalCancel.hidden = hideCancel;

        if (dontAsk) {
            dontAsk.classList.toggle('hidden', !dontAskAgain);
            dontAskCheckbox.checked = false;
        }

        if (showInput) {
            modalInputContainer.classList.remove('hidden');
            modalInput.value = input;
        } else {
            modalInputContainer.classList.add('hidden');
        }

        modal.classList.remove('hidden');
        (showInput ? modalInput : modalConfirm).focus();

        const finish = (confirmed) => {
            modal.classList.add('hidden');
            modalConfirm.textContent = originalConfirmLabel;
            modalCancel.hidden = false;
            modalConfirm.removeEventListener('click', handleConfirm);
            modalCancel.removeEventListener('click', handleCancel);
            modalClose.removeEventListener('click', handleCancel);
            modalInput.removeEventListener('keypress', handleKey);
            resolve({
                confirmed,
                value: showInput && confirmed ? modalInput.value : null,
                dontAskAgain: Boolean(dontAskAgain && dontAskCheckbox && dontAskCheckbox.checked)
            });
        };
        const handleConfirm = () => finish(true);
        const handleCancel = () => finish(false);
        const handleKey = (e) => {
            if (e.key === 'Enter') finish(true);
        };

        modalConfirm.addEventListener('click', handleConfirm);
        modalCancel.addEventListener('click', handleCancel);
        modalClose.addEventListener('click', handleCancel);
        if (showInput) modalInput.addEventListener('keypress', handleKey);
    });
}

/**
 * Show modal dialog
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @param {boolean} showInput - Show input field
 * @param {string} inputValue - Initial input value
 * @returns {Promise<string|boolean>} Input value or true/false
 */
export async function showModal(title, message, showInput = false, inputValue = '') {
    const result = await showDialog({ title, message, input: showInput ? inputValue : null });
    if (showInput) {
        return result.confirmed ? result.value : false;
    }
    return result.confirmed;
}

/**
 * Hide modal
 */
export function hideModal() {
    const modal = document.getElementById('modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * Show confirmation dialog
 * @param {string} message - Confirmation message
 * @param {string} title - Dialog title
 * @returns {Promise<boolean>}
 */
export function showConfirm(message, title = 'Confirm Action') {
    return showModal(title, message, false);
}

/**
 * Show prompt dialog
 * @param {string} message - Prompt message
 * @param {string} defaultValue - Default input value
 * @param {string} title - Dialog title
 * @returns {Promise<string|boolean>}
 */
export function showPrompt(message, defaultValue = '', title = 'Input Required') {
    return showModal(title, message, true, defaultValue);
}

/**
 * Show toast notification
 * @param {string} message - Notification message
 * @param {string} type - Notification type (success, error, info, warning)
 * @param {number} duration - Duration in milliseconds
 */
export function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        background-color: ${type === 'success' ? '#16a34a' : type === 'error' ? '#dc2626' : type === 'warning' ? '#f59e0b' : '#0891b2'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, duration);
}

/**
 * Show notification (alias for showToast for backward compatibility)
 * @param {string} message - Notification message
 * @param {string} type - Notification type (success, error, info, warning)
 * @param {number} duration - Duration in milliseconds
 */
export function showNotification(message, type = 'info', duration = 3000) {
    return showToast(message, type, duration);
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @returns {Promise<boolean>}
 */
export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (error) {
        console.error('Failed to copy to clipboard:', error);
        return false;
    }
}

/**
 * Download text as file
 * @param {string} content - File content
 * @param {string} filename - Filename
 * @param {string} mimeType - MIME type
 */
export function downloadFile(content, filename, mimeType = 'text/plain') {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Parse query string
 * @param {string} queryString - Query string
 * @returns {Object} Parsed parameters
 */
export function parseQueryString(queryString) {
    const params = {};
    const query = queryString.startsWith('?') ? queryString.slice(1) : queryString;

    query.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key) {
            params[decodeURIComponent(key)] = value ? decodeURIComponent(value) : '';
        }
    });

    return params;
}

/**
 * Build query string from object
 * @param {Object} params - Parameters object
 * @returns {string} Query string
 */
export function buildQueryString(params) {
    return Object.keys(params)
        .filter(key => params[key] !== null && params[key] !== undefined)
        .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
        .join('&');
}

/**
 * Check if string is valid path
 * @param {string} path - Path to validate
 * @returns {boolean}
 */
export function isValidPath(path) {
    if (!path || typeof path !== 'string') return false;
    // Basic validation - starts with / and doesn't contain invalid characters
    return /^\/[^<>:"|?*]*$/.test(path);
}

/**
 * Sort array of objects by property
 * @param {Array} array - Array to sort
 * @param {string} property - Property to sort by
 * @param {boolean} ascending - Sort direction
 * @returns {Array} Sorted array
 */
export function sortBy(array, property, ascending = true) {
    return [...array].sort((a, b) => {
        const aVal = a[property];
        const bVal = b[property];

        if (aVal < bVal) return ascending ? -1 : 1;
        if (aVal > bVal) return ascending ? 1 : -1;
        return 0;
    });
}

/**
 * Generate unique ID
 * @returns {string} Unique ID
 */
export function generateId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Sleep for specified duration
 * @param {number} ms - Duration in milliseconds
 * @returns {Promise<void>}
 */
export function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry function with exponential backoff
 * @param {Function} fn - Function to retry
 * @param {number} maxRetries - Maximum number of retries
 * @param {number} delay - Initial delay in milliseconds
 * @returns {Promise<any>}
 */
export async function retry(fn, maxRetries = 3, delay = 1000) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            return await fn();
        } catch (error) {
            if (i === maxRetries - 1) {
                throw error;
            }
            await sleep(delay * Math.pow(2, i));
        }
    }
}

/**
 * Check if object is empty
 * @param {Object} obj - Object to check
 * @returns {boolean}
 */
export function isEmpty(obj) {
    return Object.keys(obj).length === 0;
}

/**
 * Deep clone object
 * @param {any} obj - Object to clone
 * @returns {any} Cloned object
 */
export function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}
