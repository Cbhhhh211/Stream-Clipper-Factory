import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Download, LoaderCircle } from 'lucide-react';
import { api } from '../hooks/useApi';

function parseQuery() {
  const params = new URLSearchParams(window.location.search);
  return {
    orderId: params.get('order_id') || '',
    token: params.get('token') || '',
  };
}

function goHome() {
  window.history.pushState({}, '', '/');
  window.dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

export default function CheckoutSuccessPage() {
  const [{ orderId, token }] = useState(parseQuery);
  const [order, setOrder] = useState(null);
  const [error, setError] = useState('');
  const redirectedRef = useRef(false);

  useEffect(() => {
    if (!orderId || !token) {
      setError('缺少订单信息，无法确认支付状态。');
      return undefined;
    }

    let alive = true;

    async function loadStatus() {
      try {
        const payload = await api.getPublicOrder(orderId, token);
        if (!alive) return;
        setOrder(payload);
        setError('');
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : '订单查询失败');
      }
    }

    loadStatus();
    const timer = window.setInterval(loadStatus, 2500);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [orderId, token]);

  useEffect(() => {
    if (!order || redirectedRef.current) return;
    if (order.status === 'paid' && order.download_url) {
      redirectedRef.current = true;
      window.setTimeout(() => {
        window.location.href = order.download_url;
      }, 800);
    }
  }, [order]);

  return (
    <div className="marketing-shell min-h-screen bg-[#050810] px-5 py-10 text-[var(--color-text-primary)] md:px-8 md:py-14">
      <div className="marketing-grid" aria-hidden />
      <div className="mx-auto max-w-4xl">
        <div className="surface-panel p-6 md:p-8">
          <p className="section-eyebrow">Order Status</p>
          <h1 className="signal-heading mt-3 text-3xl md:text-5xl">支付状态确认中</h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[rgba(223,240,248,0.72)]">
            我们会自动轮询订单状态。Stripe 回调确认成功后，页面会自动跳转到下载链接。
          </p>

          {error ? (
            <div className="mt-6 rounded-2xl border border-[rgba(255,51,84,0.25)] bg-[rgba(255,51,84,0.08)] px-4 py-3 text-sm text-[rgba(255,223,230,0.92)]">
              {error}
            </div>
          ) : null}

          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <div className="surface-panel-soft rounded-3xl px-4 py-5">
              <div className="text-xs uppercase tracking-[0.16em] text-[rgba(223,240,248,0.55)]">Order</div>
              <div className="mt-3 break-all text-sm text-white">{orderId || '--'}</div>
            </div>
            <div className="surface-panel-soft rounded-3xl px-4 py-5">
              <div className="text-xs uppercase tracking-[0.16em] text-[rgba(223,240,248,0.55)]">Status</div>
              <div className="mt-3 text-sm text-white">{order?.status || 'waiting'}</div>
            </div>
            <div className="surface-panel-soft rounded-3xl px-4 py-5">
              <div className="text-xs uppercase tracking-[0.16em] text-[rgba(223,240,248,0.55)]">Delivery</div>
              <div className="mt-3 text-sm text-white">{order?.download_url ? 'ready' : 'pending'}</div>
            </div>
          </div>

          <div className="mt-6 rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] p-5">
            {order?.status === 'paid' && order?.download_url ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3 text-sm text-[rgba(223,240,248,0.82)]">
                  <CheckCircle2 className="h-5 w-5 text-[var(--color-success)]" />
                  支付已确认，正在为你打开下载链接。
                </div>
                <button
                  className="btn-warm rounded-2xl px-6 py-4 text-sm"
                  onClick={() => {
                    window.location.href = order.download_url;
                  }}
                >
                  立即下载
                  <Download className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-3 text-sm text-[rgba(223,240,248,0.72)]">
                <LoaderCircle className="h-5 w-5 animate-spin text-[var(--color-accent)]" />
                正在等待支付回调。如果你刚完成支付，通常几秒内会自动跳转。
              </div>
            )}
          </div>

          <button className="btn-secondary mt-6 rounded-2xl px-6 py-4 text-sm font-semibold" onClick={goHome}>
            返回官网
          </button>
        </div>
      </div>
    </div>
  );
}
