/**
 * Manager view: operation history with precise filters, and classification
 * reports (download one now, write the monthly ones to the share, see runs).
 *
 * Needs the MANAGER or ADMIN role; the API enforces it (/api/manager/*).
 */

import { checkAuth, logout, getCurrentUser, redirectToLogin, setupAutoRefresh } from './auth.js';
import { initI18n, translatePage, t } from './i18n.js';
import { apiRequest, apiDownload } from './api.js';
import { loadAndApplyTheme } from './theme.js';
import { openOperationDetails } from './operation-details.js';
import { formatOperationStatus, formatPimDelivery, showError, showSuccess, showInfo } from './ui.js';
import { formatDateTime, showDialog, debounce } from './utils.js';

const TYPES = ['PUSH', 'PULL', 'UPDATE'];
const STATUSES = ['COMPLETED', 'FAILED', 'IN_PROGRESS', 'PENDING', 'ROLLED_BACK'];
const MANAGER_ROLES = ['MANAGER', 'ADMIN'];
const FILTERS_KEY = 'rfm.manager.filters';
const RUNS_POLL_MS = 3000;

// Columns of the history export, in order; headers come from the locale
const EXPORT_COLUMNS = [
    ['id', 'manager.columns.id'],
    ['type', 'manager.columns.type'],
    ['status', 'manager.columns.status'],
    ['catalog_name', 'manager.columns.catalog'],
    ['user_name', 'manager.columns.user'],
    ['created_at', 'manager.columns.created'],
    ['completed_at', 'manager.columns.completed'],
    ['file_count', 'manager.columns.files'],
    ['has_been_pulled', 'manager.columns.pulled'],
    ['pim_status', 'manager.columns.pim'],
    ['source_path', 'manager.columns.source'],
    ['dest_path', 'manager.columns.destination'],
    ['error_msg', 'manager.columns.error']
];

const state = {
    users: [],
    filters: defaultFilters(),
    sortBy: 'created_at',
    sortOrder: 'desc',
    offset: 0,
    limit: 50,
    total: 0,
    requestId: 0,
    reportSettings: null,
    reportUsers: new Set(),
    writeRecipients: new Set(),
    runsTimer: null
};

function defaultFilters() {
    return { q: '', period: 'last7', from: '', to: '', users: [], types: [], statuses: [], pulled: '' };
}

// =========================================================================
// Dates (the browser's local days)
// =========================================================================

function isoDay(date) {
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function addDays(date, days) {
    const copy = new Date(date);
    copy.setDate(copy.getDate() + days);
    return copy;
}

function isoMonth(date) {
    return isoDay(date).slice(0, 7);
}

/** First and last day (inclusive, yyyy-mm-dd) of a period preset. */
function periodRange(period) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    switch (period) {
        case 'today': return [isoDay(today), isoDay(today)];
        case 'yesterday': return [isoDay(addDays(today, -1)), isoDay(addDays(today, -1))];
        case 'last7': return [isoDay(addDays(today, -6)), isoDay(today)];
        case 'last30': return [isoDay(addDays(today, -29)), isoDay(today)];
        case 'thisMonth': return [isoDay(new Date(today.getFullYear(), today.getMonth(), 1)), isoDay(today)];
        case 'lastMonth': return [
            isoDay(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
            isoDay(new Date(today.getFullYear(), today.getMonth(), 0))
        ];
        default: return ['', ''];
    }
}

/** Local midnight of a yyyy-mm-dd day as an ISO timestamp with offset. */
function dayStart(day, offsetDays = 0) {
    const [y, m, d] = day.split('-').map(Number);
    return new Date(y, m - 1, d + offsetDays).toISOString();
}

function formatMonth(month) {
    const [y, m] = month.split('-').map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString(document.documentElement.lang || undefined,
        { year: 'numeric', month: 'long' });
}

// =========================================================================
// Small widgets
// =========================================================================

/**
 * A dropdown of checkboxes. ``selected`` is a Set of values that is changed
 * in place; ``onChange`` runs after every change.
 */
function multiSelect(container, options, selected, { allLabel, onChange }) {
    container.textContent = '';
    const details = document.createElement('details');
    details.className = 'multi-select-dropdown';
    const summary = document.createElement('summary');
    summary.className = 'form-control';
    const menu = document.createElement('div');
    menu.className = 'multi-select-menu';

    const updateSummary = () => {
        summary.textContent = selected.size === 0
            ? allLabel
            : selected.size === 1
                ? [...selected][0]
                : t('manager.filters.usersSelected', { count: selected.size });
    };

    const tools = document.createElement('div');
    tools.className = 'multi-select-tools';
    const toolButton = (key, apply) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-ghost btn-sm';
        button.textContent = t(key);
        button.addEventListener('click', () => {
            apply();
            menu.querySelectorAll('input[type=checkbox]').forEach(box => { box.checked = selected.has(box.value); });
            updateSummary();
            onChange();
        });
        return button;
    };
    tools.append(
        toolButton('manager.filters.selectAll', () => options.forEach(o => selected.add(o.value))),
        toolButton('manager.filters.selectNone', () => selected.clear())
    );
    menu.appendChild(tools);

    options.forEach(option => {
        const label = document.createElement('label');
        label.className = 'multi-select-option';
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.value = option.value;
        box.checked = selected.has(option.value);
        box.addEventListener('change', () => {
            if (box.checked) selected.add(option.value); else selected.delete(option.value);
            updateSummary();
            onChange();
        });
        const text = document.createElement('span');
        text.textContent = option.label;
        label.append(box, text);
        if (option.hint) {
            const hint = document.createElement('small');
            hint.className = 'text-muted';
            hint.textContent = option.hint;
            label.appendChild(hint);
        }
        menu.appendChild(label);
    });

    details.append(summary, menu);
    container.appendChild(details);
    updateSummary();
    return details;
}

/** Toggle buttons for a set of values; ``selected`` is changed in place. */
function chips(container, values, selected, labelOf, onChange) {
    container.textContent = '';
    values.forEach(value => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'chip';
        chip.textContent = labelOf(value);
        chip.setAttribute('aria-pressed', String(selected.has(value)));
        chip.addEventListener('click', () => {
            if (selected.has(value)) selected.delete(value); else selected.add(value);
            chip.setAttribute('aria-pressed', String(selected.has(value)));
            onChange();
        });
        container.appendChild(chip);
    });
}

// Close an open dropdown when clicking elsewhere
document.addEventListener('click', (event) => {
    document.querySelectorAll('details.multi-select-dropdown[open]').forEach(details => {
        if (!details.contains(event.target)) details.open = false;
    });
});

function cell(row, content, className) {
    const td = document.createElement('td');
    if (className) td.className = className;
    if (content instanceof Node) td.appendChild(content); else td.textContent = content ?? '';
    row.appendChild(td);
    return td;
}

function pill(className, text) {
    const span = document.createElement('span');
    span.className = className;
    span.textContent = text;
    return span;
}

function typeLabel(type) {
    return t(`manager.types.${type}`);
}

// =========================================================================
// History
// =========================================================================

function saveFilters() {
    try {
        localStorage.setItem(FILTERS_KEY, JSON.stringify({ ...state.filters, limit: state.limit }));
    } catch (error) {
        // Storage blocked: the filters simply are not remembered
    }
}

function restoreFilters() {
    try {
        const saved = JSON.parse(localStorage.getItem(FILTERS_KEY) || 'null');
        if (saved) {
            state.filters = { ...defaultFilters(), ...saved };
            state.limit = saved.limit || state.limit;
        }
    } catch (error) {
        // Unreadable: start from the defaults
    }
}

function historyParams() {
    const f = state.filters;
    const params = new URLSearchParams({
        sort_by: state.sortBy,
        sort_order: state.sortOrder,
        limit: String(state.limit),
        offset: String(state.offset)
    });
    if (f.q.trim()) params.set('q', f.q.trim());
    if (f.users.length) params.set('users', f.users.join(','));
    if (f.types.length) params.set('types', f.types.join(','));
    if (f.statuses.length) params.set('statuses', f.statuses.join(','));
    if (f.pulled) params.set('pulled', f.pulled);
    if (f.from) params.set('date_from', dayStart(f.from));
    if (f.to) params.set('date_to', dayStart(f.to, 1));
    return params;
}

function filtersBody() {
    const params = historyParams();
    return {
        q: params.get('q'),
        users: state.filters.users,
        types: state.filters.types,
        statuses: state.filters.statuses,
        date_from: params.get('date_from'),
        date_to: params.get('date_to'),
        pulled: state.filters.pulled === '' ? null : state.filters.pulled === 'true',
        sort_by: state.sortBy,
        sort_order: state.sortOrder
    };
}

async function loadHistory() {
    const requestId = ++state.requestId;
    const loading = document.getElementById('history-loading');
    loading.classList.remove('hidden');
    try {
        const data = await apiRequest(`/api/manager/operations?${historyParams()}`);
        if (requestId !== state.requestId) return; // a newer request is on its way
        state.total = data.total;
        renderSummary(data.summary);
        renderHistory(data.operations);
        renderPager();
    } catch (error) {
        if (requestId === state.requestId) showError(t('manager.table.loadFailed', { error: error.message }));
    } finally {
        if (requestId === state.requestId) loading.classList.add('hidden');
    }
}

const reloadHistory = debounce(() => {
    state.offset = 0;
    saveFilters();
    loadHistory();
}, 300);

function renderSummary(summary) {
    const container = document.getElementById('summary-cards');
    container.textContent = '';
    const files = summary.by_user.reduce((sum, u) => sum + (u.files || 0), 0);
    const cards = [
        ['manager.summary.total', summary.total, null],
        ['manager.summary.pushes', summary.by_type.PUSH || 0, 'push'],
        ['manager.summary.pulls', summary.by_type.PULL || 0, 'pull'],
        ['manager.summary.updates', summary.by_type.UPDATE || 0, 'update'],
        ['manager.summary.failed', summary.by_status.FAILED || 0, 'failed'],
        ['manager.summary.files', files, null]
    ];
    cards.forEach(([key, value, tone]) => {
        const card = document.createElement('div');
        card.className = 'summary-card' + (tone ? ` tone-${tone}` : '');
        const number = document.createElement('div');
        number.className = 'summary-value';
        number.textContent = Number(value).toLocaleString(document.documentElement.lang || undefined);
        const label = document.createElement('div');
        label.className = 'summary-label';
        label.textContent = t(key);
        card.append(number, label);
        container.appendChild(card);
    });

    const body = document.getElementById('by-user-body');
    body.textContent = '';
    summary.by_user.forEach(user => {
        const row = document.createElement('tr');
        row.className = 'clickable';
        row.tabIndex = 0;
        cell(row, user.username);
        [user.total, user.push, user.pull, user.update, user.failed, user.files]
            .forEach(value => cell(row, String(value), 'num'));
        const pick = () => {
            state.filters.users = [user.username];
            renderUserFilter();
            reloadHistory();
        };
        row.addEventListener('click', pick);
        row.addEventListener('keydown', e => { if (e.key === 'Enter') pick(); });
        body.appendChild(row);
    });
}

function renderHistory(operations) {
    const body = document.getElementById('history-body');
    body.textContent = '';
    document.getElementById('history-empty').classList.toggle('hidden', operations.length > 0);

    operations.forEach(op => {
        const row = document.createElement('tr');
        row.className = 'clickable';
        row.tabIndex = 0;
        cell(row, `#${op.id}`, 'mono');
        cell(row, pill(`operation-type ${op.type.toLowerCase()}`, typeLabel(op.type)));
        cell(row, pill(`operation-status ${op.status.toLowerCase()}`, formatOperationStatus(op.status)));

        const catalog = document.createElement('div');
        catalog.className = 'catalog-cell';
        const name = document.createElement('strong');
        name.textContent = op.catalog_name || op.source_path;
        catalog.appendChild(name);
        if (op.has_been_pulled) {
            catalog.appendChild(pill('badge badge-warning', t('manager.table.pulledBadge')));
        }
        const path = document.createElement('div');
        path.className = 'text-muted path-line';
        path.textContent = op.type === 'PUSH' ? op.source_path : (op.dest_path || op.source_path);
        path.title = path.textContent;
        catalog.appendChild(path);
        if (op.error_msg) {
            const error = document.createElement('div');
            error.className = 'text-danger path-line';
            error.textContent = op.error_msg;
            error.title = op.error_msg;
            catalog.appendChild(error);
        }
        cell(row, catalog);

        cell(row, op.user_name);
        cell(row, formatDateTime(op.created_at), 'nowrap');
        cell(row, formatDateTime(op.completed_at), 'nowrap');
        cell(row, op.file_count ?? '', 'num');
        cell(row, op.pim_delivery ? pill(`integration-badge pim-${op.pim_delivery.status.toLowerCase()}`,
            formatPimDelivery(op.pim_delivery)) : '');

        const open = () => openOperationDetails(op.id, { onChange: loadHistory });
        row.addEventListener('click', open);
        row.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
        body.appendChild(row);
    });
}

function renderPager() {
    const from = state.total === 0 ? 0 : state.offset + 1;
    const to = Math.min(state.offset + state.limit, state.total);
    document.getElementById('page-range').textContent = t('manager.table.range', { from, to, total: state.total });
    document.getElementById('page-prev').disabled = state.offset === 0;
    document.getElementById('page-next').disabled = state.offset + state.limit >= state.total;
}

function renderSortArrows() {
    document.querySelectorAll('#history-table th.sortable').forEach(th => {
        const active = th.dataset.sortBy === state.sortBy;
        th.classList.toggle('sorted-asc', active && state.sortOrder === 'asc');
        th.classList.toggle('sorted-desc', active && state.sortOrder === 'desc');
        th.setAttribute('aria-sort', active ? (state.sortOrder === 'asc' ? 'ascending' : 'descending') : 'none');
        th.querySelector('.sort-arrow').textContent = active ? (state.sortOrder === 'asc' ? '▲' : '▼') : '';
    });
}

function renderUserFilter() {
    const selected = new Set(state.filters.users);
    multiSelect(
        document.getElementById('filter-users'),
        state.users.map(u => ({
            value: u.username,
            label: u.username,
            hint: [t(`roles.${u.role}`), u.is_active ? null : t('manager.filters.inactiveUser')]
                .filter(Boolean).join(', ')
        })),
        selected,
        {
            allLabel: t('manager.filters.allUsers'),
            onChange: () => {
                state.filters.users = [...selected];
                reloadHistory();
            }
        }
    );
}

function renderFilterControls() {
    const f = state.filters;
    if (f.period !== 'custom') [f.from, f.to] = periodRange(f.period);
    document.getElementById('filter-q').value = f.q;
    document.getElementById('filter-period').value = f.period;
    document.getElementById('filter-from').value = f.from;
    document.getElementById('filter-to').value = f.to;
    document.getElementById('filter-pulled').value = f.pulled;
    document.getElementById('page-size').value = String(state.limit);
    renderUserFilter();

    const types = new Set(f.types);
    chips(document.getElementById('filter-types'), TYPES, types, typeLabel, () => {
        state.filters.types = [...types];
        reloadHistory();
    });
    const statuses = new Set(f.statuses);
    chips(document.getElementById('filter-statuses'), STATUSES, statuses, formatOperationStatus, () => {
        state.filters.statuses = [...statuses];
        reloadHistory();
    });
}

function setupHistory() {
    const f = () => state.filters;
    document.getElementById('filter-q').addEventListener('input', e => {
        f().q = e.target.value;
        reloadHistory();
    });
    document.getElementById('filter-period').addEventListener('change', e => {
        f().period = e.target.value;
        if (f().period !== 'custom') {
            [f().from, f().to] = periodRange(f().period);
            document.getElementById('filter-from').value = f().from;
            document.getElementById('filter-to').value = f().to;
        }
        reloadHistory();
    });
    ['from', 'to'].forEach(which => {
        document.getElementById(`filter-${which}`).addEventListener('change', e => {
            f()[which] = e.target.value;
            f().period = 'custom';
            document.getElementById('filter-period').value = 'custom';
            reloadHistory();
        });
    });
    document.getElementById('filter-pulled').addEventListener('change', e => {
        f().pulled = e.target.value;
        reloadHistory();
    });
    document.getElementById('filter-reset').addEventListener('click', () => {
        state.filters = defaultFilters();
        renderFilterControls();
        reloadHistory();
    });
    document.getElementById('page-size').addEventListener('change', e => {
        state.limit = parseInt(e.target.value, 10);
        reloadHistory();
    });
    document.getElementById('page-prev').addEventListener('click', () => {
        state.offset = Math.max(0, state.offset - state.limit);
        loadHistory();
    });
    document.getElementById('page-next').addEventListener('click', () => {
        state.offset += state.limit;
        loadHistory();
    });
    document.querySelectorAll('#history-table th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const column = th.dataset.sortBy;
            if (state.sortBy === column) {
                state.sortOrder = state.sortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortBy = column;
                state.sortOrder = ['created_at', 'completed_at', 'id', 'file_count'].includes(column) ? 'desc' : 'asc';
            }
            renderSortArrows();
            state.offset = 0;
            loadHistory();
        });
    });
    document.getElementById('export-btn').addEventListener('click', exportHistory);
}

async function exportHistory() {
    const button = document.getElementById('export-btn');
    button.disabled = true;
    showInfo(t('manager.filters.exporting'));
    try {
        await apiDownload('/api/manager/operations/export', {
            ...filtersBody(),
            columns: EXPORT_COLUMNS.map(([key, labelKey]) => ({ key, header: t(labelKey) }))
        });
        showSuccess(t('manager.filters.exported', { count: Math.min(state.total, 20000) }));
    } catch (error) {
        showError(t('manager.filters.exportFailed', { error: error.message }));
    } finally {
        button.disabled = false;
    }
}

// =========================================================================
// Reports
// =========================================================================

function errorText(error) {
    return error.detail?.message || error.message;
}

async function loadReportSettings() {
    let settings;
    try {
        settings = await apiRequest('/api/manager/reports/settings');
    } catch (error) {
        settings = { valid: false, error: error.message };
    }
    state.reportSettings = settings;

    const status = document.getElementById('auto-status');
    const help = document.getElementById('auto-help');
    const facts = document.getElementById('auto-facts');
    facts.textContent = '';
    const fact = (labelKey, value, mono = false) => {
        if (value === null || value === undefined || value === '') return;
        const dt = document.createElement('dt');
        dt.textContent = t(labelKey);
        const dd = document.createElement('dd');
        dd.textContent = value;
        if (mono) dd.className = 'mono break-all';
        facts.append(dt, dd);
    };

    if (!settings.valid) {
        status.className = 'badge badge-danger';
        status.textContent = t('manager.reports.auto.off');
        help.textContent = t('manager.reports.auto.invalid', { error: settings.error });
        renderWriteRecipients([]);
        return;
    }

    status.className = 'badge ' + (settings.auto_enabled ? 'badge-success' : 'badge-secondary');
    status.textContent = t(settings.auto_enabled ? 'manager.reports.auto.on' : 'manager.reports.auto.off');
    help.textContent = settings.auto_enabled
        ? t('manager.reports.auto.help', { time: settings.run_time, timezone: settings.timezone })
        : t('manager.reports.auto.offHelp');
    fact('manager.reports.auto.nextRun', settings.next_run ? formatDateTime(settings.next_run) : null);
    fact('manager.reports.auto.recipients',
        settings.recipients.map(r => `${r.name} (${r.username})`).join(', '));
    fact('manager.reports.auto.folder', settings.example_path || settings.path_error, true);
    const configured = ok => t(ok ? 'manager.reports.auto.configured' : 'manager.reports.auto.notConfigured');
    fact('manager.reports.auto.productData', configured(settings.product_data));
    fact('manager.reports.auto.shareAccount', configured(settings.share_account));
    renderWriteRecipients(settings.recipients);

    // Default the generator to the configured people the first time
    if (state.reportUsers.size === 0) {
        const known = new Set(state.users.map(u => u.username));
        settings.recipients.filter(r => known.has(r.username)).forEach(r => state.reportUsers.add(r.username));
        renderReportUsers();
    }
}

function renderWriteRecipients(recipients) {
    state.writeRecipients = new Set(recipients.map(r => r.username));
    const names = Object.fromEntries(recipients.map(r => [r.username, r.name]));
    chips(document.getElementById('write-recipients'), recipients.map(r => r.username),
        state.writeRecipients, username => names[username], () => {
            document.getElementById('write-btn').disabled = state.writeRecipients.size === 0;
        });
    document.getElementById('write-btn').disabled = recipients.length === 0;
}

function renderReportUsers() {
    const recipients = Object.fromEntries((state.reportSettings?.recipients || []).map(r => [r.username, r.name]));
    multiSelect(
        document.getElementById('report-users'),
        state.users.map(u => ({ value: u.username, label: u.username, hint: recipients[u.username] || '' })),
        state.reportUsers,
        { allLabel: t('manager.reports.generator.chooseUsers'), onChange: () => {} }
    );
}

function reportPeriod() {
    const mode = document.querySelector('input[name="report-mode"]:checked').value;
    if (mode === 'month') {
        const month = document.getElementById('report-month').value;
        if (!month) return null;
        const [y, m] = month.split('-').map(Number);
        return [isoDay(new Date(y, m - 1, 1)), isoDay(new Date(y, m, 0))];
    }
    const from = document.getElementById('report-from').value;
    const to = document.getElementById('report-to').value;
    return from && to ? [from, to] : null;
}

async function downloadReport() {
    const feedback = document.getElementById('report-feedback');
    feedback.className = 'report-feedback';
    if (state.reportUsers.size === 0) {
        feedback.textContent = t('manager.reports.generator.chooseUsers');
        feedback.classList.add('text-danger');
        return;
    }
    const period = reportPeriod();
    if (!period || period[1] < period[0]) {
        feedback.textContent = t('manager.reports.generator.badRange');
        feedback.classList.add('text-danger');
        return;
    }

    const button = document.getElementById('report-download');
    button.disabled = true;
    feedback.textContent = t('manager.reports.generator.downloading');
    try {
        const { headers } = await apiDownload('/api/manager/reports/download', {
            usernames: [...state.reportUsers],
            date_from: period[0],
            date_to: period[1],
            include_user_column: document.getElementById('report-user-column').checked,
            user_column_header: t('manager.columns.user')
        });
        const lines = [t('manager.reports.generator.downloaded', { rows: headers.get('X-Report-Rows') ?? '?' })];
        const warning = headers.get('X-Report-Warning');
        if (warning) {
            lines.push(t('manager.reports.generator.warning', { warning: decodeURIComponent(warning) }));
            feedback.classList.add('text-warning');
        }
        feedback.textContent = lines.join(' ');
    } catch (error) {
        feedback.textContent = t('manager.reports.generator.failed', { error: errorText(error) });
        feedback.classList.add('text-danger');
    } finally {
        button.disabled = false;
    }
}

async function writeReportsNow() {
    const month = document.getElementById('write-month').value;
    const recipients = (state.reportSettings?.recipients || []).filter(r => state.writeRecipients.has(r.username));
    if (!month || recipients.length === 0) return;

    const { confirmed } = await showDialog({
        title: t('manager.reports.auto.writeNow'),
        message: t('manager.reports.auto.writeConfirm', {
            month: formatMonth(month),
            names: recipients.map(r => r.name).join(', ')
        }),
        confirmLabel: t('manager.reports.auto.writeButton')
    });
    if (!confirmed) return;

    try {
        const runs = await apiRequest('/api/manager/reports/run', {
            method: 'POST',
            body: JSON.stringify({ month, usernames: recipients.map(r => r.username) })
        });
        showSuccess(t('manager.reports.auto.writeStarted', { count: runs.length }));
        loadRuns();
    } catch (error) {
        showError(t('manager.reports.auto.writeFailed', { error: errorText(error) }));
    }
}

async function loadRuns() {
    clearTimeout(state.runsTimer);
    let runs;
    try {
        runs = await apiRequest('/api/manager/reports/runs?limit=50');
    } catch (error) {
        showError(error.message);
        return;
    }
    const body = document.getElementById('runs-body');
    body.textContent = '';
    document.getElementById('runs-empty').classList.toggle('hidden', runs.length > 0);
    const tone = { RUNNING: 'badge-info', SUCCESS: 'badge-success', FAILED: 'badge-danger' };

    runs.forEach(run => {
        const row = document.createElement('tr');
        cell(row, formatDateTime(run.started_at), 'nowrap');
        cell(row, formatMonth(run.report_month.slice(0, 7)), 'nowrap');
        cell(row, `${run.label} (${run.recipient})`);
        let trigger = run.trigger === 'SCHEDULED'
            ? t('manager.reports.runs.scheduled')
            : t('manager.reports.runs.manual', { user: run.requested_by || '?' });
        if (run.attempts > 1) trigger += ` · ${t('manager.reports.runs.attempts', { count: run.attempts })}`;
        cell(row, trigger);
        cell(row, pill(`badge ${tone[run.status] || ''}`, t(`manager.reports.runs.${run.status}`)));
        cell(row, run.row_count ?? '', 'num');
        cell(row, run.file_path || '', 'mono break-all');
        const message = cell(row, run.message || '', run.status === 'FAILED' ? 'text-danger' : 'text-muted');
        message.classList.add('break-all');
        body.appendChild(row);
    });

    // Follow running reports until they finish
    if (runs.some(run => run.status === 'RUNNING')) {
        state.runsTimer = setTimeout(loadRuns, RUNS_POLL_MS);
    }
}

function setupReports() {
    const today = new Date();
    document.getElementById('report-month').value = isoMonth(today);
    document.getElementById('write-month').value = isoMonth(today);
    document.getElementById('write-month').max = isoMonth(today);
    document.getElementById('report-from').value = isoDay(new Date(today.getFullYear(), today.getMonth(), 1));
    document.getElementById('report-to').value = isoDay(today);

    document.querySelectorAll('input[name="report-mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            const range = document.querySelector('input[name="report-mode"]:checked').value === 'range';
            document.getElementById('report-month-row').classList.toggle('hidden', range);
            document.getElementById('report-range-row').classList.toggle('hidden', !range);
        });
    });
    document.getElementById('report-download').addEventListener('click', downloadReport);
    document.getElementById('write-btn').addEventListener('click', writeReportsNow);
    document.getElementById('runs-refresh').addEventListener('click', loadRuns);
}

// =========================================================================
// Tabs and start-up
// =========================================================================

const loadedTabs = new Set();

function switchTab(tab) {
    if (!['history', 'reports'].includes(tab)) tab = 'history';
    document.querySelectorAll('.tab-btn').forEach(button => {
        const active = button.dataset.tab === tab;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === `tab-${tab}`);
    });
    if (window.location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);

    if (!loadedTabs.has(tab)) {
        loadedTabs.add(tab);
        if (tab === 'history') loadHistory();
        if (tab === 'reports') {
            loadReportSettings();
            loadRuns();
        }
    } else if (tab === 'reports') {
        loadRuns();
    }
}

function setupHeader(user) {
    document.getElementById('user-name').textContent = user.username;
    document.getElementById('user-role').textContent = t(`roles.${String(user.role).toUpperCase()}`);
    document.getElementById('user-avatar').textContent = String(user.username || '?').slice(0, 2);
    document.getElementById('explorer-btn').addEventListener('click', () => {
        window.location.href = 'explorer.html';
    });
    const adminButton = document.getElementById('admin-btn');
    const isAdmin = String(user.role).toUpperCase() === 'ADMIN';
    adminButton.hidden = !isAdmin;
    adminButton.addEventListener('click', () => {
        window.location.href = 'admin.html';
    });
    document.getElementById('auto-admin-link').hidden = !isAdmin;
    document.getElementById('logout-btn').addEventListener('click', () => logout());
}

async function init() {
    if (!checkAuth()) {
        redirectToLogin();
        return;
    }
    const user = getCurrentUser();
    if (!user) {
        redirectToLogin();
        return;
    }

    await initI18n();
    translatePage();
    loadAndApplyTheme();

    if (!MANAGER_ROLES.includes(String(user.role).toUpperCase())) {
        await showDialog({ title: t('manager.title'), message: t('manager.accessDenied'), hideCancel: true });
        window.location.href = 'explorer.html';
        return;
    }

    setupAutoRefresh();
    setupHeader(user);

    try {
        state.users = await apiRequest('/api/manager/users');
    } catch (error) {
        showError(error.message);
    }

    restoreFilters();
    renderFilterControls();
    renderSortArrows();
    setupHistory();
    renderReportUsers();
    setupReports();

    document.querySelectorAll('.tab-btn').forEach(button => {
        button.addEventListener('click', () => switchTab(button.dataset.tab));
    });
    window.addEventListener('hashchange', () => switchTab(window.location.hash.slice(1)));
    switchTab(window.location.hash.slice(1));
}

init();
