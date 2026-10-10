/**
 * Operation details dialog, shared by the explorer and the manager view.
 *
 * Shows one operation (who, what, when, where, outcome) with the operations
 * of its catalog: for a PUSH every UPDATE and the PULL, for an UPDATE or a
 * PULL the PUSH it belongs to. The page must contain the
 * #operation-details-modal markup (see pages/explorer.html).
 */

import { t } from './i18n.js';
import {
    getOperationDetails,
    retryPimDelivery,
    recheckRemoteSync,
    stopPimDelivery,
    stopRemoteSync
} from './api.js';
import { formatOperationStatus, formatPimDelivery, formatRemoteSync, showError, showSuccess } from './ui.js';
import { showDialog, formatFileSize, formatDateTime } from './utils.js';

/**
 * One line describing an UPDATE action - used for the pending list, the
 * confirmation and the history details, so all three read the same.
 */
export function describeUpdateAction(action) {
    const upload = action.upload || {};
    const file = upload.filename
        ? t('update.describeUploadedFile', {
            name: upload.filename,
            size: upload.size_bytes != null ? formatFileSize(upload.size_bytes) : '?'
        })
        : null;

    let text;
    switch (action.action) {
        case 'rename':
        case 'move':
            text = t('update.describeRename', { source: action.source, dest: action.dest });
            break;
        case 'delete':
            text = t('update.describeDelete', { source: action.source });
            break;
        case 'replace':
            text = t('update.describeReplace', { source: action.source, from: action.from_path || file });
            break;
        case 'add':
            text = t('update.describeAdd', { dest: action.dest, from: action.from_path || file });
            break;
        default:
            text = JSON.stringify(action);
    }

    if (action.remove_source) {
        if (action.source_removed === true) {
            text += ' — ' + t('update.describeSourceRemoved');
        } else if (action.source_removed === false) {
            text += ' — ' + t('update.describeSourceNotRemoved');
        } else {
            text += ' — ' + t('update.describeSourceWillBeRemoved');
        }
    }
    if (upload.sha256) {
        text += ' — ' + t('update.describeChecksum', { sha: upload.sha256.slice(0, 16) });
    }
    return text;
}

// Operation whose details dialog is open, so integration actions can refresh it
let detailsOperationId = null;
// Called after an integration action changed an operation (the page refreshes its list)
let onChangeHandler = null;

/**
 * PIM delivery and image host sync for one operation, with the actions a
 * user can take: stop a pending PIM notification or an active check, send
 * the PIM event again, check the image host again.
 */
function buildIntegrationDetails(operation) {
    const pim = operation.pim_delivery;
    const sync = operation.remote_sync;
    const block = document.createElement('div');
    block.className = 'integration-details';
    if (!pim && !sync) return block;

    const when = formatDateTime;
    const stoppedBy = job => t('integration.stoppedBy', { time: when(job.cancelled_at), user: job.cancelled_by });
    const facts = document.createElement('dl');
    facts.className = 'operation-facts';
    const fact = (labelKey, value) => {
        if (value === null || value === undefined || value === '') return;
        const dt = document.createElement('dt');
        dt.textContent = t(labelKey);
        const dd = document.createElement('dd');
        dd.textContent = value;
        facts.append(dt, dd);
    };
    const actionButton = (labelKey, run, confirmKey = null) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-secondary btn-sm';
        button.textContent = t(labelKey);
        button.addEventListener('click', async () => {
            if (confirmKey) {
                const { confirmed } = await showDialog({ title: t(labelKey), message: t(confirmKey), confirmLabel: t(labelKey) });
                if (!confirmed) return;
            }
            button.disabled = true;
            try {
                await run();
                showSuccess(t(labelKey + 'Done'));
            } catch (error) {
                showError(t('integration.actionFailed', { error: error.message }));
            }
            if (onChangeHandler) Promise.resolve(onChangeHandler()).catch(() => {});
            if (detailsOperationId !== null) openOperationDetails(detailsOperationId, { onChange: onChangeHandler });
        });
        return button;
    };

    if (pim) {
        fact('integration.pimLabel', formatPimDelivery(pim));
        fact('integration.eventType', pim.event_type);
        fact('integration.tgId', pim.tg_id);
        fact('integration.attemptsLabel', String(pim.attempts));
        fact('integration.deliveredLabel', when(pim.delivered_at));
        if (pim.status === 'PENDING' && pim.attempts > 0) {
            fact('integration.nextAttemptLabel', when(pim.next_attempt_at));
        }
        if (pim.cancelled_by) fact('integration.stoppedLabel', stoppedBy(pim));
        if (pim.status !== 'DELIVERED') fact('integration.lastErrorLabel', pim.last_error);
    }
    if (sync) {
        fact('integration.syncLabel', formatRemoteSync(sync));
        fact('integration.syncStarted', when(sync.started_at));
        fact('integration.lastCheckedLabel', when(sync.last_checked_at));
        if (sync.status === 'CHECKING') fact('integration.nextCheckLabel', when(sync.next_check_at));
        if (sync.cancelled_by) {
            fact('integration.stoppedLabel', stoppedBy(sync));
        } else {
            fact('integration.syncCompleted', when(sync.completed_at));
        }
        fact('integration.lastErrorLabel', sync.last_error);
    }
    block.appendChild(facts);

    if (sync && sync.status !== 'WAITING' && (sync.files || []).length > 0) {
        const list = document.createElement('ul');
        list.className = 'sync-files';
        sync.files.forEach(file => {
            const item = document.createElement('li');
            item.className = file.synced ? 'synced' : 'missing';
            item.textContent = (file.synced ? '✓ ' : '✗ ') + file.name
                + (!file.synced && file.status_code ? ` (HTTP ${file.status_code})` : '');
            list.appendChild(item);
        });
        block.appendChild(list);
    }

    const actions = document.createElement('div');
    actions.className = 'integration-actions';
    if (pim && pim.status === 'PENDING') {
        actions.appendChild(actionButton('integration.stopPim', () => stopPimDelivery(operation.id),
            'integration.stopPimConfirm'));
    }
    if (pim && pim.status !== 'DELIVERED') {
        actions.appendChild(actionButton('integration.retryPim', () => retryPimDelivery(operation.id)));
    }
    if (sync && ['WAITING', 'CHECKING'].includes(sync.status)) {
        actions.appendChild(actionButton('integration.stopSync', () => stopRemoteSync(operation.id),
            'integration.stopSyncConfirm'));
    }
    // A check cancelled by a PULL stays cancelled: the catalog is gone
    if (sync && (['CHECKING', 'TIMEOUT', 'SYNCED'].includes(sync.status) || sync.cancelled_by)) {
        actions.appendChild(actionButton('integration.recheckSync', () => recheckRemoteSync(operation.id)));
    }
    if (actions.children.length > 0) block.appendChild(actions);

    return block;
}

/**
 * Who did what, when, and with which result, for one operation.
 */
function buildOperationSummary(operation) {
    const block = document.createElement('div');
    block.className = `operation-summary status-${String(operation.status).toLowerCase()}`;

    const heading = document.createElement('div');
    heading.className = 'operation-summary-heading';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'operation-type ' + String(operation.type).toLowerCase();
    typeBadge.textContent = operation.type;
    const title = document.createElement('strong');
    title.textContent = ` #${operation.id} `;
    const status = document.createElement('span');
    status.className = 'operation-status ' + String(operation.status).toLowerCase().replace('_', '-');
    status.textContent = formatOperationStatus(operation.status);
    const who = document.createElement('span');
    who.className = 'text-muted';
    who.textContent = ' ' + t('details.by', { user: operation.user_name || '?' });
    heading.append(typeBadge, title, status, who);
    block.appendChild(heading);

    const facts = document.createElement('dl');
    facts.className = 'operation-facts';
    const fact = (labelKey, value) => {
        if (value === null || value === undefined || value === '') return;
        const dt = document.createElement('dt');
        dt.textContent = t(labelKey);
        const dd = document.createElement('dd');
        dd.textContent = value;
        facts.append(dt, dd);
    };
    const when = formatDateTime;
    fact('details.created', when(operation.created_at));
    fact('details.started', when(operation.started_at));
    fact('details.completed', when(operation.completed_at));
    fact('details.source', operation.source_path);
    if (operation.dest_path !== operation.source_path) fact('details.destination', operation.dest_path);
    fact('details.archive', operation.archive_path);
    if (operation.type !== 'UPDATE') fact('details.fileCount', operation.file_count);
    fact('details.error', operation.error_msg);
    block.appendChild(facts);
    block.appendChild(buildIntegrationDetails(operation));

    const params = operation.params_json || {};
    if (operation.type === 'UPDATE' && Array.isArray(params.actions)) {
        const list = document.createElement('ul');
        list.className = 'operation-actions';
        params.actions.forEach(action => {
            const item = document.createElement('li');
            item.textContent = describeUpdateAction(action);
            list.appendChild(item);
        });
        block.appendChild(list);
    }
    if (operation.type === 'PULL' && (params.update_operation_ids || []).length > 0) {
        const note = document.createElement('p');
        note.textContent = t('details.pullIncludedUpdates', {
            ids: params.update_operation_ids.map(id => '#' + id).join(', ')
        });
        block.appendChild(note);
    }
    (params.warnings || []).forEach(warning => {
        const note = document.createElement('p');
        note.className = 'text-danger';
        note.textContent = '⚠ ' + warning;
        block.appendChild(note);
    });

    return block;
}

/**
 * Open the details dialog of an operation.
 *
 * @param {number} operationId
 * @param {Object} [options]
 * @param {Function} [options.onChange] - called after a PIM / image host action
 */
export async function openOperationDetails(operationId, { onChange = null } = {}) {
    let details;
    try {
        details = await getOperationDetails(operationId);
    } catch (error) {
        showError(t('details.loadFailed', { error: error.message }));
        return;
    }

    detailsOperationId = operationId;
    onChangeHandler = onChange;
    const modal = document.getElementById('operation-details-modal');
    const body = document.getElementById('operation-details-body');
    body.textContent = '';

    const main = details.operation;
    document.getElementById('operation-details-title').textContent =
        t('details.titleFor', { type: main.type, id: main.id });

    const section = (headingText, children) => {
        const heading = document.createElement('h4');
        heading.textContent = headingText;
        body.appendChild(heading);
        children.forEach(child => body.appendChild(child));
    };

    body.appendChild(buildOperationSummary(main));

    if (details.push) {
        section(t('details.pushHeader'), [buildOperationSummary(details.push)]);
    }
    if (details.updates.length > 0) {
        section(t('details.updatesHeader', { count: details.updates.length }),
            details.updates.map(buildOperationSummary));
    } else if (main.type === 'PUSH') {
        const none = document.createElement('p');
        none.className = 'text-muted';
        none.textContent = t('details.noUpdates');
        section(t('details.updatesHeader', { count: 0 }), [none]);
    }
    if (details.pull && details.pull.id !== main.id) {
        section(t('details.pullHeader'), [buildOperationSummary(details.pull)]);
    }

    const closeButtons = [
        document.getElementById('operation-details-close'),
        document.getElementById('operation-details-ok')
    ];
    const close = () => {
        detailsOperationId = null;
        modal.classList.add('hidden');
        closeButtons.forEach(button => button.removeEventListener('click', close));
    };
    closeButtons.forEach(button => button.addEventListener('click', close));
    modal.classList.remove('hidden');
}
