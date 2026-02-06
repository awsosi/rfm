/**
 * Admin System Management Module
 *
 * Handles:
 * - Worker provisioning and real-time control
 * - System monitoring and statistics
 * - Real-time log viewing with WebSocket
 */

class AdminSystem {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.websocket = null;
        this.wsReconnectInterval = null;
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
                        ${stats.database_healthy ? '&#10003;' : '&#10007;'} DB
                    </div>
                    <div class="stat-label">Components</div>
                    <div class="stat-details">
                        Audit Logs: ${stats.total_audit_logs}
                    </div>
                </div>
            </div>
        `;
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
            tbody.innerHTML = '<tr><td colspan="8" class="no-data">No logs found</td></tr>';
            return;
        }

        response.logs.forEach(log => {
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

            const relativeTime = this.formatRelativeTime(log.timestamp);

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${fullTimestamp}</td>
                <td>${relativeTime}</td>
                <td>${this.escapeHtml(log.action)}</td>
                <td>${this.escapeHtml(sourceDir)}</td>
                <td>${this.escapeHtml(targetDir)}</td>
                <td>${log.user_id || '-'}</td>
                <td>${this.escapeHtml(log.username || 'System')}</td>
                <td>${log.ip_address || 'N/A'}</td>
            `;
            tbody.appendChild(tr);
        });

        const paginationInfo = document.getElementById('logs-pagination-info');
        if (paginationInfo) {
            paginationInfo.textContent = `Showing ${response.offset + 1} to ${response.offset + response.logs.length} of ${response.total_count}`;
        }
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
                console.log('Operation update:', message.data);
                break;
            case 'worker_status':
                console.log('Worker status update:', message.data);
                break;
            case 'system_alert':
                console.log('System alert:', message.data);
                break;
            case 'log_entry':
                console.log('New log entry:', message.data);
                break;
            case 'heartbeat':
                break;
            default:
                console.log('Unknown WebSocket message type:', message.event_type);
        }
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

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} min${diffMins !== 1 ? 's' : ''} ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;

        return date.toLocaleString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    showSuccess(message) {
        console.log('SUCCESS:', message);
    }

    showError(message, error = null) {
        console.error('ERROR:', message, error);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AdminSystem;
}

export default AdminSystem;
