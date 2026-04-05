import { useEffect, useMemo, useState } from 'react';
import CheckoutSuccessPage from './components/CheckoutSuccessPage';
import MarketingSite from './components/MarketingSite';
import PurchasePage from './components/PurchasePage';
import StudioApp from './components/StudioApp';

function resolvePathname() {
  if (typeof window === 'undefined') return '/';
  return window.location.pathname || '/';
}

function isDesktopShell() {
  return typeof window !== 'undefined' && Boolean(window.streamClipperDesktop);
}

function resolveRoute(pathname) {
  if (isDesktopShell()) {
    return { kind: 'studio' };
  }

  if (pathname === '/studio' || pathname === '/app') {
    return { kind: 'studio' };
  }

  if (pathname === '/checkout/success') {
    return { kind: 'checkout-success' };
  }

  const purchaseMatch = pathname.match(/^\/buy\/([a-z0-9_-]+)$/i);
  if (purchaseMatch) {
    return { kind: 'purchase', productId: purchaseMatch[1].toLowerCase() };
  }

  return { kind: 'marketing' };
}

export default function App() {
  const [pathname, setPathname] = useState(resolvePathname);
  const route = useMemo(() => resolveRoute(pathname), [pathname]);
  const studioMode = route.kind === 'studio';

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

  if (route.kind === 'studio') {
    return <StudioApp />;
  }

  if (route.kind === 'purchase') {
    return <PurchasePage productId={route.productId} />;
  }

  if (route.kind === 'checkout-success') {
    return <CheckoutSuccessPage />;
  }

  return <MarketingSite />;
}
