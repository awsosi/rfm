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
let logsOffset = 0;
const logsLimit = 100;

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

    // Initialize AdminSystem for samba paths and system stats
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

    // Load initial tab
    loadTabData('users');
}

// =========================================================================
// Navigation & Tabs
// =========================================================================

function setupNavigation() {
    document.getElementById('explorer-btn').addEventListener('click', () => {
        window.location.href = 'explorer.html';
    });

    document.getElementById('logout-btn').addEventListener('click', () => {
        logout();
        window.location.href = 'login.html';
    });
}

function setupTabSwitching() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;

            tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            tabPanes.forEach(pane => pane.classList.remove('active'));
            document.getElementById(`tab-${tabName}`).classList.add('active');

            loadTabData(tabName);
        });
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
            await loadLogs();
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
        const currentUser = getCurrentUser();

        users.forEach(user => {
            const isCurrentUser = currentUser && user.id === currentUser.id;
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${user.id}</td>
                <td>${escapeHtml(user.username)}</td>
                <td><span class="badge badge-${user.role?.toUpperCase() === 'ADMIN' ? 'primary' : 'secondary'}">${user.role}</span></td>
                <td><span class="status-badge ${user.is_active ? 'status-active' : 'status-inactive'}">${user.is_active ? 'Active' : 'Inactive'}</span></td>
                <td>${formatDate(user.created_at)}</td>
                <td>
                    <button class="btn btn-sm btn-secondary edit-user-btn" data-id="${user.id}">Edit</button>
                    <button class="btn btn-sm btn-danger delete-user-btn" data-id="${user.id}" ${isCurrentUser ? 'disabled title="Cannot delete your own account"' : ''}>Delete</button>
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
        tbody.innerHTML = '<tr><td colspan="6">Error loading users</td></tr>';
    } finally {
        loading.classList.add('hidden');
    }
}

async function editUser(userId) {
    const form = document.getElementById('user-form');
    form.reset();
    document.getElementById('user-modal-title').textContent = 'Edit User';

    try {
        const users = await getUsers();
        const user = users.find(u => u.id === userId);
        if (user) {
            document.getElementById('user-id').value = user.id;
            document.getElementById('user-username').value = user.username;
            document.getElementById('user-password').value = '';
            document.getElementById('user-role').value = user.role;
            document.getElementById('user-active').checked = user.is_active;
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

        const activeWorkers = workers.filter(w => w.status?.toUpperCase() !== 'PENDING');
        const pendingWorkers = workers.filter(w => w.status?.toUpperCase() === 'PENDING');

        activeWorkers.forEach(worker => {
            const status = worker.status?.toUpperCase();
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${worker.id}</td>
                <td>${escapeHtml(worker.hostname || 'N/A')}</td>
                <td><span class="status-badge status-${worker.status}">${worker.status}</span></td>
                <td>${formatDate(worker.last_heartbeat)}</td>
                <td>
                    <small>A: ${escapeHtml(worker.path_a_prefix || 'Not set')}<br>
                    B: ${escapeHtml(worker.path_b_prefix || 'Not set')}<br>
                    C: ${escapeHtml(worker.path_c_prefix || 'Not set')}</small>
                </td>
                <td>
                    ${status === 'ACTIVE'
                        ? `<button class="btn btn-sm btn-warning suspend-worker-btn" data-id="${worker.id}">Suspend</button>`
                        : `<button class="btn btn-sm btn-success activate-worker-btn" data-id="${worker.id}">Activate</button>`
                    }
                    <button class="btn btn-sm btn-danger remove-worker-btn" data-id="${worker.id}" data-name="${escapeHtml(worker.name || worker.hostname)}">Remove</button>
                </td>
            `;
            tbody.appendChild(row);
        });

        // Attach event listeners for active worker buttons
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
                if (!confirm(`Are you sure you want to remove worker "${workerName}"?\n\nThe worker can re-register if it's still active.`)) {
                    return;
                }
                try {
                    await apiRequest(`/api/admin/workers/${btn.dataset.id}`, { method: 'DELETE' });
                    await loadWorkers();
                } catch (error) {
                    alert('Error removing worker: ' + error.message);
                }
            });
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
            'config-log-retention': 'log_retention_days',
            'config-log-compression': 'enable_log_compression',
            'config-syslog-enabled': 'enable_syslog',
            'config-syslog-host': 'syslog_host',
            'config-syslog-port': 'syslog_port',
            'config-syslog-protocol': 'syslog_protocol',
            'config-remote-audit-enabled': 'enable_remote_audit_api',
            'config-remote-audit-url': 'remote_audit_api_url',
            'config-remote-audit-token': 'remote_audit_api_token',
            'config-remote-audit-timeout': 'remote_audit_api_timeout',
            'config-path-a-prefix': 'global_path_a_prefix',
            'config-path-b-prefix': 'global_path_b_prefix',
            'config-worker-heartbeat-interval': 'worker_heartbeat_interval',
            'config-worker-heartbeat-timeout': 'worker_heartbeat_timeout',
            'config-worker-timeout': 'worker_timeout',
            'config-worker-retry': 'worker_retry_attempts',
            'config-operation-timeout': 'operation_timeout',
            'config-auto-rollback': 'enable_auto_rollback',
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
        'config-log-retention': 'log_retention_days',
        'config-log-compression': 'enable_log_compression',
        'config-syslog-enabled': 'enable_syslog',
        'config-syslog-host': 'syslog_host',
        'config-syslog-port': 'syslog_port',
        'config-syslog-protocol': 'syslog_protocol',
        'config-remote-audit-enabled': 'enable_remote_audit_api',
        'config-remote-audit-url': 'remote_audit_api_url',
        'config-remote-audit-token': 'remote_audit_api_token',
        'config-remote-audit-timeout': 'remote_audit_api_timeout',
        'config-path-a-prefix': 'global_path_a_prefix',
        'config-path-b-prefix': 'global_path_b_prefix',
        'config-worker-heartbeat-interval': 'worker_heartbeat_interval',
        'config-worker-heartbeat-timeout': 'worker_heartbeat_timeout',
        'config-worker-timeout': 'worker_timeout',
        'config-worker-retry': 'worker_retry_attempts',
        'config-operation-timeout': 'operation_timeout',
        'config-auto-rollback': 'enable_auto_rollback',
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
    document.getElementById('add-samba-path-btn')?.addEventListener('click', () => {
        adminSystem.createSambaPath();
    });

    document.getElementById('refresh-stats-btn')?.addEventListener('click', () => {
        adminSystem.loadSystemStats();
    });

    document.getElementById('refresh-worker-control-btn')?.addEventListener('click', () => {
        loadWorkerControlList();
    });
}

async function loadSystemTab() {
    await Promise.all([
        adminSystem.loadSambaPaths(),
        adminSystem.loadSystemStats(),
        loadWorkerControlList()
    ]);
}

async function loadWorkerControlList() {
    const container = document.getElementById('worker-control-list');
    if (!container) return;

    try {
        const workers = await getWorkers();
        const activeWorkers = workers.filter(w => w.status === 'ACTIVE' || w.status === 'active');

        if (activeWorkers.length === 0) {
            container.innerHTML = '<p class="no-data">No active workers available</p>';
            return;
        }

        container.innerHTML = activeWorkers.map(worker => `
            <div class="worker-control-card" data-worker-id="${worker.id}">
                <div class="worker-control-header">
                    <h4>${escapeHtml(worker.name || worker.hostname || 'Worker ' + worker.id)}</h4>
                    <span class="badge badge-${worker.status?.toLowerCase() === 'active' ? 'success' : 'warning'}">${worker.status}</span>
                </div>
                <div class="worker-control-info">
                    <div><strong>Hostname:</strong> ${escapeHtml(worker.hostname || 'N/A')}</div>
                    <div><strong>Path A:</strong> ${escapeHtml(worker.path_a_prefix || 'Not set')}</div>
                    <div><strong>Path B:</strong> ${escapeHtml(worker.path_b_prefix || 'Not set')}</div>
                    <div><strong>Path C:</strong> ${escapeHtml(worker.path_c_prefix || 'Not set')}</div>
                    <div><strong>Last Heartbeat:</strong> ${worker.last_heartbeat ? formatDate(worker.last_heartbeat) : 'Never'}</div>
                </div>
                <div class="worker-control-actions">
                    <button class="btn btn-sm btn-secondary" onclick="sendWorkerCmd(${worker.id}, 'ping')">Ping</button>
                    <button class="btn btn-sm btn-secondary" onclick="sendWorkerCmd(${worker.id}, 'get_status')">Status</button>
                    <button class="btn btn-sm btn-primary" onclick="provisionWorkerDialog(${worker.id})">Provision</button>
                    <button class="btn btn-sm btn-secondary" onclick="sendWorkerCmd(${worker.id}, 'reload_config')">Reload Config</button>
                </div>
                <div class="worker-cmd-result" id="worker-cmd-result-${worker.id}"></div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<p class="error">Error loading workers: ${escapeHtml(error.message)}</p>`;
    }
}

async function sendWorkerCmd(workerId, command) {
    const resultDiv = document.getElementById(`worker-cmd-result-${workerId}`);
    resultDiv.innerHTML = '<span class="loading">Sending command...</span>';

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
        resultDiv.innerHTML = `<span class="error">Error: ${escapeHtml(error.message)}</span>`;
    }
}

async function provisionWorkerDialog(workerId) {
    const pathA = prompt('Enter new Path A prefix (leave empty to keep current):');
    const pathB = prompt('Enter new Path B prefix (leave empty to keep current):');
    const pathC = prompt('Enter new Path C prefix (leave empty to keep current):');

    if (!pathA && !pathB && !pathC) {
        alert('No changes specified');
        return;
    }

    const config = {};
    if (pathA) config.path_a_prefix = pathA;
    if (pathB) config.path_b_prefix = pathB;
    if (pathC) config.path_c_prefix = pathC;

    const resultDiv = document.getElementById(`worker-cmd-result-${workerId}`);
    resultDiv.innerHTML = '<span class="loading">Provisioning worker...</span>';

    try {
        await apiRequest(`/api/admin/workers/${workerId}/provision`, {
            method: 'POST',
            body: JSON.stringify({ config, restart_required: false })
        });
        resultDiv.innerHTML = '<span class="success">Worker provisioned successfully</span>';
        await loadWorkerControlList();
    } catch (error) {
        resultDiv.innerHTML = `<span class="error">Error: ${escapeHtml(error.message)}</span>`;
    }
}

// =========================================================================
// Logs Management
// =========================================================================

function setupLogEvents() {
    document.getElementById('refresh-logs-btn').addEventListener('click', () => loadLogs(false));
    document.getElementById('load-more-logs').addEventListener('click', () => loadLogs(true));
    document.getElementById('log-level-filter').addEventListener('change', () => loadLogs(false));

    let searchTimeout;
    document.getElementById('log-search').addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => loadLogs(false), 500);
    });

    document.getElementById('export-logs-btn').addEventListener('click', async () => {
        try {
            const response = await apiRequest('/api/admin/logs/stream?offset=0&limit=10000');
            const json = JSON.stringify(response.logs || [], null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `audit-logs-${new Date().toISOString()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            alert('Error exporting logs: ' + error.message);
        }
    });
}

async function loadLogs(append = false) {
    const tbody = document.getElementById('logs-table-body');
    const loading = document.getElementById('logs-loading');

    if (!append) {
        logsOffset = 0;
        tbody.innerHTML = '';
    }

    loading.classList.remove('hidden');

    try {
        const level = document.getElementById('log-level-filter')?.value;
        const search = document.getElementById('log-search')?.value;

        const params = new URLSearchParams();
        if (level) params.append('level', level);
        if (search) params.append('search_query', search);
        params.append('offset', logsOffset);
        params.append('limit', logsLimit);

        const response = await apiRequest(`/api/admin/logs/stream?${params.toString()}`);

        if (!response || !response.logs) {
            throw new Error('Invalid response from server');
        }

        const logs = response.logs;

        if (logs.length === 0 && !append) {
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

        logsOffset += logs.length;

        const paginationInfo = document.getElementById('logs-pagination-info');
        if (paginationInfo) {
            paginationInfo.textContent = `Showing ${response.offset + 1} to ${response.offset + logs.length} of ${response.total_count}`;
        }

        if (!response.has_more) {
            document.getElementById('load-more-logs').style.display = 'none';
        } else {
            document.getElementById('load-more-logs').style.display = 'block';
        }

    } catch (error) {
        console.error('Failed to load logs:', error);
        tbody.innerHTML = '<tr><td colspan="8" class="error">Error loading logs: ' + escapeHtml(error.message) + '</td></tr>';
    } finally {
        loading.classList.add('hidden');
    }
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
