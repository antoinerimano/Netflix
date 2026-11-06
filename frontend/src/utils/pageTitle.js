// The browser tab / history title of a page about one thing: "Heat | Tauruss".
// The server sends the same title in the page's HTML (backend users/seo.py) for search engines
// and link previews; this keeps it right while moving around inside the app.
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

const SITE_NAME = 'Tauruss';
let current = null;

/** The title a page set, or null (App then shows the app's own title). */
export function currentPageTitle() {
  return current;
}

export function usePageTitle(name) {
  const { t } = useTranslation();
  useEffect(() => {
    if (!name) return undefined;
    current = `${name} | ${SITE_NAME}`;
    document.title = current;
    return () => {
      current = null;
      document.title = t('meta.title');
    };
  }, [name, t]);
}
