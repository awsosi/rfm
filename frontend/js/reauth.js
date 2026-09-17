/**
 * Password confirmation for admin changes to system settings.
 *
 * The API answers 403 "reauth_required" when the admin has not typed their
 * password in this session recently (config admin_reauth_minutes). apiRequest
 * then calls confirmPassword() and, once confirmed, sends the request again.
 *
 * The dialog is a real <form> with a username field (read-only, filled with
 * the signed-in user) and a current-password field, so password managers
 * recognise it and offer the saved password.
 */

import { getApiBaseUrl, getCurrentUser, getToken, redirectToLogin } from './auth.js';
import { initI18n, isI18nReady, t } from './i18n.js';

let pending = null;

/**
 * Ask for the password and confirm it with the API. Concurrent callers share
 * one dialog.
 * @returns {Promise<boolean>} true once confirmed, false when cancelled
 */
export function confirmPassword() {
    if (!pending) {
        pending = openDialog().finally(() => {
            pending = null;
        });
    }
    return pending;
}

/** Error thrown to the caller when the admin cancels the confirmation. */
export function notConfirmedError() {
    const error = new Error(t('reauth.notConfirmed'));
    error.reauthCancelled = true;
    return error;
}

async function openDialog() {
    if (!isI18nReady()) {
        await initI18n();
    }

    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'reauth-title');
    modal.innerHTML = `
        <div class="modal-content">
            <form id="reauth-form" method="post" action="#" novalidate>
                <div class="modal-header">
                    <h3 id="reauth-title"></h3>
                    <button type="button" class="modal-close" data-cancel>&times;</button>
                </div>
                <div class="modal-body">
                    <p class="reauth-message"></p>
                    <div class="error-message hidden" role="alert" aria-live="assertive"></div>
                    <div class="form-group">
                        <label for="reauth-username"></label>
                        <input type="text" id="reauth-username" name="username" class="form-control"
                               autocomplete="username" readonly>
                    </div>
                    <div class="form-group">
                        <label for="reauth-password"></label>
                        <input type="password" id="reauth-password" name="password" class="form-control"
                               autocomplete="current-password" required>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-cancel></button>
                    <button type="submit" class="btn btn-primary"></button>
                </div>
            </form>
        </div>`;

    const form = modal.querySelector('form');
    const errorBox = modal.querySelector('.error-message');
    const usernameInput = modal.querySelector('#reauth-username');
    const passwordInput = modal.querySelector('#reauth-password');
    const submitBtn = modal.querySelector('button[type="submit"]');

    modal.querySelector('#reauth-title').textContent = t('reauth.title');
    modal.querySelector('.reauth-message').textContent = t('reauth.message');
    modal.querySelector('label[for="reauth-username"]').textContent = t('login.username');
    modal.querySelector('label[for="reauth-password"]').textContent = t('login.password');
    modal.querySelector('.modal-footer [data-cancel]').textContent = t('reauth.cancel');
    modal.querySelector('.modal-close').setAttribute('aria-label', t('reauth.cancel'));
    submitBtn.textContent = t('reauth.confirm');
    usernameInput.value = getCurrentUser()?.username || '';

    document.body.appendChild(modal);
    passwordInput.focus();

    const showError = (message) => {
        errorBox.textContent = message;
        errorBox.classList.remove('hidden');
        passwordInput.select();
        passwordInput.focus();
    };

    return new Promise((resolve) => {
        const finish = (confirmed) => {
            document.removeEventListener('keydown', onKey);
            modal.remove();
            resolve(confirmed);
        };
        const onKey = (e) => {
            if (e.key === 'Escape') finish(false);
        };
        document.addEventListener('keydown', onKey);
        modal.querySelectorAll('[data-cancel]').forEach(btn => btn.addEventListener('click', () => finish(false)));

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!passwordInput.value) {
                showError(t('reauth.missingPassword'));
                return;
            }
            const token = getToken();
            if (!token) {
                finish(false);
                redirectToLogin();
                return;
            }

            submitBtn.disabled = true;
            try {
                const response = await fetch(`${getApiBaseUrl()}/api/auth/reauthenticate`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ password: passwordInput.value })
                });
                if (response.ok) {
                    finish(true);
                } else if (response.status === 401) {
                    finish(false);
                    redirectToLogin();
                } else if (response.status === 403) {
                    showError(t('reauth.invalidPassword'));
                } else {
                    showError(t('login.connectionError'));
                }
            } catch (error) {
                showError(t('login.connectionError'));
            } finally {
                submitBtn.disabled = false;
            }
        });
    });
}
