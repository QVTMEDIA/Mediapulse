import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'mediapulse.theme';

function readSavedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved === 'light' || saved === 'dark' ? saved : null;
  } catch {
    return null;
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false;
}

// Three-state convention (see index.html's inline script and styles.css's
// own comment above the dark-mode tokens): no saved choice follows the OS/
// browser preference and stays in sync with it live; once the user toggles,
// that choice is explicit, persisted, and no longer moves with the system
// setting. data-theme on <html> is always kept in sync with the resolved
// value here, even in the "following system" case -- simpler than leaving
// it unset and relying on the bare media query once React has mounted.
export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [hasExplicitChoice, setHasExplicitChoice] = useState(() => readSavedTheme() !== null);
  const [theme, setTheme] = useState<Theme>(() => readSavedTheme() ?? (systemPrefersDark() ? 'dark' : 'light'));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (hasExplicitChoice || !window.matchMedia) return;
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setTheme(query.matches ? 'dark' : 'light');
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [hasExplicitChoice]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // Private browsing / storage disabled -- the toggle still works
        // for this session, it just won't be remembered next visit.
      }
      return next;
    });
    setHasExplicitChoice(true);
  }, []);

  return { theme, toggleTheme };
}
