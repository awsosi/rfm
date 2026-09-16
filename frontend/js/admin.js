/**
 * Admin Panel JavaScript Module
 * Single source of truth for all admin panel functionality.
 */

import { checkAuth, logout, getCurrentUser } from './auth.js';
import {
    getUsers, createUser, updateUser, deleteUser,
    getWorkers, approveWorker, rejectWorker,
    getConfig, updateConfig, getLogs, apiRequest
} from './api.js';
import { showConfirm, formatDate, escapeHtml, showNotification } from './utils.js';
import AdminSystem from './admin-system.js';

// =========================================================================
// State
// =========================================================================

let adminSystem = null;
let statsRefreshInterval = null;
let currentTab = 'users';
let cachedUsers = null;
let workerDataMap = {}; // workerId -> worker object for provision dialog pre-fill

// =========================================================================
// Theme
// =========================================================================

function getSystemTheme() {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

function applyTheme(theme) {
    const effectiveTheme = theme === 'system' ? getSystemTheme() : theme;
    document.body.setAttribute('data-theme', effectiveTheme);
    window._currentThemeSetting = theme;
}

function setupSystemThemeListener() {
    if (window.matchMedia) {
        const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        darkModeQuery.addEventListener('change', (e) => {
            if (window._currentThemeSetting === 'system') {
                document.body.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    }
}

async function loadAndApplyTheme() {
    try {
        const { getPreferences } = await import('./api.js');
        const preferences = await getPreferences();
        applyTheme(preferences.ui_theme || 'system');
    } catch (error) {
        console.error('Failed to load theme preference:', error);
        applyTheme('system');
    }
    setupSystemThemeListener();
}

// =========================================================================
// Initialization
// =========================================================================

/**
 * Initialize the admin panel - called from admin.html
 */
export function initAdminPanel() {
    if (!checkAuth()) {
        window.location.href = 'login.html';
        return;
    }

    const currentUser = getCurrentUser();
    if (!currentUser || currentUser.role?.toUpperCase() !== 'ADMIN') {
        alert('Access denied. Admin role required.');
        window.location.href = 'explorer.html';
        return;
    }

    document.getElementById('user-name').textContent = currentUser.username;

    // Load and apply theme
    loadAndApplyTheme();

    // Initialize AdminSystem for system stats
    const apiClient = {
        get: (endpoint) => apiRequest(endpoint, { method: 'GET' }),
        post: (endpoint, data) => apiRequest(endpoint, { method: 'POST', body: JSON.stringify(data) }),
        put: (endpoint, data) => apiRequest(endpoint, { method: 'PUT', body: JSON.stringify(data) }),
        delete: (endpoint) => apiRequest(endpoint, { method: 'DELETE' })
    };
    adminSystem = new AdminSystem(apiClient);
    window.adminSystem = adminSystem;

    // Expose functions needed by dynamically generated onclick handlers
    window.sendWorkerCmd = sendWorkerCmd;
    window.provisionWorkerDialog = provisionWorkerDialog;

    setupNavigation();
    setupTabSwitching();
    setupUserEvents();
    setupWorkerEvents();
    setupConfigEvents();
    setupLogEvents();
    setupSystemEvents();

    // Navigate based on URL hash (defaults to users tab)
    navigateFromHash();
}

// =========================================================================
// Navigation & Tabs
// =========================================================================

// Maps URL-friendly route names to internal tab data-tab values
const TAB_ROUTES = {
    'users': 'users',
    'workers': 'workers',
    'configuration': 'config',
    'system': 'system',
    'logs': 'logs'
};

// Reverse map: data-tab value -> URL route name
const TAB_ROUTE_NAMES = Object.fromEntries(
    Object.entries(TAB_ROUTES).map(([route, tab]) => [tab, route])
);

// Maps section IDs to their parent tab (data-tab value)
const SECTION_TO_TAB = {
    // Configuration tab sections
    'session-settings': 'config',
    'polkasql-authentication': 'config',
    'rosapi-settings': 'config',
    'pim-settings': 'config',
    'validation-settings': 'config',
    'worker-configuration': 'config',
    'operation-settings': 'config',
    'push-operation-settings': 'config',
    'ui-settings': 'config',
    'security-settings': 'config',
    'maintenance-mode': 'config',
    // Logs tab sections
    'syslog-integration': 'logs',
    'log-retention': 'logs',
    'audit-log-viewer': 'logs'
};

function setupNavigation() {
    document.getElementById('explorer-btn').addEventListener('click', () => {
        window.location.href = 'explorer.html';
    });

    document.getElementById('logout-btn').addEventListener('click', () => {
        logout();
        window.location.href = 'login.html';
    });
}

/**
 * Switch to a tab by its data-tab name, optionally updating the URL hash.
 * @param {string} tabName - Internal tab name (e.g. 'users', 'config')
 * @param {object} options
 * @param {boolean} options.updateHash - Whether to update window.location.hash (default: true)
 * @param {string|null} options.sectionId - Section ID to scroll to after tab loads
 */
function switchToTab(tabName, { updateHash = true, sectionId = null } = {}) {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabButtons.forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (activeBtn) activeBtn.classList.add('active');

    tabPanes.forEach(pane => pane.classList.remove('active'));
    const activePane = document.getElementById(`tab-${tabName}`);
    if (activePane) activePane.classList.add('active');

    // Stop stats auto-refresh when leaving system tab
    if (currentTab === 'system' && tabName !== 'system') {
        stopStatsAutoRefresh();
    }

    currentTab = tabName;

    if (updateHash) {
        const routeName = TAB_ROUTE_NAMES[tabName] || tabName;
        const newHash = sectionId ? `#${routeName}/${sectionId}` : `#${routeName}`;
        // Use replaceState to avoid polluting browser history on every tab switch
        history.replaceState(null, '', newHash);
    }

    loadTabData(tabName).then(() => {
        if (sectionId) {
            scrollToSection(sectionId);
        }
    });
}

/**
 * Scroll to a section element by ID with a brief highlight effect.
 */
function scrollToSection(sectionId) {
    const el = document.getElementById(sectionId);
    if (!el) return;

    el.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Brief highlight to draw attention
    el.classList.add('section-highlight');
    setTimeout(() => el.classList.remove('section-highlight'), 2000);
}

/**
 * Parse the current URL hash and navigate to the appropriate tab/section.
 * Supported formats:
 *   #users, #workers, #configuration, #system, #logs
 *   #configuration/operation-settings  (tab + section)
 *   #logs/audit-log-viewer             (tab + section)
 *   #operation-settings                (section only - auto-resolves tab)
 */
function navigateFromHash() {
    const hash = window.location.hash.replace(/^#/, '');
    if (!hash) {
        switchToTab('users', { updateHash: true });
        return;
    }

    const parts = hash.split('/');
    const first = parts[0];
    const second = parts[1] || null;

    // Case 1: First part is a known tab route
    if (TAB_ROUTES[first] !== undefined) {
        const tabName = TAB_ROUTES[first];
        switchToTab(tabName, { updateHash: true, sectionId: second });
        return;
    }

    // Case 2: First part is a known section ID (direct section link)
    if (SECTION_TO_TAB[first]) {
        const tabName = SECTION_TO_TAB[first];
        const routeName = TAB_ROUTE_NAMES[tabName];
        // Update hash to canonical form: tab/section
        history.replaceState(null, '', `#${routeName}/${first}`);
        switchToTab(tabName, { updateHash: false, sectionId: first });
        return;
    }

    // Fallback: treat as users tab
    switchToTab('users', { updateHash: true });
}

function setupTabSwitching() {
    const tabButtons = document.querySelectorAll('.tab-btn');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;
            switchToTab(tabName);
        });
    });

    // Listen for hash changes (browser back/forward, manual URL edit)
    window.addEventListener('hashchange', () => {
        navigateFromHash();
    });
}

async function loadTabData(tabName) {
    switch (tabName) {
        case 'users':
            await loadUsers();
            break;
        case 'workers':
            await loadWorkers();
            break;
        case 'config':
            await loadConfigurationData();
            break;
        case 'system':
            await loadSystemTab();
            break;
        case 'logs':
            await loadLogConfig();
            await loadAuditLogs(false);
            break;
    }
}

// =========================================================================
// User Management
// =========================================================================

function setupUserEvents() {
    document.getElementById('add-user-btn').addEventListener('click', () => {
        openUserModal();
    });

    document.getElementById('user-modal-close').addEventListener('click', () => {
        document.getElementById('user-modal').classList.add('hidden');
    });

    document.getElementById('user-modal-cancel').addEventListener('click', () => {
        document.getElementById('user-modal').classList.add('hidden');
    });

    document.getElementById('user-modal-save').addEventListener('click', async () => {
        await saveUser();
    });
}

async function loadUsers() {
    const tbody = document.getElementById('users-table-body');
    const loading = document.getElementById('users-loading');

    loading.classList.remove('hidden');
    tbody.innerHTML = '';

    try {
        const users = await getUsers();
        cachedUsers = users;
        const currentUser = getCurrentUser();

        // Count active admins for last-admin protection
        const activeAdminCount = users.filter(u =>
            u.role?.toUpperCase() === 'ADMIN' && u.is_active
        ).length;

        users.forEach(user => {
            const isCurrentUser = currentUser && user.id === currentUser.id;
            const isLastAdmin = user.role?.toUpperCase() === 'ADMIN' && activeAdminCount <= 1;
            const isPolkaAuth = user.is_polka_auth;

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${user.id}</td>
                <td>${escapeHtml(user.username)}</td>
                <td>${isPolkaAuth
                    ? '<span class="badge badge-info" title="Authenticated via PolkaSQL">PolkaSQL</span>'
                    : '<span class="badge badge-secondary">Local</span>'
                }</td>
                <td><span class="badge badge-${user.role?.toUpperCase() === 'ADMIN' ? 'primary' : 'secondary'}">${user.role}</span></td>
                <td><span class="status-badge ${user.is_active ? 'status-active' : 'status-inactive'}">${user.is_active ? 'Active' : 'Inactive'}</span></td>
                <td>${formatDate(user.created_at)}</td>
                <td>
                    <button class="btn btn-sm btn-secondary edit-user-btn" data-id="${user.id}">Edit</button>
                    <button class="btn btn-sm btn-danger delete-user-btn" data-id="${user.id}"
                        ${isCurrentUser ? 'disabled title="Cannot delete your own account"' : ''}
                        ${isLastAdmin ? 'disabled title="Cannot delete last admin user"' : ''}
                    >Delete</button>
                </td>
            `;
            tbody.appendChild(row);
        });

        document.querySelectorAll('.edit-user-btn').forEach(btn => {
            btn.addEventListener('click', () => editUser(parseInt(btn.dataset.id)));
        });

        document.querySelectorAll('.delete-user-btn').forEach(btn => {
            btn.addEventListener('click', () => confirmDeleteUser(parseInt(btn.dataset.id)));
        });

    } catch (error) {
        console.error('Failed to load users:', error);
        tbody.innerHTML = '<tr><td colspan="7">Error loading users</td></tr>';
    } finally {
        loading.classList.add('hidden');
    }
}

async function editUser(userId) {
    const form = document.getElementById('user-form');
    form.reset();
    document.getElementById('user-modal-title').textContent = 'Edit User';

    const usernameInput = document.getElementById('user-username');
    const passwordInput = document.getElementById('user-password');
    const passwordHelp = passwordInput.nextElementSibling;

    // Reset field states
    usernameInput.disabled = false;
    passwordInput.disabled = false;
    if (passwordHelp) passwordHelp.textContent = 'Leave empty to keep current password';

    try {
        const users = cachedUsers || await getUsers();
        const user = users.find(u => u.id === userId);
        if (user) {
            document.getElementById('user-id').value = user.id;
            document.getElementById('user-username').value = user.username;
            document.getElementById('user-password').value = '';
            document.getElementById('user-role').value = user.role;
            document.getElementById('user-active').checked = user.is_active;

            // Disable username/password for PolkaSQL users
            if (user.is_polka_auth) {
                usernameInput.disabled = true;
                passwordInput.disabled = true;
                if (passwordHelp) passwordHelp.textContent = 'Cannot modify credentials for PolkaSQL users';
            }
        }
    } catch (error) {
        console.error('Failed to load user for edit:', error);
    }

    document.getElementById('user-modal').classList.remove('hidden');
}

function openUserModal() {
    const form = document.getElementById('user-form');
    form.reset();
    document.getElementById('user-modal-title').textContent = 'Add User';
    document.getElementById('user-id').value = '';
    document.getElementById('user-active').checked = true;

    // Reset field states
    const usernameInput = document.getElementById('user-username');
    const passwordInput = document.getElementById('user-password');
    const passwordHelp = passwordInput.nextElementSibling;
    usernameInput.disabled = false;
    passwordInput.disabled = false;
    if (passwordHelp) passwordHelp.textContent = 'Leave empty to keep current password';

    document.getElementById('user-modal').classList.remove('hidden');
}

async function saveUser() {
    const userId = document.getElementById('user-id').value;
    const username = document.getElementById('user-username').value;
    const password = document.getElementById('user-password').value;
    const role = document.getElementById('user-role').value;
    const isActive = document.getElementById('user-active').checked;

    try {
        if (userId) {
            const updateData = { role, is_active: isActive };
            if (password) updateData.password = password;
            await updateUser(userId, updateData);
        } else {
            if (!password) {
                alert('Password is required for new users');
                return;
            }
            await createUser({ username, password, role, is_active: isActive });
        }

        document.getElementById('user-modal').classList.add('hidden');
        await loadUsers();
    } catch (error) {
        alert('Error saving user: ' + error.message);
    }
}

async function confirmDeleteUser(userId) {
    const confirmed = await showConfirm('Are you sure you want to delete this user?');
    if (confirmed) {
        try {
            await deleteUser(userId);
            await loadUsers();
        } catch (error) {
            alert('Error deleting user: ' + error.message);
        }
    }
}

// =========================================================================
// Worker Management
// =========================================================================

function setupWorkerEvents() {
    document.getElementById('refresh-workers-btn').addEventListener('click', loadWorkers);

    // Provision modal buttons
    document.getElementById('provision-modal-close').addEventListener('click', () => {
        document.getElementById('provision-modal').classList.add('hidden');
    });
    document.getElementById('provision-modal-cancel').addEventListener('click', () => {
        document.getElementById('provision-modal').classList.add('hidden');
    });
    document.getElementById('provision-modal-save').addEventListener('click', async () => {
        const workerId = parseInt(document.getElementById('provision-modal-save').dataset.workerId);
        await executeProvision(workerId);
    });
}

async function loadWorkers() {
    const tbody = document.getElementById('workers-table-body');
    const pendingTbody = document.getElementById('pending-workers-table-body');
    const loading = document.getElementById('workers-loading');

    loading.classList.remove('hidden');
    tbody.innerHTML = '';
    pendingTbody.innerHTML = '';

    try {
        const workers = await getWorkers();

        // Store worker data for provision dialog pre-fill
        workerDataMap = {};
        workers.forEach(w => { workerDataMap[w.id] = w; });

        const activeWorkers = workers.filter(w => w.status?.toUpperCase() !== 'PENDING');
        const pendingWorkers = workers.filter(w => w.status?.toUpperCase() === 'PENDING');

        activeWorkers.forEach(worker => {
            const status = worker.status?.toUpperCase();
            const isActive = status === 'ACTIVE';
            // OFFLINE = missed heartbeats; the worker returns to ACTIVE by itself
            // when it checks in, so it can be suspended but needs no activation.
            const isOffline = status === 'OFFLINE';
            const statusTitle = isOffline
                ? 'No heartbeat received. Returns to ACTIVE automatically when the worker checks in.'
                : '';
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${worker.id}</td>
                <td>${escapeHtml(worker.hostname || 'N/A')}</td>
                <td><span class="status-badge status-${(worker.status || '').toLowerCase()}" title="${statusTitle}">${worker.status}</span></td>
                <td>${formatDate(worker.last_heartbeat)}</td>
                <td>
                    <small>A: ${escapeHtml(worker.path_a_prefix || 'Not set')}<br>
                    B: ${escapeHtml(worker.path_b_prefix || 'Not set')}<br>
                    C: ${escapeHtml(worker.path_c_prefix || 'Not set')}</small>
                </td>
                <td>
                    ${isActive || isOffline
                        ? `<button class="btn btn-sm btn-warning suspend-worker-btn" data-id="${worker.id}">Suspend</button>`
                        : `<button class="btn btn-sm btn-success activate-worker-btn" data-id="${worker.id}">Activate</button>`
                    }
                    <button class="btn btn-sm btn-danger remove-worker-btn" data-id="${worker.id}" data-name="${escapeHtml(worker.name || worker.hostname)}">Remove</button>
                    ${isActive ? `
                    <button class="btn btn-sm btn-secondary worker-ping-btn" data-id="${worker.id}">Ping</button>
                    <button class="btn btn-sm btn-secondary worker-status-btn" data-id="${worker.id}">Status</button>
                    <button class="btn btn-sm btn-primary worker-provision-btn" data-id="${worker.id}">Provision</button>
                    ` : ''}
                </td>
            `;
            tbody.appendChild(row);
        });

        // Worker command result row (hidden, shown on demand)
        activeWorkers.forEach(worker => {
            if (worker.status?.toUpperCase() === 'ACTIVE') {
                const resultRow = document.createElement('tr');
                resultRow.id = `worker-cmd-row-${worker.id}`;
                resultRow.style.display = 'none';
                resultRow.innerHTML = `<td colspan="6"><div class="worker-cmd-result" id="worker-cmd-result-${worker.id}"></div></td>`;
                // Insert after the worker's main row
                const mainRow = tbody.querySelector(`tr:has(.worker-ping-btn[data-id="${worker.id}"])`);
                if (mainRow && mainRow.nextSibling) {
                    tbody.insertBefore(resultRow, mainRow.nextSibling);
                } else {
                    tbody.appendChild(resultRow);
                }
            }
        });

        // Attach event listeners
        document.querySelectorAll('.suspend-worker-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await apiRequest(`/api/admin/workers/${btn.dataset.id}/suspend`, { method: 'POST' });
                    await loadWorkers();
                } catch (error) {
                    alert('Error suspending worker: ' + error.message);
                }
            });
        });

        document.querySelectorAll('.activate-worker-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await apiRequest(`/api/admin/workers/${btn.dataset.id}`, {
                        method: 'PUT',
                        body: JSON.stringify({ status: 'ACTIVE' })
                    });
                    await loadWorkers();
                } catch (error) {
                    alert('Error activating worker: ' + error.message);
                }
            });
        });

        document.querySelectorAll('.remove-worker-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const workerName = btn.dataset.name;
                const confirmed = await showConfirm(`Are you sure you want to remove worker "${workerName}"?\n\nThe worker can re-register if it's still active.`);
                if (!confirmed) return;
                try {
                    await apiRequest(`/api/admin/workers/${btn.dataset.id}`, { method: 'DELETE' });
                    await loadWorkers();
                } catch (error) {
                    alert('Error removing worker: ' + error.message);
                }
            });
        });

        document.querySelectorAll('.worker-ping-btn').forEach(btn => {
            btn.addEventListener('click', () => sendWorkerCmd(parseInt(btn.dataset.id), 'ping'));
        });

        document.querySelectorAll('.worker-status-btn').forEach(btn => {
            btn.addEventListener('click', () => sendWorkerCmd(parseInt(btn.dataset.id), 'get_status'));
        });

        document.querySelectorAll('.worker-provision-btn').forEach(btn => {
            btn.addEventListener('click', () => provisionWorkerDialog(parseInt(btn.dataset.id)));
        });

        // Pending workers
        if (pendingWorkers.length === 0) {
            document.getElementById('no-pending-workers').style.display = 'block';
        } else {
            document.getElementById('no-pending-workers').style.display = 'none';

            pendingWorkers.forEach(worker => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${worker.id}</td>
                    <td>${escapeHtml(worker.hostname || 'N/A')}</td>
                    <td>${formatDate(worker.created_at)}</td>
                    <td>
                        <button class="btn btn-sm btn-primary approve-worker-btn" data-id="${worker.id}">Approve</button>
                        <button class="btn btn-sm btn-danger reject-worker-btn" data-id="${worker.id}">Reject</button>
                    </td>
                `;
                pendingTbody.appendChild(row);
            });

            document.querySelectorAll('.approve-worker-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await approveWorker(btn.dataset.id);
                        await loadWorkers();
                    } catch (error) {
                        alert('Error approving worker: ' + error.message);
                    }
                });
            });

            document.querySelectorAll('.reject-worker-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await rejectWorker(btn.dataset.id);
                        await loadWorkers();
                    } catch (error) {
                        alert('Error rejecting worker: ' + error.message);
                    }
                });
            });
        }

    } catch (error) {
        console.error('Failed to load workers:', error);
        tbody.innerHTML = '<tr><td colspan="6">Error loading workers</td></tr>';
    } finally {
        loading.classList.add('hidden');
    }
}

// =========================================================================
// Worker Commands (moved from System tab to Workers tab)
// =========================================================================

async function sendWorkerCmd(workerId, command) {
    // Show the result row
    const resultRow = document.getElementById(`worker-cmd-row-${workerId}`);
    const resultDiv = document.getElementById(`worker-cmd-result-${workerId}`);

    if (resultRow) resultRow.style.display = '';
    if (resultDiv) resultDiv.innerHTML = '<span class="loading">Sending command...</span>';

    try {
        const response = await apiRequest(`/api/admin/workers/${workerId}/command`, {
            method: 'POST',
            body: JSON.stringify({ command, params: {}, timeout_seconds: 30 })
        });

        if (response.status === 'success') {
            resultDiv.innerHTML = `<span class="success">${escapeHtml(command)}: ${escapeHtml(response.message || 'OK')} (${response.duration_ms}ms)</span>`;
            if (response.data) {
                resultDiv.innerHTML += `<pre>${escapeHtml(JSON.stringify(response.data, null, 2))}</pre>`;
            }
        } else {
            resultDiv.innerHTML = `<span class="error">${escapeHtml(command)} failed: ${escapeHtml(response.message)}</span>`;
        }
    } catch (error) {
        if (resultDiv) resultDiv.innerHTML = `<span class="error">Error: ${escapeHtml(error.message)}</span>`;
    }
}

function provisionWorkerDialog(workerId) {
    const worker = workerDataMap[workerId] || {};

    // Pre-fill inputs with current worker paths as placeholder text
    const inputA = document.getElementById('provision-path-a');
    const inputB = document.getElementById('provision-path-b');
    const inputC = document.getElementById('provision-path-c');

    inputA.value = '';
    inputB.value = '';
    inputC.value = '';
    inputA.placeholder = worker.path_a_prefix || 'e.g. \\\\server\\shareA';
    inputB.placeholder = worker.path_b_prefix || 'e.g. \\\\server\\shareB';
    inputC.placeholder = worker.path_c_prefix || 'e.g. \\\\server\\shareC';

    // Store workerId on the save button
    document.getElementById('provision-modal-save').dataset.workerId = workerId;

    document.getElementById('provision-modal').classList.remove('hidden');
}

async function executeProvision(workerId) {
    const pathA = document.getElementById('provision-path-a').value.trim();
    const pathB = document.getElementById('provision-path-b').value.trim();
    const pathC = document.getElementById('provision-path-c').value.trim();

    if (!pathA && !pathB && !pathC) {
        showNotification('No changes specified', 'warning');
        return;
    }

    document.getElementById('provision-modal').classList.add('hidden');

    const config = {};
    if (pathA) config.path_a_prefix = pathA;
    if (pathB) config.path_b_prefix = pathB;
    if (pathC) config.path_c_prefix = pathC;

    const resultRow = document.getElementById(`worker-cmd-row-${workerId}`);
    const resultDiv = document.getElementById(`worker-cmd-result-${workerId}`);

    if (resultRow) resultRow.style.display = '';
    if (resultDiv) resultDiv.innerHTML = '<span class="loading">Provisioning worker...</span>';

    try {
        await apiRequest(`/api/admin/workers/${workerId}/provision`, {
            method: 'POST',
            body: JSON.stringify({ config, restart_required: false })
        });
        if (resultDiv) resultDiv.innerHTML = '<span class="success">Worker provisioned successfully</span>';
        showNotification('Worker provisioned successfully', 'success');
        await loadWorkers();
    } catch (error) {
        if (resultDiv) resultDiv.innerHTML = `<span class="error">Error: ${escapeHtml(error.message)}</span>`;
        showNotification('Error provisioning worker: ' + error.message, 'error');
    }
}

// =========================================================================
// Configuration Management
// =========================================================================

function setupConfigEvents() {
    document.getElementById('save-config-btn').addEventListener('click', async () => {
        try {
            await saveConfigurationData();
        } catch (error) {
            console.error('Failed to save configuration:', error);
        }
    });
}

/**
 * Load configuration data and populate form fields
 */
export async function loadConfigurationData() {
    try {
        const configs = await apiRequest('/api/admin/config');

        const configMap = {};
        configs.forEach(cfg => {
            configMap[cfg.key] = cfg;
        });

        const fieldMappings = {
            'config-max-concurrent-users': 'max_concurrent_users',
            'config-session-lifetime': 'session_lifetime_days',
            'config-polka-auth-enabled': 'polka_auth_enabled',
            'config-polka-auth-url': 'polka_auth_url',
            'config-polka-auth-api-key': 'polka_auth_api_key',
            'config-polka-auth-timeout': 'polka_auth_timeout',
            'config-rosapi-enabled': 'rosapi_enabled',
            'config-rosapi-base-url': 'rosapi_base_url',
            'config-rosapi-auth-base-url': 'rosapi_auth_base_url',
            'config-rosapi-auth-login-endpoint': 'rosapi_auth_login_endpoint',
            'config-rosapi-auth-refresh-endpoint': 'rosapi_auth_refresh_endpoint',
            'config-rosapi-auth-email': 'rosapi_auth_email',
            'config-rosapi-auth-password': 'rosapi_auth_password',
            'config-rosapi-timeout': 'rosapi_timeout',
            'config-rosapi-push-enabled': 'rosapi_push_enabled',
            'config-rosapi-push-base-url': 'rosapi_push_base_url',
            'config-rosapi-push-endpoint': 'rosapi_push_endpoint',
            'config-rosapi-push-method': 'rosapi_push_method',
            'config-rosapi-push-payload': 'rosapi_push_payload',
            'config-rosapi-pull-enabled': 'rosapi_pull_enabled',
            'config-rosapi-pull-base-url': 'rosapi_pull_base_url',
            'config-rosapi-pull-endpoint': 'rosapi_pull_endpoint',
            'config-rosapi-pull-method': 'rosapi_pull_method',
            'config-rosapi-pull-payload': 'rosapi_pull_payload',
            'config-rosapi-verify-base-url': 'rosapi_verify_base_url',
            'config-rosapi-verify-endpoint': 'rosapi_verify_endpoint',
            'config-pim-enabled': 'pim_enabled',
            'config-pim-base-url': 'pim_base_url',
            'config-pim-endpoint': 'pim_endpoint',
            'config-pim-method': 'pim_method',
            'config-pim-api-token': 'pim_api_token',
            'config-pim-timeout': 'pim_timeout',
            'config-pim-push-enabled': 'pim_push_enabled',
            'config-pim-push-event-type': 'pim_push_event_type',
            'config-pim-pull-enabled': 'pim_pull_enabled',
            'config-pim-pull-event-type': 'pim_pull_event_type',
            'config-pim-update-enabled': 'pim_update_enabled',
            'config-pim-update-event-type': 'pim_update_event_type',
            'config-pim-payload-template': 'pim_payload_template',
            'config-pim-tg-id': 'pim_tg_id',
            'config-catalog-validation-enabled': 'catalog_validation_enabled',
            'config-catalog-validation-url': 'catalog_validation_url',
            'config-catalog-validation-api-key': 'catalog_validation_api_key',
            'config-catalog-validation-timeout': 'catalog_validation_timeout',
            'config-catalog-validation-max-suggestions': 'catalog_validation_max_suggestions',
            'config-catalog-validation-fail-open': 'catalog_validation_fail_open',
            'config-push-validation-enabled': 'push_validation_enabled',
            'config-push-validation-min-files': 'push_validation_min_files',
            'config-push-validation-allowed-extensions': 'push_validation_allowed_extensions',
            'config-push-validation-verify-content': 'push_validation_verify_content',
            'config-enable-update-archive-mirror': 'enable_update_archive_mirror',
            'config-update-upload-max-mb': 'update_upload_max_mb',
            'config-update-upload-ttl-hours': 'update_upload_ttl_hours',
            'config-worker-heartbeat-interval': 'worker_heartbeat_interval',
            'config-worker-heartbeat-timeout': 'worker_heartbeat_timeout',
            'config-worker-timeout': 'worker_timeout',
            'config-worker-retry': 'worker_retry_attempts',
            'config-operation-timeout': 'operation_timeout',
            'config-auto-rollback': 'enable_auto_rollback',
            'config-push-flatten': 'enable_push_flatten',
            'config-push-archive': 'enable_push_archive',
            'config-push-ignore-masks': 'push_ignore_file_masks',
            'config-max-listing-items': 'max_file_listing_items',
            'config-lazy-loading': 'enable_lazy_loading',
            'config-ip-whitelist': 'enable_ip_whitelist',
            'config-ip-whitelist-list': 'ip_whitelist',
            'config-rate-limiting': 'enable_rate_limiting',
            'config-rate-limit': 'rate_limit_requests_per_minute',
            'config-maintenance-mode': 'maintenance_mode',
            'config-maintenance-message': 'maintenance_message'
        };

        for (const [elementId, configKey] of Object.entries(fieldMappings)) {
            const element = document.getElementById(elementId);
            if (!element) continue;

            const cfg = configMap[configKey];
            if (!cfg) continue;

            if (element.type === 'checkbox') {
                element.checked = cfg.value?.toLowerCase() === 'true';
            } else {
                element.value = cfg.value || '';
            }
        }
    } catch (error) {
        console.error('Failed to load configuration:', error);
    }
}

/**
 * Save configuration data from form fields
 */
export async function saveConfigurationData() {
    const fieldMappings = {
        'config-max-concurrent-users': 'max_concurrent_users',
        'config-session-lifetime': 'session_lifetime_days',
        'config-polka-auth-enabled': 'polka_auth_enabled',
        'config-polka-auth-url': 'polka_auth_url',
        'config-polka-auth-api-key': 'polka_auth_api_key',
        'config-polka-auth-timeout': 'polka_auth_timeout',
        'config-rosapi-enabled': 'rosapi_enabled',
        'config-rosapi-base-url': 'rosapi_base_url',
        'config-rosapi-auth-base-url': 'rosapi_auth_base_url',
        'config-rosapi-auth-login-endpoint': 'rosapi_auth_login_endpoint',
        'config-rosapi-auth-refresh-endpoint': 'rosapi_auth_refresh_endpoint',
        'config-rosapi-auth-email': 'rosapi_auth_email',
        'config-rosapi-auth-password': 'rosapi_auth_password',
        'config-rosapi-timeout': 'rosapi_timeout',
        'config-rosapi-push-enabled': 'rosapi_push_enabled',
        'config-rosapi-push-base-url': 'rosapi_push_base_url',
        'config-rosapi-push-endpoint': 'rosapi_push_endpoint',
        'config-rosapi-push-method': 'rosapi_push_method',
        'config-rosapi-push-payload': 'rosapi_push_payload',
        'config-rosapi-pull-enabled': 'rosapi_pull_enabled',
        'config-rosapi-pull-base-url': 'rosapi_pull_base_url',
        'config-rosapi-pull-endpoint': 'rosapi_pull_endpoint',
        'config-rosapi-pull-method': 'rosapi_pull_method',
        'config-rosapi-pull-payload': 'rosapi_pull_payload',
        'config-rosapi-verify-base-url': 'rosapi_verify_base_url',
        'config-rosapi-verify-endpoint': 'rosapi_verify_endpoint',
        'config-pim-enabled': 'pim_enabled',
        'config-pim-base-url': 'pim_base_url',
        'config-pim-endpoint': 'pim_endpoint',
        'config-pim-method': 'pim_method',
        'config-pim-api-token': 'pim_api_token',
        'config-pim-timeout': 'pim_timeout',
        'config-pim-push-enabled': 'pim_push_enabled',
        'config-pim-push-event-type': 'pim_push_event_type',
        'config-pim-pull-enabled': 'pim_pull_enabled',
        'config-pim-pull-event-type': 'pim_pull_event_type',
        'config-pim-update-enabled': 'pim_update_enabled',
        'config-pim-update-event-type': 'pim_update_event_type',
        'config-pim-payload-template': 'pim_payload_template',
        'config-pim-tg-id': 'pim_tg_id',
        'config-catalog-validation-enabled': 'catalog_validation_enabled',
        'config-catalog-validation-url': 'catalog_validation_url',
        'config-catalog-validation-api-key': 'catalog_validation_api_key',
        'config-catalog-validation-timeout': 'catalog_validation_timeout',
        'config-catalog-validation-max-suggestions': 'catalog_validation_max_suggestions',
        'config-catalog-validation-fail-open': 'catalog_validation_fail_open',
        'config-push-validation-enabled': 'push_validation_enabled',
        'config-push-validation-min-files': 'push_validation_min_files',
        'config-push-validation-allowed-extensions': 'push_validation_allowed_extensions',
        'config-push-validation-verify-content': 'push_validation_verify_content',
        'config-enable-update-archive-mirror': 'enable_update_archive_mirror',
        'config-update-upload-max-mb': 'update_upload_max_mb',
        'config-update-upload-ttl-hours': 'update_upload_ttl_hours',
        'config-worker-heartbeat-interval': 'worker_heartbeat_interval',
        'config-worker-heartbeat-timeout': 'worker_heartbeat_timeout',
        'config-worker-timeout': 'worker_timeout',
        'config-worker-retry': 'worker_retry_attempts',
        'config-operation-timeout': 'operation_timeout',
        'config-auto-rollback': 'enable_auto_rollback',
        'config-push-flatten': 'enable_push_flatten',
        'config-push-archive': 'enable_push_archive',
        'config-push-ignore-masks': 'push_ignore_file_masks',
        'config-max-listing-items': 'max_file_listing_items',
        'config-lazy-loading': 'enable_lazy_loading',
        'config-ip-whitelist': 'enable_ip_whitelist',
        'config-ip-whitelist-list': 'ip_whitelist',
        'config-rate-limiting': 'enable_rate_limiting',
        'config-rate-limit': 'rate_limit_requests_per_minute',
        'config-maintenance-mode': 'maintenance_mode',
        'config-maintenance-message': 'maintenance_message'
    };

    const configs = {};
    for (const [elementId, configKey] of Object.entries(fieldMappings)) {
        const element = document.getElementById(elementId);
        if (!element) continue;

        if (element.type === 'checkbox') {
            configs[configKey] = element.checked ? 'true' : 'false';
        } else {
            configs[configKey] = element.value;
        }
    }

    try {
        await apiRequest('/api/admin/config/bulk', {
            method: 'POST',
            body: JSON.stringify({ configs })
        });
        showNotification('Configuration saved successfully', 'success');
    } catch (error) {
        console.error('Failed to save configuration:', error);
        showNotification(error.message || 'Failed to save configuration', 'error');
        throw error;
    }
}

// =========================================================================
// System Tab
// =========================================================================

function setupSystemEvents() {
    document.getElementById('refresh-stats-btn')?.addEventListener('click', () => {
        loadSystemStats();
    });
}

async function loadSystemTab() {
    await loadSystemStats();
    startStatsAutoRefresh();
}

function startStatsAutoRefresh() {
    stopStatsAutoRefresh();
    statsRefreshInterval = setInterval(() => {
        if (currentTab === 'system') {
            loadSystemStats();
        }
    }, 5000);
}

function stopStatsAutoRefresh() {
    if (statsRefreshInterval) {
        clearInterval(statsRefreshInterval);
        statsRefreshInterval = null;
    }
}

async function loadSystemStats() {
    try {
        const [stats, health] = await Promise.all([
            apiRequest('/api/admin/stats/system'),
            apiRequest('/api/admin/health')
        ]);
        renderSystemStats(stats, health);
    } catch (error) {
        console.error('Failed to load system stats:', error);
    }
}

function renderSystemStats(stats, health) {
    const container = document.getElementById('system-stats-container');
    if (!container) return;

    // Build health components display
    const componentEntries = Object.entries(health.components || {});
    const healthComponentsHtml = componentEntries.map(([name, info]) => {
        const statusIcon = info.status === 'healthy' ? '&#10003;' : info.status === 'critical' ? '&#10007;' : '&#9888;';
        const statusClass = info.status === 'healthy' ? 'success' : info.status === 'critical' ? 'error' : 'warning';
        return `<div><span class="${statusClass}">${statusIcon}</span> <strong>${escapeHtml(name)}:</strong> ${escapeHtml(info.message || info.status)}</div>`;
    }).join('');

    container.innerHTML = `
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Operations</h3>
                <div class="stat-value">${stats.active_operations}</div>
                <div class="stat-label">Active</div>
                <div class="stat-details">
                    In Progress: ${stats.operations_in_progress} | Pending: ${stats.operations_pending}
                </div>
            </div>

            <div class="stat-card">
                <h3>Workers</h3>
                <div class="stat-value">${stats.active_workers}</div>
                <div class="stat-label">Active</div>
                <div class="stat-details">
                    Healthy: ${stats.workers_healthy} | Suspended: ${stats.workers_suspended} | Offline: ${stats.workers_offline}
                    ${stats.pending_workers > 0 ? `<br><strong>${stats.pending_workers} pending approval</strong>` : ''}
                </div>
            </div>

            <div class="stat-card">
                <h3>Users</h3>
                <div class="stat-value">${stats.active_users}</div>
                <div class="stat-label">Active Sessions</div>
                <div class="stat-details">
                    Total: ${stats.total_users} (${stats.admin_users} admins, ${stats.viewer_users} users)
                </div>
            </div>

            <div class="stat-card">
                <h3>Last Hour</h3>
                <div class="stat-value">${stats.operations_completed_last_hour}</div>
                <div class="stat-label">Operations Completed</div>
                <div class="stat-details">
                    Failed: ${stats.operations_failed_last_hour}
                    ${stats.avg_operation_duration_seconds ? `<br>Avg Duration: ${stats.avg_operation_duration_seconds.toFixed(1)}s` : ''}
                </div>
            </div>

            <div class="stat-card">
                <h3>System Health</h3>
                <div class="stat-value">
                    <span class="badge badge-${health.overall_status === 'healthy' ? 'success' : health.overall_status === 'degraded' ? 'warning' : 'danger'}">${health.overall_status}</span>
                </div>
                <div class="stat-label">Components</div>
                <div class="stat-details">
                    ${healthComponentsHtml}
                </div>
            </div>
        </div>
    `;
}

// =========================================================================
// Logs Management
// =========================================================================

function setupLogEvents() {
    document.getElementById('refresh-logs-btn').addEventListener('click', () => loadAuditLogs(false));

    let searchTimeout;
    document.getElementById('log-search').addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => loadAuditLogs(false), 500);
    });

    document.getElementById('export-logs-btn').addEventListener('click', exportAuditLogs);

    // Logging Configuration save
    document.getElementById('save-log-config-btn').addEventListener('click', saveLogConfig);
}

async function loadLogConfig() {
    try {
        const config = await apiRequest('/api/admin/logs/config');

        const el = (id) => document.getElementById(id);
        if (el('log-config-syslog-enabled')) el('log-config-syslog-enabled').checked = config.enable_syslog;
        if (el('log-config-syslog-host')) el('log-config-syslog-host').value = config.syslog_host || '';
        if (el('log-config-syslog-port')) el('log-config-syslog-port').value = config.syslog_port || 514;
        if (el('log-config-syslog-protocol')) el('log-config-syslog-protocol').value = config.syslog_protocol || 'UDP';
        if (el('log-config-syslog-format')) el('log-config-syslog-format').value = config.syslog_format || 'RFC5424';
        if (el('log-config-syslog-hostname')) el('log-config-syslog-hostname').value = config.syslog_hostname || '';
        if (el('log-config-retention')) el('log-config-retention').value = config.log_retention_days || 14;
        if (el('log-config-compression')) el('log-config-compression').checked = config.enable_log_compression;
    } catch (error) {
        console.error('Failed to load logging config:', error);
    }
}

async function saveLogConfig() {
    const el = (id) => document.getElementById(id);

    const configData = {
        enable_syslog: el('log-config-syslog-enabled')?.checked || false,
        syslog_host: el('log-config-syslog-host')?.value || null,
        syslog_port: parseInt(el('log-config-syslog-port')?.value) || 514,
        syslog_protocol: el('log-config-syslog-protocol')?.value || 'UDP',
        syslog_format: el('log-config-syslog-format')?.value || 'RFC5424',
        syslog_hostname: el('log-config-syslog-hostname')?.value || '',
        log_retention_days: parseInt(el('log-config-retention')?.value) || 14,
        enable_log_compression: el('log-config-compression')?.checked || false,
    };

    // Don't send null syslog_host as empty string
    if (!configData.syslog_host) configData.syslog_host = null;

    try {
        await apiRequest('/api/admin/logs/config', {
            method: 'PUT',
            body: JSON.stringify(configData)
        });
        showNotification('Logging configuration saved successfully', 'success');
    } catch (error) {
        console.error('Failed to save logging config:', error);
        showNotification(error.message || 'Failed to save logging configuration', 'error');
    }
}

async function exportAuditLogs() {
    try {
        // Fetch all logs in batches of 1000 (API max)
        let allLogs = [];
        let offset = 0;
        const batchSize = 1000;
        let hasMore = true;

        while (hasMore) {
            const response = await apiRequest(`/api/admin/logs/stream?offset=${offset}&limit=${batchSize}`);
            if (response.logs && response.logs.length > 0) {
                allLogs = allLogs.concat(response.logs);
                offset += response.logs.length;
                hasMore = response.has_more;
            } else {
                hasMore = false;
            }
        }

        const json = JSON.stringify(allLogs, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `audit-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
        a.click();
        URL.revokeObjectURL(url);
        showNotification(`Exported ${allLogs.length} audit log entries`, 'success');
    } catch (error) {
        showNotification('Error exporting logs: ' + error.message, 'error');
    }
}

// =========================================================================
// Audit Log State
// =========================================================================

let currentPage = 1;
const pageSize = 50;
let totalLogCount = 0;

async function loadAuditLogs(preservePage = false) {
    const tbody = document.getElementById('logs-table-body');
    const loading = document.getElementById('logs-loading');

    if (!preservePage) {
        currentPage = 1;
    }

    tbody.innerHTML = '';
    loading.classList.remove('hidden');

    try {
        const search = document.getElementById('log-search')?.value;
        const offset = (currentPage - 1) * pageSize;

        const params = new URLSearchParams();
        if (search) params.append('search_query', search);
        params.append('offset', offset);
        params.append('limit', pageSize);

        const response = await apiRequest(`/api/admin/logs/stream?${params.toString()}`);

        if (!response || !response.logs) {
            throw new Error('Invalid response from server');
        }

        const logs = response.logs;
        totalLogCount = response.total_count;

        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="no-data">No audit logs found</td></tr>';
        }

        logs.forEach(log => {
            let sourceDir = '-';
            let targetDir = '-';

            if (log.details && (log.action === 'push' || log.action === 'pull')) {
                if (log.details.source_directory) sourceDir = log.details.source_directory;
                if (log.details.target_directory) targetDir = log.details.target_directory;
            }

            let fullTimestamp = 'N/A';
            if (log.timestamp) {
                const date = new Date(log.timestamp);
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hours = String(date.getHours()).padStart(2, '0');
                const minutes = String(date.getMinutes()).padStart(2, '0');
                const seconds = String(date.getSeconds()).padStart(2, '0');
                const milliseconds = String(date.getMilliseconds()).padStart(3, '0');
                fullTimestamp = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}.${milliseconds}`;
            }

            const relativeTime = formatRelativeTime(log.timestamp);

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${fullTimestamp}</td>
                <td>${relativeTime}</td>
                <td>${escapeHtml(log.action)}</td>
                <td>${escapeHtml(sourceDir)}</td>
                <td>${escapeHtml(targetDir)}</td>
                <td>${log.user_id || '-'}</td>
                <td>${escapeHtml(log.username || 'System')}</td>
                <td>${escapeHtml(log.ip_address || 'N/A')}</td>
            `;
            tbody.appendChild(tr);
        });

        renderPagination();

    } catch (error) {
        console.error('Failed to load logs:', error);
        tbody.innerHTML = '<tr><td colspan="8" class="error">Error loading logs: ' + escapeHtml(error.message) + '</td></tr>';
    } finally {
        loading.classList.add('hidden');
    }
}

function renderPagination() {
    const container = document.getElementById('logs-pagination');
    if (!container) return;

    const totalPages = Math.max(1, Math.ceil(totalLogCount / pageSize));
    const startEntry = totalLogCount === 0 ? 0 : (currentPage - 1) * pageSize + 1;
    const endEntry = Math.min(currentPage * pageSize, totalLogCount);

    let html = `<span class="pagination-info">Showing ${startEntry}-${endEntry} of ${totalLogCount}</span>`;
    html += '<div class="pagination-buttons">';

    // Previous button
    html += `<button class="btn btn-sm btn-secondary" ${currentPage <= 1 ? 'disabled' : ''} data-page="${currentPage - 1}">&laquo; Prev</button>`;

    // Page numbers (show max 7 pages with ellipsis)
    const maxVisible = 7;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
        html += `<button class="btn btn-sm btn-secondary" data-page="1">1</button>`;
        if (startPage > 2) html += '<span class="pagination-ellipsis">...</span>';
    }

    for (let i = startPage; i <= endPage; i++) {
        const active = i === currentPage ? 'btn-primary' : 'btn-secondary';
        html += `<button class="btn btn-sm ${active}" data-page="${i}">${i}</button>`;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += '<span class="pagination-ellipsis">...</span>';
        html += `<button class="btn btn-sm btn-secondary" data-page="${totalPages}">${totalPages}</button>`;
    }

    // Next button
    html += `<button class="btn btn-sm btn-secondary" ${currentPage >= totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">Next &raquo;</button>`;
    html += '</div>';

    container.innerHTML = html;

    // Attach click handlers
    container.querySelectorAll('button[data-page]').forEach(btn => {
        btn.addEventListener('click', () => {
            const page = parseInt(btn.dataset.page);
            if (page >= 1 && page <= totalPages && page !== currentPage) {
                currentPage = page;
                loadAuditLogs(true);
            }
        });
    });
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return 'N/A';

    const date = new Date(timestamp);
    if (isNaN(date.getTime())) return 'Invalid date';

    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} min${diffMins !== 1 ? 's' : ''} ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;

    return date.toLocaleString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}
