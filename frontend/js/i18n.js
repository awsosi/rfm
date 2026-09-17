/**
 * Internationalization (i18n) Module
 * Handles loading and managing translations for the application
 */

// Current locale and translations
let currentLocale = 'en-US';
let translations = {};
let availableLocales = [];

/**
 * Initialize i18n system
 * Auto-detects browser language or loads from user preferences
 * @returns {Promise<void>}
 */
const LOCALE_STORAGE_KEY = 'rfm.locale';

/**
 * Read an explicitly chosen locale from local storage.
 * @returns {string|null} Locale code, or null if unset/unavailable/unknown
 */
function getStoredLocale() {
    try {
        const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
        return stored && availableLocales.includes(stored) ? stored : null;
    } catch (error) {
        return null;
    }
}

export async function initI18n() {
    // Load available locales
    try {
        const response = await fetch('/locales/locales.json');
        availableLocales = await response.json();
    } catch (error) {
        console.error('Failed to load available locales:', error);
        availableLocales = ['en-US'];
    }

    // Determine which locale to use
    let localeToLoad = 'en-US';

    // Try to get from user preferences first
    try {
        const { getPreferences } = await import('./api.js');
        const preferences = await getPreferences();

        if (preferences.ui_language && preferences.ui_language !== 'auto') {
            localeToLoad = preferences.ui_language;
        } else {
            // "auto": an explicit local choice still wins over browser detection
            localeToLoad = getStoredLocale() || detectBrowserLocale();
        }
    } catch (error) {
        // Not logged in, or preferences unavailable: prefer an explicit local
        // choice (made on the login page) over browser detection.
        localeToLoad = getStoredLocale() || detectBrowserLocale();
    }

    // Load the determined locale
    await loadLocale(localeToLoad);
}

/**
 * Detect browser's preferred language
 * @returns {string} Locale code (e.g., 'en-US')
 */
function detectBrowserLocale() {
    // Get browser languages in order of preference
    const browserLanguages = navigator.languages || [navigator.language || navigator.userLanguage || 'en-US'];

    // Try to find exact match
    for (const lang of browserLanguages) {
        if (availableLocales.includes(lang)) {
            return lang;
        }
    }

    // Try to find language match (e.g., 'pl' matches 'pl-PL')
    for (const lang of browserLanguages) {
        const langCode = lang.split('-')[0].toLowerCase();
        const match = availableLocales.find(locale =>
            locale.toLowerCase().startsWith(langCode)
        );
        if (match) {
            return match;
        }
    }

    // Default to en-US
    return 'en-US';
}

/**
 * Load translations for a specific locale
 * Falls back to en-US if locale file doesn't exist or has missing keys
 * @param {string} locale - Locale code (e.g., 'en-US')
 * @returns {Promise<void>}
 */
export async function loadLocale(locale) {
    try {
        // Always load en-US as fallback
        let fallbackTranslations = {};
        if (locale !== 'en-US') {
            try {
                const fallbackResponse = await fetch('/locales/en-US.json');
                fallbackTranslations = await fallbackResponse.json();
            } catch (error) {
                console.error('Failed to load fallback locale (en-US):', error);
            }
        }

        // Load requested locale
        const response = await fetch(`/locales/${locale}.json`);
        const localeTranslations = await response.json();

        // Merge with fallback (fallback first, then override with locale-specific)
        translations = deepMerge(fallbackTranslations, localeTranslations);
        currentLocale = locale;

        console.log(`Loaded locale: ${locale}`);
    } catch (error) {
        console.error(`Failed to load locale ${locale}, falling back to en-US:`, error);

        // Load en-US as ultimate fallback
        if (locale !== 'en-US') {
            try {
                const response = await fetch('/locales/en-US.json');
                translations = await response.json();
                currentLocale = 'en-US';
            } catch (fallbackError) {
                console.error('Failed to load fallback locale:', fallbackError);
                translations = {};
            }
        } else {
            translations = {};
        }
    }
}

/**
 * Deep merge two objects
 * @param {Object} target - Target object
 * @param {Object} source - Source object
 * @returns {Object} Merged object
 */
function deepMerge(target, source) {
    const result = { ...target };

    for (const key in source) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
            result[key] = deepMerge(result[key] || {}, source[key]);
        } else {
            result[key] = source[key];
        }
    }

    return result;
}

/**
 * Get translation for a key
 * Supports nested keys with dot notation (e.g., 'login.signIn')
 * Supports parameter replacement (e.g., 'Hello {name}' with params: {name: 'John'})
 * @param {string} key - Translation key
 * @param {Object} params - Parameters for replacement
 * @returns {string} Translated string
 */
export function t(key, params = {}) {
    // Navigate nested keys
    const keys = key.split('.');
    let value = translations;

    for (const k of keys) {
        if (value && typeof value === 'object') {
            value = value[k];
        } else {
            value = undefined;
            break;
        }
    }

    // If translation not found, return key
    if (value === undefined) {
        console.warn(`Translation missing for key: ${key}`);
        return key;
    }

    // Handle parameter replacement
    let result = String(value);
    for (const [param, val] of Object.entries(params)) {
        result = result.replace(new RegExp(`\\{${param}\\}`, 'g'), val);
    }

    return result;
}

/**
 * Whether a locale has been loaded (initI18n or setLocale ran on this page)
 * @returns {boolean}
 */
export function isI18nReady() {
    return Object.keys(translations).length > 0;
}

/**
 * Get current locale
 * @returns {string} Current locale code
 */
export function getCurrentLocale() {
    return currentLocale;
}

/**
 * Get available locales
 * @returns {Array<string>} Array of available locale codes
 */
export function getAvailableLocales() {
    return availableLocales;
}

/**
 * Set locale and reload translations
 * @param {string} locale - Locale code to set
 * @returns {Promise<void>}
 */
export async function setLocale(locale) {
    await loadLocale(locale);

    // Remember an explicit choice locally. This is what lets the language
    // switcher on the login page survive a reload, where there is no user
    // session to read a stored preference from.
    try {
        localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch (error) {
        // Private mode or blocked storage - the choice simply will not persist
    }

    // Trigger custom event for components to re-render
    document.dispatchEvent(new CustomEvent('localechange', {
        detail: { locale: currentLocale }
    }));
}

/**
 * Translate all elements with data-i18n attribute
 * Usage in HTML: <button data-i18n="login.signIn">Sign In</button>
 * With params: <button data-i18n="login.welcome" data-i18n-params='{"name":"John"}'>Welcome</button>
 */
export function translatePage() {
    const elements = document.querySelectorAll('[data-i18n]');

    elements.forEach(element => {
        const key = element.getAttribute('data-i18n');
        const paramsAttr = element.getAttribute('data-i18n-params');
        const params = paramsAttr ? JSON.parse(paramsAttr) : {};

        element.textContent = t(key, params);
    });

    // Translate placeholders
    const placeholderElements = document.querySelectorAll('[data-i18n-placeholder]');
    placeholderElements.forEach(element => {
        const key = element.getAttribute('data-i18n-placeholder');
        element.placeholder = t(key);
    });

    // Translate titles
    const titleElements = document.querySelectorAll('[data-i18n-title]');
    titleElements.forEach(element => {
        const key = element.getAttribute('data-i18n-title');
        element.title = t(key);
    });

    // Translate aria-labels, so icon-only controls are announced in the
    // active language rather than staying English for screen readers.
    const ariaElements = document.querySelectorAll('[data-i18n-aria-label]');
    ariaElements.forEach(element => {
        const key = element.getAttribute('data-i18n-aria-label');
        element.setAttribute('aria-label', t(key));
    });

    // Keep the document language in sync for correct hyphenation and
    // screen-reader pronunciation.
    document.documentElement.lang = currentLocale;
}

/**
 * Get locale name for display
 * @param {string} locale - Locale code
 * @returns {string} Display name
 */
export function getLocaleName(locale) {
    const localeNames = {
        'en-US': 'English',
        'pl-PL': 'Polish'
    };

    return localeNames[locale] || locale;
}

/**
 * Get locale code from language preference
 * Maps simplified codes to full locale codes
 * @param {string} langPref - Language preference ('auto', 'en', 'pl', etc.)
 * @returns {string} Locale code
 */
export function getLocaleFromPreference(langPref) {
    if (!langPref || langPref === 'auto') {
        return detectBrowserLocale();
    }

    const preferenceMap = {
        'en': 'en-US',
        'pl': 'pl-PL',
        'en-US': 'en-US',
        'pl-PL': 'pl-PL'
    };

    return preferenceMap[langPref] || detectBrowserLocale();
}
