/**
 * Admin System Management Module
 *
 * Handles:
 * - Samba paths management
 * - Worker provisioning and real-time control
 * - System monitoring and statistics
 * - Real-time log viewing with WebSocket
 */

class AdminSystem {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.websocket = null;
        this.wsReconnectInterval = null;
        this.statsRefreshInterval = null;
    }

    // =============================================================================
    // Samba Paths Management
    // =============================================================================

    async loadSambaPaths() {
        try {
            const response = await this.apiClient.get('/api/admin/samba-paths');
            this.renderSambaPaths(response);
        } catch (error) {
            this.showError('Failed to load Samba paths', error);
        }
    }

    renderSambaPaths(paths) {
        const tbody = document.getElementById('samba-paths-table-body');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (paths.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="no-data">No Samba paths configured</td></tr>';
            return;
        }

        paths.forEach(path => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${path.id}</td>
                <td>${this.escapeHtml(path.name)}</td>
                <td><code>${this.escapeHtml(path.path_prefix)}</code></td>
                <td>${this.escapeHtml(path.share_type || 'smb')}</td>
                <td><span class="badge ${path.is_active ? 'badge-success' : 'badge-danger'}">${path.is_active ? 'Active' : 'Inactive'}</span></td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="adminSystem.editSambaPath(${path.id})">Edit</button>
                    <button class="btn btn-sm btn-danger" onclick="adminSystem.deleteSambaPath(${path.id}, '${this.escapeHtml(path.name)}')">Delete</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    async createSambaPath() {
        const name = prompt('Enter Samba path name:');
        if (!name) return;

        const pathPrefix = prompt('Enter path prefix (e.g., \\\\server\\share):');
        if (!pathPrefix) return;

        const description = prompt('Enter description (optional):');

        try {
            await this.apiClient.post('/api/admin/samba-paths', {
                name,
                path_prefix: pathPrefix,
                description: description || null,
                is_active: true,
                share_type: 'smb',
                requires_auth: true
            });

            this.showSuccess('Samba path created successfully');
            await this.loadSambaPaths();
        } catch (error) {
            this.showError('Failed to create Samba path', error);
        }
    }

    async editSambaPath(pathId) {
        // TODO: Show modal with form for editing
        const newName = prompt('Enter new name (or cancel to skip):');
        if (!newName) return;

        try {
            await this.apiClient.put(`/api/admin/samba-paths/${pathId}`, {
                name: newName
            });

            this.showSuccess('Samba path updated successfully');
            await this.loadSambaPaths();
        } catch (error) {
            this.showError('Failed to update Samba path', error);
        }
    }

    async deleteSambaPath(pathId, pathName) {
        if (!confirm(`Are you sure you want to delete Samba path '${pathName}'?`)) {
            return;
        }

        try {
            await this.apiClient.delete(`/api/admin/samba-paths/${pathId}`);
            this.showSuccess('Samba path deleted successfully');
            await this.loadSambaPaths();
        } catch (error) {
            this.showError('Failed to delete Samba path', error);
        }
    }

    // =============================================================================
    // Worker Management & Provisioning
    // =============================================================================

    async loadWorkerStatus(workerId) {
        try {
            const status = await this.apiClient.get(`/api/admin/workers/${workerId}/status`);
            this.renderWorkerStatus(status);
        } catch (error) {
            this.showError('Failed to load worker status', error);
        }
    }

    renderWorkerStatus(status) {
        const container = document.getElementById('worker-status-detail');
        if (!container) return;

        const healthBadge = status.is_healthy
            ? '<span class="badge badge-success">Healthy</span>'
            : '<span class="badge badge-danger">Unhealthy</span>';

        container.innerHTML = `
            <div class="worker-status-card">
                <h3>${this.escapeHtml(status.worker_name)} ${healthBadge}</h3>
                <div class="status-grid">
                    <div class="status-item">
                        <label>Hostname:</label>
                        <span>${this.escapeHtml(status.hostname)}</span>
                    </div>
                    <div class="status-item">
                        <label>Status:</label>
                        <span class="badge ${this.getWorkerStatusClass(status.status)}">${status.status}</span>
                    </div>
                    <div class="status-item">
                        <label>Last Heartbeat:</label>
                        <span>${status.last_heartbeat ? new Date(status.last_heartbeat).toLocaleString() : 'Never'}</span>
                    </div>
                    <div class="status-item">
                        <label>Uptime:</label>
                        <span>${status.uptime_seconds ? this.formatUptime(status.uptime_seconds) : 'N/A'}</span>
                    </div>
                    <div class="status-item">
                        <label>Operations Processed:</label>
                        <span>${status.operations_processed || 0}</span>
                    </div>
                    <div class="status-item">
                        <label>Queue Size:</label>
                        <span>${status.operations_in_queue || 0}</span>
                    </div>
                    ${status.cpu_usage_percent !== undefined ? `
                    <div class="status-item">
                        <label>CPU Usage:</label>
                        <span>${status.cpu_usage_percent.toFixed(1)}%</span>
                    </div>
                    ` : ''}
                    ${status.memory_usage_mb !== undefined ? `
                    <div class="status-item">
                        <label>Memory Usage:</label>
                        <span>${status.memory_usage_mb.toFixed(0)} MB</span>
                    </div>
                    ` : ''}
                    ${status.disk_free_gb !== undefined ? `
                    <div class="status-item">
                        <label>Disk Free:</label>
                        <span>${status.disk_free_gb.toFixed(1)} GB</span>
                    </div>
                    ` : ''}
                </div>
                ${status.health_issues.length > 0 ? `
                <div class="health-issues">
                    <h4>Health Issues:</h4>
                    <ul>
                        ${status.health_issues.map(issue => `<li>${this.escapeHtml(issue)}</li>`).join('')}
                    </ul>
                </div>
                ` : ''}
                ${status.current_config ? `
                <div class="current-config">
                    <h4>Current Configuration:</h4>
                    <pre>${JSON.stringify(status.current_config, null, 2)}</pre>
                </div>
                ` : ''}
            </div>
        `;
    }

    async sendWorkerCommand(workerId, command, params = {}) {
        try {
            const response = await this.apiClient.post(`/api/admin/workers/${workerId}/command`, {
                command,
                params,
                timeout_seconds: 30
            });

            this.showSuccess(`Command '${command}' sent successfully (${response.duration_ms}ms): ${response.message}`);
            return response;
        } catch (error) {
            this.showError(`Failed to send command '${command}'`, error);
            return null;
        }
    }

    async provisionWorker(workerId) {
        const pathA = prompt('Enter Path A prefix (or leave empty to skip):');
        const pathB = prompt('Enter Path B prefix (or leave empty to skip):');

        if (!pathA && !pathB) {
            alert('No changes specified');
            return;
        }

        const config = {};
        if (pathA) config.path_a_prefix = pathA;
        if (pathB) config.path_b_prefix = pathB;

        try {
            await this.apiClient.post(`/api/admin/workers/${workerId}/provision`, {
                config,
                restart_required: false
            });

            this.showSuccess('Worker provisioned successfully');
        } catch (error) {
            this.showError('Failed to provision worker', error);
        }
    }

    // =============================================================================
    // System Statistics & Monitoring
    // =============================================================================

    async loadSystemStats() {
        try {
            const stats = await this.apiClient.get('/api/admin/stats/system');
            this.renderSystemStats(stats);
        } catch (error) {
            this.showError('Failed to load system stats', error);
        }
    }

    renderSystemStats(stats) {
        const container = document.getElementById('system-stats-container');
        if (!container) return;

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
                        ${stats.database_healthy ? '✓' : '✗'} DB |
                        ${stats.redis_healthy ? '✓' : '✗'} Redis
                    </div>
                    <div class="stat-label">Components</div>
                    <div class="stat-details">
                        Samba Paths: ${stats.samba_paths_active} | Audit Logs: ${stats.total_audit_logs}
                    </div>
                </div>
            </div>
        `;
    }

    startStatsAutoRefresh(intervalMs = 5000) {
        if (this.statsRefreshInterval) {
            clearInterval(this.statsRefreshInterval);
        }

        this.statsRefreshInterval = setInterval(() => {
            this.loadSystemStats();
        }, intervalMs);
    }

    stopStatsAutoRefresh() {
        if (this.statsRefreshInterval) {
            clearInterval(this.statsRefreshInterval);
            this.statsRefreshInterval = null;
        }
    }

    // =============================================================================
    // Real-time Log Viewing
    // =============================================================================

    async loadLogs(filters = {}) {
        try {
            const params = new URLSearchParams();
            if (filters.user_id) params.append('user_id', filters.user_id);
            if (filters.action) params.append('action', filters.action);
            if (filters.start_time) params.append('start_time', filters.start_time);
            if (filters.end_time) params.append('end_time', filters.end_time);
            params.append('offset', filters.offset || 0);
            params.append('limit', filters.limit || 100);

            const response = await this.apiClient.get(`/api/admin/logs/stream?${params}`);
            this.renderLogs(response);
        } catch (error) {
            this.showError('Failed to load logs', error);
        }
    }

    renderLogs(response) {
        const tbody = document.getElementById('logs-table-body');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (response.logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="no-data">No logs found</td></tr>';
            return;
        }

        response.logs.forEach(log => {
            // Extract source and target directories from details_json for push/pull operations
            let sourceDir = '-';
            let targetDir = '-';

            if (log.details && (log.action === 'push' || log.action === 'pull')) {
                if (log.details.source_directory) {
                    sourceDir = log.details.source_directory;
                }
                if (log.details.target_directory) {
                    targetDir = log.details.target_directory;
                }
            }

            // Format timestamp as relative time
            const timestamp = this.formatRelativeTime(log.timestamp);

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${timestamp}</td>
                <td>${this.escapeHtml(log.action)}</td>
                <td>${this.escapeHtml(sourceDir)}</td>
                <td>${this.escapeHtml(targetDir)}</td>
                <td>${log.user_id || '-'}</td>
                <td>${this.escapeHtml(log.username || 'System')}</td>
                <td>${log.ip_address || 'N/A'}</td>
            `;
            tbody.appendChild(tr);
        });

        // Update pagination info
        const paginationInfo = document.getElementById('logs-pagination-info');
        if (paginationInfo) {
            paginationInfo.textContent = `Showing ${response.offset + 1} to ${response.offset + response.logs.length} of ${response.total_count}`;
        }
    }

    showLogDetails(logId) {
        // TODO: Show modal with full log details
        alert(`Log details for ID ${logId} - implement modal`);
    }

    // =============================================================================
    // WebSocket Real-time Updates
    // =============================================================================

    connectWebSocket() {
        const token = localStorage.getItem('access_token');
        if (!token) {
            console.error('No access token available for WebSocket');
            return;
        }

        const wsUrl = `ws://${window.location.host}/ws/realtime?token=${token}`;

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = () => {
            console.log('WebSocket connected');
            this.showSuccess('Real-time updates connected');

            // Subscribe to topics
            this.websocket.send(JSON.stringify({ type: 'subscribe', topic: 'operations' }));
            this.websocket.send(JSON.stringify({ type: 'subscribe', topic: 'workers' }));
            this.websocket.send(JSON.stringify({ type: 'subscribe', topic: 'alerts' }));
            this.websocket.send(JSON.stringify({ type: 'subscribe', topic: 'logs' }));
        };

        this.websocket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (error) {
                console.error('Failed to parse WebSocket message:', error);
            }
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        this.websocket.onclose = () => {
            console.log('WebSocket disconnected');
            this.websocket = null;

            // Attempt reconnect after 5 seconds
            if (!this.wsReconnectInterval) {
                this.wsReconnectInterval = setTimeout(() => {
                    this.wsReconnectInterval = null;
                    this.connectWebSocket();
                }, 5000);
            }
        };
    }

    disconnectWebSocket() {
        if (this.wsReconnectInterval) {
            clearTimeout(this.wsReconnectInterval);
            this.wsReconnectInterval = null;
        }

        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
    }

    handleWebSocketMessage(message) {
        switch (message.event_type) {
            case 'operation_update':
                this.handleOperationUpdate(message.data);
                break;
            case 'worker_status':
                this.handleWorkerStatusUpdate(message.data);
                break;
            case 'system_alert':
                this.handleSystemAlert(message.data);
                break;
            case 'log_entry':
                this.handleLogEntry(message.data);
                break;
            case 'heartbeat':
                // Ignore heartbeat messages
                break;
            default:
                console.log('Unknown WebSocket message type:', message.event_type);
        }
    }

    handleOperationUpdate(data) {
        console.log('Operation update:', data);
        // TODO: Update UI with operation progress
    }

    handleWorkerStatusUpdate(data) {
        console.log('Worker status update:', data);
        this.showInfo(`Worker ${data.worker_name} changed from ${data.old_status} to ${data.new_status}`);
        // Refresh worker list if on workers tab
    }

    handleSystemAlert(data) {
        const severity = data.severity || 'info';
        const message = `${data.title}: ${data.message}`;

        switch (severity) {
            case 'critical':
            case 'error':
                this.showError(message);
                break;
            case 'warning':
                this.showWarning(message);
                break;
            default:
                this.showInfo(message);
        }
    }

    handleLogEntry(data) {
        console.log('New log entry:', data);
        // TODO: Prepend to log table if on logs tab
    }

    // =============================================================================
    // Utility Functions
    // =============================================================================

    getWorkerStatusClass(status) {
        switch (status.toUpperCase()) {
            case 'ACTIVE': return 'badge-success';
            case 'SUSPENDED': return 'badge-warning';
            case 'PENDING': return 'badge-info';
            default: return 'badge-secondary';
        }
    }

    getLogLevelClass(level) {
        switch (level.toUpperCase()) {
            case 'ERROR': return 'badge-danger';
            case 'WARN': return 'badge-warning';
            case 'INFO': return 'badge-info';
            default: return 'badge-secondary';
        }
    }

    formatUptime(seconds) {
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);

        if (days > 0) return `${days}d ${hours}h ${minutes}m`;
        if (hours > 0) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    formatRelativeTime(timestamp) {
        if (!timestamp) return 'N/A';

        const date = new Date(timestamp);
        if (isNaN(date.getTime())) return 'Invalid date';

        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) {
            return 'Just now';
        } else if (diffMins < 60) {
            return `${diffMins} min${diffMins !== 1 ? 's' : ''} ago`;
        } else if (diffHours < 24) {
            return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        } else if (diffDays < 7) {
            return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
        }

        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    showSuccess(message) {
        console.log('SUCCESS:', message);
        // TODO: Implement toast notifications
        alert(message);
    }

    showError(message, error = null) {
        console.error('ERROR:', message, error);
        // TODO: Implement toast notifications
        alert(`Error: ${message}${error ? '\n' + error : ''}`);
    }

    showWarning(message) {
        console.warn('WARNING:', message);
        // TODO: Implement toast notifications
    }

    showInfo(message) {
        console.info('INFO:', message);
        // TODO: Implement toast notifications
    }
}

// Export for use in admin page
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AdminSystem;
}

export default AdminSystem;
