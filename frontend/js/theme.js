/**
 * Light / dark theme from the user's preference ("system" follows the OS).
 * Shared by the explorer, the Admin Panel and the manager view.
 */

function getSystemTheme() {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

/**
 * Apply a theme setting ('system', 'light' or 'dark') to the page.
 */
export function applyTheme(theme) {
    const effectiveTheme = theme === 'system' ? getSystemTheme() : theme;
    document.body.setAttribute('data-theme', effectiveTheme);

    // Store current theme setting for system theme change listener
    window._currentThemeSetting = theme;
}

/**
 * While the setting is 'system', follow OS/browser theme changes.
 */
export function setupSystemThemeListener() {
    if (window.matchMedia) {
        const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
        darkModeQuery.addEventListener('change', (e) => {
            if (window._currentThemeSetting === 'system') {
                document.body.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    }
}

/**
 * Apply the theme saved in the user's preferences.
 */
export async function loadAndApplyTheme() {
    try {
        const { getPreferences } = await import('./api.js');
        const preferences = await getPreferences();
        applyTheme(preferences.ui_theme || 'system');
    } catch (error) {
        console.error('Failed to load theme preference:', error);
        applyTheme('system');
    }
    setupSystemThemeListener();
}
