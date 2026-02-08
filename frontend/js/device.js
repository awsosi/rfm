/**
 * Device Authorization Page
 *
 * Handles device authorization for Windows context menu integration.
 * User approves or denies device authorization by entering the user_code.
 */

import { checkAuth, getToken } from './auth.js';
import { initI18n, translatePage, t } from './i18n.js';

const API_BASE_URL = '';

// Initialize i18n and translate page
await initI18n();
translatePage();

// Update page title
document.title = t('device.pageTitle');

// Get URL parameters
const urlParams = new URLSearchParams(window.location.search);
const userCode = urlParams.get('user_code');

// DOM elements
const errorMessage = document.getElementById('error-message');
const successMessage = document.getElementById('success-message');
const authContent = document.getElementById('auth-content');
const userCodeText = document.getElementById('user-code-text');
const approveBtn = document.getElementById('approve-btn');
const denyBtn = document.getElementById('deny-btn');

/**
 * Show error message
 */
function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.remove('hidden');
    successMessage.classList.add('hidden');
}

/**
 * Show success message
 */
function showSuccess(message) {
    successMessage.textContent = message;
    successMessage.classList.remove('hidden');
    errorMessage.classList.add('hidden');

    // Hide auth content after success
    authContent.style.display = 'none';
}

/**
 * Clear all messages
 */
function clearMessages() {
    errorMessage.classList.add('hidden');
    successMessage.classList.add('hidden');
}

/**
 * Verify device authorization request exists and is valid
 */
async function verifyDeviceRequest() {
    if (!userCode) {
        showError(t('device.notFound'));
        approveBtn.disabled = true;
        return false;
    }

    // Display the user code
    userCodeText.textContent = t('device.userCode').replace('{code}', userCode);

    return true;
}

/**
 * Approve device authorization
 */
async function approveDevice() {
    clearMessages();

    // Check if user is authenticated
    if (!checkAuth()) {
        // Redirect to login with return URL
        const returnUrl = encodeURIComponent(window.location.href);
        window.location.href = `login.html?return=${returnUrl}`;
        return;
    }

    try {
        approveBtn.disabled = true;
        approveBtn.textContent = t('device.approve') + '...';

        const token = getToken();
        const response = await fetch(`${API_BASE_URL}/api/auth/device/approve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                user_code: userCode
            })
        });

        if (response.ok) {
            showSuccess(t('device.success'));

            // Close window after 3 seconds
            setTimeout(() => {
                window.close();
            }, 3000);
        } else {
            const error = await response.json();

            if (response.status === 404) {
                showError(t('device.notFound'));
            } else if (response.status === 400) {
                showError(t('device.expired'));
            } else {
                showError(t('device.error').replace('{error}', error.detail || 'Unknown error'));
            }

            approveBtn.disabled = false;
            approveBtn.textContent = t('device.approve');
        }
    } catch (error) {
        console.error('Device approval error:', error);
        showError(t('device.error').replace('{error}', error.message));

        approveBtn.disabled = false;
        approveBtn.textContent = t('device.approve');
    }
}

/**
 * Deny device authorization
 */
function denyDevice() {
    // Simply close the window or redirect to login
    window.close();

    // If window.close() doesn't work (not opened by script), redirect to login
    setTimeout(() => {
        window.location.href = 'login.html';
    }, 100);
}

// Initialize the page
async function init() {
    const isValid = await verifyDeviceRequest();

    if (!isValid) {
        return;
    }

    // Set up event listeners
    approveBtn.addEventListener('click', approveDevice);
    denyBtn.addEventListener('click', denyDevice);
}

// Run initialization
init();
