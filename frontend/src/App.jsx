import { useEffect, useState } from 'react';
import MarketingSite from './components/MarketingSite';
import StudioApp from './components/StudioApp';

function resolvePathname() {
  if (typeof window === 'undefined') return '/';
  return window.location.pathname || '/';
}

function isDesktopShell() {
  return typeof window !== 'undefined' && Boolean(window.streamClipperDesktop);
}

function shouldRenderStudio(pathname) {
  if (isDesktopShell()) {
    return true;
  }
  return pathname === '/studio' || pathname === '/app';
}

export default function App() {
  const [pathname, setPathname] = useState(resolvePathname);
  const studioMode = shouldRenderStudio(pathname);

  useEffect(() => {
    const onPopState = () => setPathname(resolvePathname());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    const body = document.body;
    const root = document.getElementById('root');
    body.classList.toggle('marketing-mode', !studioMode);
    body.classList.toggle('studio-mode', studioMode);
    root?.classList.toggle('marketing-root', !studioMode);
    root?.classList.toggle('studio-root', studioMode);
    return () => {
      body.classList.remove('marketing-mode', 'studio-mode');
      root?.classList.remove('marketing-root', 'studio-root');
    };
  }, [studioMode]);

  if (studioMode) {
    return <StudioApp />;
  }

  return <MarketingSite />;
}
