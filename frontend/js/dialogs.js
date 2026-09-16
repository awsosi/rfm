/**
 * Confirmation dialogs the user can turn off.
 *
 * Every confirmation in the explorer is registered here under a stable key.
 * The dialog offers "Don't ask again"; ticking it (and confirming) stores the
 * key in the user's preferences, so the choice follows the user across
 * browsers. Settings lists every key with a toggle to turn it back on.
 *
 * Stored as preferences.custom_settings.suppressed_dialogs = { key: true }.
 * Error and validation popups are never registered: hiding them would hide
 * why an operation was refused.
 */

import { getPreferences, updatePreferences } from './api.js';
import { t } from './i18n.js';
import { showDialog } from './utils.js';

// Order is the order shown in Settings. labelKey/helpKey are i18n keys.
export const DIALOGS = [
    { key: 'push.confirm', labelKey: 'dialogs.pushConfirm', helpKey: 'dialogs.pushConfirmHelp' },
    { key: 'pull.confirm', labelKey: 'dialogs.pullConfirm', helpKey: 'dialogs.pullConfirmHelp' },
    { key: 'pull.confirmAfterUpdate', labelKey: 'dialogs.pullAfterUpdate', helpKey: 'dialogs.pullAfterUpdateHelp' },
    { key: 'update.confirm', labelKey: 'dialogs.updateConfirm', helpKey: 'dialogs.updateConfirmHelp' },
    { key: 'update.confirmDestructive', labelKey: 'dialogs.updateDestructive', helpKey: 'dialogs.updateDestructiveHelp' },
    { key: 'update.discardChanges', labelKey: 'dialogs.updateDiscard', helpKey: 'dialogs.updateDiscardHelp' },
    { key: 'settings.confirmReset', labelKey: 'dialogs.settingsReset', helpKey: 'dialogs.settingsResetHelp' }
];

let suppressed = null;

function fromPreferences(preferences) {
    const stored = preferences?.custom_settings?.suppressed_dialogs;
    return stored && typeof stored === 'object' ? { ...stored } : {};
}

async function loadSuppressed() {
    if (suppressed === null) {
        try {
            suppressed = fromPreferences(await getPreferences());
        } catch (error) {
            // Preferences unavailable: ask every time rather than skip anything
            console.warn('Could not load dialog preferences:', error);
            return {};
        }
    }
    return suppressed;
}

/**
 * Current suppression map ({ key: true }), for the Settings form.
 * @returns {Promise<Object>}
 */
export async function getSuppressedDialogs() {
    return { ...(await loadSuppressed()) };
}

/**
 * Persist a new suppression map, merged into the latest custom_settings so
 * other settings stored there are kept.
 * @param {Object} map - { key: true } for every dialog to hide
 */
export async function saveSuppressedDialogs(map) {
    const preferences = await getPreferences();
    const clean = {};
    DIALOGS.forEach(({ key }) => {
        if (map[key]) clean[key] = true;
    });
    await updatePreferences({
        custom_settings: { ...(preferences.custom_settings || {}), suppressed_dialogs: clean }
    });
    suppressed = clean;
}

/** Forget the cached map, e.g. after preferences were reset. */
export function resetDialogCache() {
    suppressed = null;
}

/**
 * Ask for confirmation unless the user turned this dialog off.
 *
 * @param {string} key - Registered dialog key
 * @param {string} message - Plain text (newlines allowed)
 * @param {Object} [options] - { title, confirmLabel }
 * @returns {Promise<boolean>} true when confirmed or suppressed
 */
export async function confirmDialog(key, message, options = {}) {
    if (!DIALOGS.some(dialog => dialog.key === key)) {
        throw new Error(`Unregistered dialog key: ${key}`);
    }
    if ((await loadSuppressed())[key]) {
        return true;
    }

    const result = await showDialog({
        title: options.title || t('modal.confirmAction'),
        message,
        confirmLabel: options.confirmLabel,
        dontAskAgain: true
    });

    if (result.confirmed && result.dontAskAgain) {
        try {
            await saveSuppressedDialogs({ ...(await loadSuppressed()), [key]: true });
        } catch (error) {
            console.warn('Could not save dialog preference:', error);
        }
    }
    return result.confirmed;
}
