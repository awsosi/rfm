/**
 * Admin Panel JavaScript Module
 *
 * Handles all admin panel functionality:
 * - User management (CRUD)
 * - Worker management (approve, suspend, update)
 * - System configuration
 * - Audit logs viewing
 */

import { API } from './api.js';
import { showNotification, formatDate } from './utils.js';

export class AdminPanel {
    constructor() {
        this.currentTab = 'users';
        this.config = {};
        this.configKeyMapping = {};
        this.init();
    }

    /**
     * Initialize admin panel
     */
    init() {
        this.setupTabSwitching();
        this.setupEventListeners();
        this.loadInitialData();
    }

    /**
     * Setup tab switching
     */
    setupTabSwitching() {
        const tabButtons = document.querySelectorAll('.tab-btn');
        const tabPanes = document.querySelectorAll('.tab-pane');

        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const tabName = button.dataset.tab;

                // Update active states
                tabButtons.forEach(btn => btn.classList.remove('active'));
                tabPanes.forEach(pane => pane.classList.remove('active'));

                button.classList.add('active');
                document.getElementById(`tab-${tabName}`).classList.add('active');

                this.currentTab = tabName;

                // Load tab data
                this.loadTabData(tabName);
            });
        });
    }

    /**
     * Setup event listeners for buttons and forms
     */
    setupEventListeners() {
        // User management
        const addUserBtn = document.getElementById('add-user-btn');
        if (addUserBtn) {
            addUserBtn.addEventListener('click', () => this.showUserModal());
        }

        const userForm = document.getElementById('user-form');
        if (userForm) {
            userForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.saveUser();
            });
        }

        const userModalClose = document.getElementById('user-modal-close');
        if (userModalClose) {
            userModalClose.addEventListener('click', () => this.hideUserModal());
        }

        // Worker management
        const refreshWorkersBtn = document.getElementById('refresh-workers-btn');
        if (refreshWorkersBtn) {
            refreshWorkersBtn.addEventListener('click', () => this.loadWorkers());
        }

        // Configuration
        const saveConfigBtn = document.getElementById('save-config-btn');
        if (saveConfigBtn) {
            saveConfigBtn.addEventListener('click', () => this.saveConfiguration());
        }

        // Logs
        const refreshLogsBtn = document.getElementById('refresh-logs-btn');
        if (refreshLogsBtn) {
            refreshLogsBtn.addEventListener('click', () => this.loadLogs());
        }

        const loadMoreLogsBtn = document.getElementById('load-more-logs');
        if (loadMoreLogsBtn) {
            loadMoreLogsBtn.addEventListener('click', () => this.loadMoreLogs());
        }

        const exportLogsBtn = document.getElementById('export-logs-btn');
        if (exportLogsBtn) {
            exportLogsBtn.addEventListener('click', () => this.exportLogs());
        }

        // Log filters
        const logLevelFilter = document.getElementById('log-level-filter');
        if (logLevelFilter) {
            logLevelFilter.addEventListener('change', () => this.loadLogs());
        }

        const logTypeFilter = document.getElementById('log-type-filter');
        if (logTypeFilter) {
            logTypeFilter.addEventListener('change', () => this.loadLogs());
        }

        const logSearch = document.getElementById('log-search');
        if (logSearch) {
            logSearch.addEventListener('input', debounce(() => this.loadLogs(), 500));
        }

        // Logging configuration
        const saveLogConfigBtn = document.getElementById('save-log-config-btn');
        if (saveLogConfigBtn) {
            saveLogConfigBtn.addEventListener('click', () => this.saveLogConfiguration());
        }
    }

    /**
     * Load initial data for the current tab
     */
    loadInitialData() {
        this.loadTabData(this.currentTab);
    }

    /**
     * Load data for specific tab
     */
    loadTabData(tabName) {
        switch (tabName) {
            case 'users':
                this.loadUsers();
                break;
            case 'workers':
                this.loadWorkers();
                break;
            case 'config':
                this.loadConfiguration();
                break;
            case 'logs':
                this.loadLogConfiguration();
                this.loadLogs();
                break;
        }
    }

    // =========================================================================
    // User Management
    // =========================================================================

    /**
     * Load all users
     */
    async loadUsers() {
        const loadingIndicator = document.getElementById('users-loading');
        const tableBody = document.getElementById('users-table-body');

        try {
            if (loadingIndicator) loadingIndicator.classList.remove('hidden');

            const users = await API.get('/api/admin/users');

            if (tableBody) {
                tableBody.innerHTML = users.map(user => `
                    <tr>
                        <td>${user.id}</td>
                        <td>${escapeHtml(user.username)}</td>
                        <td><span class="badge badge-${user.role.toLowerCase()}">${user.role}</span></td>
                        <td><span class="badge ${user.is_active ? 'badge-success' : 'badge-danger'}">${user.is_active ? 'Active' : 'Inactive'}</span></td>
                        <td>${formatDate(user.created_at)}</td>
                        <td>
                            <button class="btn btn-sm btn-secondary" onclick="adminPanel.editUser(${user.id})">Edit</button>
                            <button class="btn btn-sm btn-danger" onclick="adminPanel.deleteUser(${user.id}, '${escapeHtml(user.username)}')">Delete</button>
                        </td>
                    </tr>
                `).join('');
            }
        } catch (error) {
            console.error('Failed to load users:', error);
            showNotification('Failed to load users', 'error');
        } finally {
            if (loadingIndicator) loadingIndicator.classList.add('hidden');
        }
    }

    /**
     * Show user modal for add/edit
     */
    showUserModal(userId = null) {
        const modal = document.getElementById('user-modal');
        const modalTitle = document.getElementById('user-modal-title');
        const form = document.getElementById('user-form');

        if (userId) {
            modalTitle.textContent = 'Edit User';
            // Load user data
            this.loadUserForEdit(userId);
        } else {
            modalTitle.textContent = 'Add User';
            form.reset();
            document.getElementById('user-id').value = '';
        }

        modal.classList.remove('hidden');
    }

    /**
     * Hide user modal
     */
    hideUserModal() {
        const modal = document.getElementById('user-modal');
        modal.classList.add('hidden');
    }

    /**
     * Load user data for editing
     */
    async loadUserForEdit(userId) {
        try {
            const users = await API.get('/api/admin/users');
            const user = users.find(u => u.id === userId);

            if (user) {
                document.getElementById('user-id').value = user.id;
                document.getElementById('user-username').value = user.username;
                document.getElementById('user-password').value = '';
                document.getElementById('user-role').value = user.role.toLowerCase();
                document.getElementById('user-active').checked = user.is_active;
            }
        } catch (error) {
            console.error('Failed to load user:', error);
            showNotification('Failed to load user data', 'error');
        }
    }

    /**
     * Edit user
     */
    editUser(userId) {
        this.showUserModal(userId);
    }

    /**
     * Save user (create or update)
     */
    async saveUser() {
        const userId = document.getElementById('user-id').value;
        const username = document.getElementById('user-username').value;
        const password = document.getElementById('user-password').value;
        const role = document.getElementById('user-role').value.toUpperCase();
        const isActive = document.getElementById('user-active').checked;

        try {
            if (userId) {
                // Update existing user
                const updateData = {
                    role: role,
                    is_active: isActive
                };

                if (password) {
                    updateData.password = password;
                }

                await API.put(`/api/admin/users/${userId}`, updateData);
                showNotification('User updated successfully', 'success');
            } else {
                // Create new user
                if (!password) {
                    showNotification('Password is required for new users', 'error');
                    return;
                }

                await API.post('/api/admin/users', {
                    username: username,
                    password: password,
                    role: role
                });
                showNotification('User created successfully', 'success');
            }

            this.hideUserModal();
            this.loadUsers();
        } catch (error) {
            console.error('Failed to save user:', error);
            showNotification(error.message || 'Failed to save user', 'error');
        }
    }

    /**
     * Delete user
     */
    async deleteUser(userId, username) {
        if (!confirm(`Are you sure you want to delete user "${username}"?`)) {
            return;
        }

        try {
            await API.delete(`/api/admin/users/${userId}`);
            showNotification('User deleted successfully', 'success');
            this.loadUsers();
        } catch (error) {
            console.error('Failed to delete user:', error);
            showNotification(error.message || 'Failed to delete user', 'error');
        }
    }

    // =========================================================================
    // Worker Management
    // =========================================================================

    /**
     * Load all workers
     */
    async loadWorkers() {
        const loadingIndicator = document.getElementById('workers-loading');
        const tableBody = document.getElementById('workers-table-body');
        const pendingTableBody = document.getElementById('pending-workers-table-body');

        try {
            if (loadingIndicator) loadingIndicator.classList.remove('hidden');

            const workers = await API.get('/api/admin/workers?include_pending=true');

            const activeWorkers = workers.filter(w => w.status !== 'PENDING');
            const pendingWorkers = workers.filter(w => w.status === 'PENDING');

            // Populate active workers table
            if (tableBody) {
                tableBody.innerHTML = activeWorkers.map(worker => `
                    <tr>
                        <td>${worker.id}</td>
                        <td>${escapeHtml(worker.hostname || 'N/A')}</td>
                        <td><span class="badge badge-${worker.status.toLowerCase()}">${worker.status}</span></td>
                        <td>${worker.last_heartbeat ? formatDate(worker.last_heartbeat) : 'Never'}</td>
                        <td>
                            <small>A: ${escapeHtml(worker.path_a_prefix || 'Not set')}<br>
                            B: ${escapeHtml(worker.path_b_prefix || 'Not set')}</small>
                        </td>
                        <td>
                            ${worker.status === 'ACTIVE' ?
                                `<button class="btn btn-sm btn-warning" onclick="adminPanel.suspendWorker(${worker.id})">Suspend</button>` :
                                `<button class="btn btn-sm btn-success" onclick="adminPanel.activateWorker(${worker.id})">Activate</button>`
                            }
                            <button class="btn btn-sm btn-danger" onclick="adminPanel.deleteWorker(${worker.id}, '${escapeHtml(worker.name)}')">Delete</button>
                        </td>
                    </tr>
                `).join('');
            }

            // Populate pending workers table
            if (pendingTableBody) {
                if (pendingWorkers.length === 0) {
                    pendingTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">No pending approvals</td></tr>';
                } else {
                    pendingTableBody.innerHTML = pendingWorkers.map(worker => `
                        <tr>
                            <td>${worker.id}</td>
                            <td>${escapeHtml(worker.hostname || 'N/A')}</td>
                            <td>${formatDate(worker.created_at)}</td>
                            <td>
                                <button class="btn btn-sm btn-success" onclick="adminPanel.approveWorker(${worker.id})">Approve</button>
                                <button class="btn btn-sm btn-danger" onclick="adminPanel.deleteWorker(${worker.id}, '${escapeHtml(worker.name)}')">Reject</button>
                            </td>
                        </tr>
                    `).join('');
                }
            }
        } catch (error) {
            console.error('Failed to load workers:', error);
            showNotification('Failed to load workers', 'error');
        } finally {
            if (loadingIndicator) loadingIndicator.classList.add('hidden');
        }
    }

    /**
     * Approve pending worker
     */
    async approveWorker(workerId) {
        try {
            await API.post(`/api/admin/workers/${workerId}/approve`);
            showNotification('Worker approved successfully', 'success');
            this.loadWorkers();
        } catch (error) {
            console.error('Failed to approve worker:', error);
            showNotification(error.message || 'Failed to approve worker', 'error');
        }
    }

    /**
     * Suspend worker
     */
    async suspendWorker(workerId) {
        try {
            await API.post(`/api/admin/workers/${workerId}/suspend`);
            showNotification('Worker suspended successfully', 'success');
            this.loadWorkers();
        } catch (error) {
            console.error('Failed to suspend worker:', error);
            showNotification(error.message || 'Failed to suspend worker', 'error');
        }
    }

    /**
     * Activate worker (change from SUSPENDED to ACTIVE)
     */
    async activateWorker(workerId) {
        try {
            await API.put(`/api/admin/workers/${workerId}`, { status: 'ACTIVE' });
            showNotification('Worker activated successfully', 'success');
            this.loadWorkers();
        } catch (error) {
            console.error('Failed to activate worker:', error);
            showNotification(error.message || 'Failed to activate worker', 'error');
        }
    }

    /**
     * Delete worker
     */
    async deleteWorker(workerId, workerName) {
        if (!confirm(`Are you sure you want to delete worker "${workerName}"?`)) {
            return;
        }

        try {
            await API.delete(`/api/admin/workers/${workerId}`);
            showNotification('Worker deleted successfully', 'success');
            this.loadWorkers();
        } catch (error) {
            console.error('Failed to delete worker:', error);
            showNotification(error.message || 'Failed to delete worker', 'error');
        }
    }

    // =========================================================================
    // Configuration Management
    // =========================================================================

    /**
     * Load system configuration
     */
    async loadConfiguration() {
        try {
            const configs = await API.get('/api/admin/config');

            // Store configs in object for easy access
            this.config = {};
            configs.forEach(cfg => {
                this.config[cfg.key] = cfg;
            });

            // Populate form fields
            this.populateConfigForm();
        } catch (error) {
            console.error('Failed to load configuration:', error);
            showNotification('Failed to load configuration', 'error');
        }
    }

    /**
     * Populate configuration form with current values
     */
    populateConfigForm() {
        // Map form field names to config keys
        const fieldMapping = {
            'max_concurrent_users': 'max_concurrent_users',
            'session_lifetime_days': 'session_lifetime_days',
            'enable_sybase_auth': 'enable_sybase_auth',
            'sybase_auth_url': 'sybase_auth_url',
            'sybase_auth_timeout': 'sybase_auth_timeout',
            'sybase_auth_stored_proc': 'sybase_auth_stored_proc',
            'log_retention_days': 'log_retention_days',
            'enable_log_compression': 'enable_log_compression',
            'enable_syslog': 'enable_syslog',
            'syslog_host': 'syslog_host',
            'syslog_port': 'syslog_port',
            'syslog_protocol': 'syslog_protocol',
            'enable_remote_audit_api': 'enable_remote_audit_api',
            'remote_audit_api_url': 'remote_audit_api_url',
            'remote_audit_api_token': 'remote_audit_api_token',
            'remote_audit_api_timeout': 'remote_audit_api_timeout',
            'global_path_a_prefix': 'global_path_a_prefix',
            'global_path_b_prefix': 'global_path_b_prefix',
            'worker_heartbeat_interval': 'worker_heartbeat_interval',
            'worker_heartbeat_timeout': 'worker_heartbeat_timeout',
            'worker_timeout': 'worker_timeout',
            'worker_retry_attempts': 'worker_retry_attempts',
            'operation_timeout': 'operation_timeout',
            'enable_auto_rollback': 'enable_auto_rollback',
            'max_file_listing_items': 'max_file_listing_items',
            'enable_lazy_loading': 'enable_lazy_loading',
            'enable_ip_whitelist': 'enable_ip_whitelist',
            'ip_whitelist': 'ip_whitelist',
            'enable_rate_limiting': 'enable_rate_limiting',
            'rate_limit_requests_per_minute': 'rate_limit_requests_per_minute',
            'maintenance_mode': 'maintenance_mode',
            'maintenance_message': 'maintenance_message'
        };

        Object.entries(fieldMapping).forEach(([fieldName, configKey]) => {
            const element = document.querySelector(`[name="${fieldName}"]`);
            if (!element || !this.config[configKey]) return;

            const config = this.config[configKey];
            const value = config.type === 'BOOLEAN'
                ? config.value.toLowerCase() === 'true'
                : config.value;

            if (element.type === 'checkbox') {
                element.checked = value;
            } else if (element.tagName === 'TEXTAREA') {
                element.value = value || '';
            } else {
                element.value = value || '';
            }
        });
    }

    /**
     * Save system configuration
     */
    async saveConfiguration() {
        const form = document.getElementById('config-form');
        const formData = new FormData(form);

        // Build config updates object
        const updates = {};

        for (const [fieldName, value] of formData.entries()) {
            // Find corresponding config key
            const configKey = fieldName;

            // Handle different input types
            const element = document.querySelector(`[name="${fieldName}"]`);
            if (element.type === 'checkbox') {
                updates[configKey] = element.checked ? 'true' : 'false';
            } else {
                updates[configKey] = value;
            }
        }

        // Also handle unchecked checkboxes (they don't appear in FormData)
        const allCheckboxes = form.querySelectorAll('input[type="checkbox"]');
        allCheckboxes.forEach(checkbox => {
            const fieldName = checkbox.name;
            if (!updates.hasOwnProperty(fieldName)) {
                updates[fieldName] = 'false';
            }
        });

        try {
            await API.post('/api/admin/config/bulk', { configs: updates });
            showNotification('Configuration saved successfully', 'success');
            this.loadConfiguration(); // Reload to confirm
        } catch (error) {
            console.error('Failed to save configuration:', error);
            showNotification(error.message || 'Failed to save configuration', 'error');
        }
    }

    // =========================================================================
    // Logs Management
    // =========================================================================

    /**
     * Load logging configuration
     */
    async loadLogConfiguration() {
        try {
            const config = await API.get('/api/admin/logs/config');

            // Populate form
            const syslogEnabled = document.getElementById('log-config-syslog-enabled');
            if (syslogEnabled) syslogEnabled.checked = config.enable_syslog || false;

            const syslogHost = document.getElementById('log-config-syslog-host');
            if (syslogHost) syslogHost.value = config.syslog_host || '';

            const syslogPort = document.getElementById('log-config-syslog-port');
            if (syslogPort) syslogPort.value = config.syslog_port || 514;

            const syslogProtocol = document.getElementById('log-config-syslog-protocol');
            if (syslogProtocol) syslogProtocol.value = config.syslog_protocol || 'UDP';

            const retention = document.getElementById('log-config-retention');
            if (retention) retention.value = config.log_retention_days || 14;

            const compression = document.getElementById('log-config-compression');
            if (compression) compression.checked = config.enable_log_compression !== false;

        } catch (error) {
            console.error('Failed to load log configuration:', error);
        }
    }

    /**
     * Save logging configuration
     */
    async saveLogConfiguration() {
        try {
            const configs = [
                {
                    key: 'enable_syslog',
                    value: document.getElementById('log-config-syslog-enabled')?.checked ? 'true' : 'false',
                    type: 'BOOLEAN'
                },
                {
                    key: 'syslog_host',
                    value: document.getElementById('log-config-syslog-host')?.value || '',
                    type: 'STRING'
                },
                {
                    key: 'syslog_port',
                    value: document.getElementById('log-config-syslog-port')?.value || '514',
                    type: 'INT'
                },
                {
                    key: 'syslog_protocol',
                    value: document.getElementById('log-config-syslog-protocol')?.value || 'UDP',
                    type: 'STRING'
                },
                {
                    key: 'log_retention_days',
                    value: document.getElementById('log-config-retention')?.value || '14',
                    type: 'INT'
                },
                {
                    key: 'enable_log_compression',
                    value: document.getElementById('log-config-compression')?.checked ? 'true' : 'false',
                    type: 'BOOLEAN'
                }
            ];

            await API.post('/api/admin/config/bulk', { configs });
            showNotification('Logging configuration saved successfully', 'success');
        } catch (error) {
            console.error('Failed to save log configuration:', error);
            showNotification('Error saving log configuration: ' + error.message, 'error');
        }
    }

    /**
     * Load audit logs or application logs based on selected type
     */
    async loadLogs(offset = 0, limit = 100) {
        const loadingIndicator = document.getElementById('logs-loading');
        const logEntries = document.getElementById('log-entries');
        const logTypeFilter = document.getElementById('log-type-filter');
        const logLevelFilter = document.getElementById('log-level-filter');
        const logSearch = document.getElementById('log-search');

        const logType = logTypeFilter?.value || 'audit';
        const level = logLevelFilter?.value || '';
        const search = logSearch?.value || '';

        try {
            if (loadingIndicator) loadingIndicator.classList.remove('hidden');

            let logs = [];

            if (logType === 'application') {
                // Load application logs from file
                let url = `/api/admin/logs/application?offset=${offset}&limit=${limit}`;
                if (level) url += `&level=${level}`;
                if (search) url += `&search=${encodeURIComponent(search)}`;

                const response = await API.get(url);
                logs = response.logs || [];

                if (logEntries) {
                    if (offset === 0) {
                        logEntries.innerHTML = '';
                    }

                    if (logs.length === 0 && offset === 0) {
                        logEntries.innerHTML = '<div class="no-logs">No application logs found. Enable file logging in environment to view application logs.</div>';
                    }

                    logs.forEach(log => {
                        const logEntry = document.createElement('div');
                        logEntry.className = `log-entry log-level-${log.level.toLowerCase()}`;
                        logEntry.innerHTML = `
                            <div class="log-header">
                                <span class="log-timestamp">${formatDate(log.timestamp)}</span>
                                <span class="log-level badge badge-${log.level.toLowerCase()}">${log.level}</span>
                                ${log.logger ? `<span class="log-logger">${escapeHtml(log.logger)}</span>` : ''}
                            </div>
                            <div class="log-message">${escapeHtml(log.message)}</div>
                            ${log.extra ? `<div class="log-details"><pre>${escapeHtml(JSON.stringify(log.extra, null, 2))}</pre></div>` : ''}
                        `;
                        logEntries.appendChild(logEntry);
                    });
                }
            } else {
                // Load audit logs from database
                const response = await API.get(`/api/admin/logs/stream?offset=${offset}&limit=${limit}`);
                logs = response.logs || [];

                if (logEntries) {
                    if (offset === 0) {
                        logEntries.innerHTML = '';
                    }

                    if (logs.length === 0 && offset === 0) {
                        logEntries.innerHTML = '<div class="no-logs">No audit logs found.</div>';
                    }

                    logs.forEach(log => {
                        const logEntry = document.createElement('div');
                        logEntry.className = 'log-entry';
                        logEntry.innerHTML = `
                            <div class="log-header">
                                <span class="log-timestamp">${formatDate(log.timestamp)}</span>
                                <span class="log-action">${escapeHtml(log.action)}</span>
                                ${log.username ? `<span class="log-user">${escapeHtml(log.username)}</span>` : (log.user_id ? `<span class="log-user">User ID: ${log.user_id}</span>` : '')}
                            </div>
                            <div class="log-details">
                                ${log.details ? `<pre>${escapeHtml(JSON.stringify(log.details, null, 2))}</pre>` : ''}
                            </div>
                            <div class="log-meta">
                                ${log.ip_address ? `<span>IP: ${escapeHtml(log.ip_address)}</span>` : ''}
                            </div>
                        `;
                        logEntries.appendChild(logEntry);
                    });
                }
            }
        } catch (error) {
            console.error('Failed to load logs:', error);
            showNotification('Error loading logs: ' + error.message, 'error');
        } finally {
            if (loadingIndicator) loadingIndicator.classList.add('hidden');
        }
    }

    /**
     * Load more logs (pagination)
     */
    loadMoreLogs() {
        const currentCount = document.querySelectorAll('.log-entry').length;
        this.loadLogs(currentCount, 100);
    }

    /**
     * Export logs to file
     */
    async exportLogs() {
        try {
            const logs = await API.get('/api/admin/logs?offset=0&limit=10000');
            const json = JSON.stringify(logs, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `audit-logs-${new Date().toISOString()}.json`;
            a.click();
            URL.revokeObjectURL(url);
            showNotification('Logs exported successfully', 'success');
        } catch (error) {
            console.error('Failed to export logs:', error);
            showNotification('Failed to export logs', 'error');
        }
    }
}

// =========================================================================
// Utility Functions
// =========================================================================

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Debounce function
 */
function debounce(func, wait) {
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

// Initialize admin panel when DOM is ready
let adminPanel;
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        adminPanel = new AdminPanel();
        window.adminPanel = adminPanel; // Make globally accessible
    });
} else {
    adminPanel = new AdminPanel();
    window.adminPanel = adminPanel;
}

export default AdminPanel;
