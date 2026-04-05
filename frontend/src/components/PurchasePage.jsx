import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ExternalLink, QrCode, ShieldCheck } from 'lucide-react';
import { api } from '../hooks/useApi';

function goTo(path) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resolveCancelHint() {
  if (typeof window === 'undefined') return false;
  return new URLSearchParams(window.location.search).get('cancelled') === '1';
}

export default function PurchasePage({ productId }) {
  const [product, setProduct] = useState(null);
  const [email, setEmail] = useState('');
  const [checkout, setCheckout] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [cancelled] = useState(resolveCancelHint);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');

    api.getPublicProduct(productId)
      .then((payload) => {
        if (alive) {
          setProduct(payload);
        }
      })
      .catch((err) => {
        if (alive) {
          setError(err instanceof Error ? err.message : '无法加载产品信息');
        }
      })
      .finally(() => {
        if (alive) {
          setLoading(false);
        }
      });

    return () => {
      alive = false;
    };
  }, [productId]);

  const canSubmit = useMemo(() => /\S+@\S+\.\S+/.test(email.trim()), [email]);

  async function handleCheckout(event) {
    event.preventDefault();
    if (!canSubmit || submitting) return;

    setSubmitting(true);
    setError('');
    try {
      const payload = await api.createPublicCheckout({
        product_id: productId,
        email: email.trim(),
      });
      setCheckout(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建支付订单失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="marketing-shell min-h-screen bg-[#050810] px-5 py-10 text-[var(--color-text-primary)] md:px-8 md:py-14">
      <div className="marketing-grid" aria-hidden />
      <div className="mx-auto max-w-5xl space-y-6">
        <button className="btn-secondary rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em]" onClick={() => goTo('/')}>
          <ArrowLeft className="h-4 w-4" />
          返回官网
        </button>

        <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <section className="surface-panel p-6 md:p-8">
            <p className="section-eyebrow">Checkout</p>
            <h1 className="signal-heading mt-3 text-3xl md:text-5xl">
              {loading ? '正在加载产品...' : (product?.name || '购买流剪工坊')}
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-[rgba(223,240,248,0.72)]">
              先完成支付，再自动跳转到下载流程。下载链接会按订单生成，适合作为官网首版交付方案。
            </p>

            {cancelled ? (
              <div className="mt-6 rounded-2xl border border-[rgba(255,156,32,0.2)] bg-[rgba(255,156,32,0.08)] px-4 py-3 text-sm text-[rgba(255,234,204,0.9)]">
                你刚刚取消了支付，可以继续使用当前二维码或重新生成新订单。
              </div>
            ) : null}

            {error ? (
              <div className="mt-6 rounded-2xl border border-[rgba(255,51,84,0.25)] bg-[rgba(255,51,84,0.08)] px-4 py-3 text-sm text-[rgba(255,223,230,0.92)]">
                {error}
              </div>
            ) : null}

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <div className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-5">
                <div className="text-xs uppercase tracking-[0.16em] text-[rgba(223,240,248,0.55)]">Price</div>
                <div className="mt-3 text-4xl font-semibold text-white">{product?.price_display || '--'}</div>
              </div>
              <div className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-5">
                <div className="text-xs uppercase tracking-[0.16em] text-[rgba(223,240,248,0.55)]">Delivery</div>
                <div className="mt-3 text-lg font-semibold text-white">支付成功后自动下载</div>
                <div className="mt-2 text-sm leading-6 text-[rgba(223,240,248,0.64)]">下载链接按订单生成，适合你的首版官网闭环。</div>
              </div>
            </div>

            <div className="mt-6 rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-5 text-sm leading-7 text-[rgba(223,240,248,0.76)]">
              {product?.description || '适合把长直播回放更快处理成可发布短视频。'}
            </div>

            <form className="mt-6 space-y-4" onSubmit={handleCheckout}>
              <label className="block space-y-2">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(223,240,248,0.58)]">收货邮箱</span>
                <input
                  className="bento-input"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@example.com"
                  autoComplete="email"
                />
              </label>

              <button
                type="submit"
                className="btn-warm rounded-2xl px-6 py-4 text-sm"
                disabled={!product?.checkout_enabled || !canSubmit || submitting}
              >
                {submitting ? '生成中...' : '生成支付二维码'}
              </button>
            </form>
          </section>

          <aside className="surface-panel p-6 md:p-8">
            <p className="section-eyebrow">Payment</p>
            <div className="mt-4 rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] p-5">
              {checkout ? (
                <div className="space-y-5">
                  <div className="flex items-center gap-3 text-sm text-[rgba(223,240,248,0.7)]">
                    <QrCode className="h-5 w-5 text-[var(--color-accent)]" />
                    扫码支付后会自动跳转到下载成功页
                  </div>
                  <div className="rounded-[28px] bg-white p-4">
                    <img src={checkout.qr_svg_url} alt="支付二维码" className="mx-auto block w-full max-w-[280px]" />
                  </div>
                  <button
                    className="btn-secondary w-full rounded-2xl px-5 py-4 text-sm font-semibold"
                    onClick={() => window.open(checkout.checkout_url, '_blank', 'noopener,noreferrer')}
                  >
                    在新窗口打开支付页
                    <ExternalLink className="h-4 w-4" />
                  </button>
                  <div className="rounded-2xl border border-[rgba(0,200,255,0.18)] bg-[rgba(0,200,255,0.08)] px-4 py-3 text-sm text-[rgba(223,240,248,0.82)]">
                    如果你在手机上访问，可以直接点上面的按钮进入支付页；如果你在电脑上访问，就用手机扫码。
                  </div>
                </div>
              ) : (
                <div className="space-y-4 text-sm leading-7 text-[rgba(223,240,248,0.68)]">
                  <div className="flex items-center gap-3">
                    <ShieldCheck className="h-5 w-5 text-[var(--color-warm)]" />
                    支付完成后由后端确认订单状态，再签发下载链接
                  </div>
                  <div className="rounded-2xl border border-dashed border-white/10 px-4 py-10 text-center text-[rgba(223,240,248,0.52)]">
                    先填写邮箱并生成二维码
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
