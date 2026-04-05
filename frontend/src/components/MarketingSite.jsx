import { useEffect, useState } from 'react';
import { ArrowRight, CirclePlay, Coins, Download, Layers3, Sparkles, WandSparkles } from 'lucide-react';
import MarketingLeadForm from './MarketingLeadForm';
import { api } from '../hooks/useApi';
import { defaultSiteConfig, normalizeSiteConfig } from '../lib/siteConfig';

const signals = [
  { value: '3 步', label: '导入、复核、导出' },
  { value: '45 秒', label: '默认候选片段时长' },
  { value: '本地优先', label: '更适合素材安全和低门槛试用' },
];

const workflow = [
  {
    title: '导入长素材',
    body: '支持本地视频、回放链接和直播素材来源，让你不用先做繁琐整理就能开始处理。',
    icon: Download,
  },
  {
    title: '自动找高光',
    body: '基于转写、音频和内容线索先给你候选片段，不用再从几小时素材里反复翻找。',
    icon: Sparkles,
  },
  {
    title: '人工复核更快',
    body: '把真正有价值的人工判断，留在最后几分钟完成，适合真实交付而不是只看演示。',
    icon: WandSparkles,
  },
];

const offers = [
  '卖创作者效率工具：给个人主播和兼职剪辑提供更快的切片工作流。',
  '卖工作室交付工具：给小团队提升稳定出片效率，缩短翻素材时间。',
  '卖团队定制服务：给机构或 MCN 做流程梳理、部署和培训。',
];

const channelPlan = [
  '小红书：发效率对比、案例复盘、工作流拆解，用内容种草拉私信。',
  '抖音：发 15-30 秒的前后对比视频，直接打“直播回放没人剪”的痛点。',
  '私域：把线索沉淀到微信或邮箱，按主播、剪辑师、工作室三类跟进。',
  '官网：负责解释价值、承接支付、自动发货和试用申请。',
];

const faq = [
  {
    q: '适合先卖给谁？',
    a: '最适合已经有直播回放素材、但缺稳定切片效率的人：主播本人、兼职剪辑师和小型工作室。',
  },
  {
    q: '为什么先做官网而不是直接卖安装包？',
    a: '因为官网负责把价值讲清楚、承接支付和线索；安装包是交付形式，不是转化入口。',
  },
  {
    q: '这个工具是云端还是本地？',
    a: '现在主打本地交付，更适合早期售卖，也更容易让用户接受素材安全和交付稳定性。',
  },
];

function openLink(url) {
  if (!url) return;
  if (url.startsWith('/')) {
    window.history.pushState({}, '', url);
    window.dispatchEvent(new PopStateEvent('popstate'));
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

function scrollToLeadForm() {
  document.getElementById('lead-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function MarketingSite() {
  const [siteConfig, setSiteConfig] = useState(defaultSiteConfig);

  useEffect(() => {
    let alive = true;
    api.getPublicSiteConfig()
      .then((payload) => {
        if (alive) {
          setSiteConfig(normalizeSiteConfig(payload));
        }
      })
      .catch(() => {
        if (alive) {
          setSiteConfig(defaultSiteConfig);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="marketing-shell min-h-screen bg-[#050810] text-[var(--color-text-primary)]">
      <div className="marketing-grid" aria-hidden />

      <header className="sticky top-0 z-30 border-b border-white/8 bg-[rgba(5,8,16,0.78)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 md:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[rgba(0,200,255,0.25)] bg-[rgba(0,200,255,0.08)]">
              <Layers3 className="h-5 w-5 text-[var(--color-accent)]" />
            </div>
            <div>
              <div className="display-font text-lg uppercase tracking-[0.22em] text-[var(--color-accent)]">{siteConfig.brandName}</div>
              <div className="text-xs text-[rgba(223,240,248,0.55)]">Launch-ready creator clipping system</div>
            </div>
          </div>

          <div className="hidden items-center gap-3 md:flex">
            <button className="btn-secondary rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em]" onClick={() => openLink('/studio')}>
              在线演示
            </button>
            <button className="btn-warm rounded-full px-5 py-3 text-xs" onClick={scrollToLeadForm}>
              预约演示
            </button>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden px-5 pb-14 pt-14 md:px-8 md:pb-24 md:pt-20">
          <div className="mx-auto grid max-w-7xl gap-10 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-7">
              <div className="inline-flex items-center gap-2 rounded-full border border-[rgba(255,156,32,0.2)] bg-[rgba(255,156,32,0.08)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(255,220,183,0.85)]">
                <Coins className="h-4 w-4" />
                {siteConfig.heroBadge}
              </div>

              <div className="space-y-5">
                <h1 className="signal-heading max-w-4xl text-5xl leading-none md:text-7xl">
                  {siteConfig.headline}
                </h1>
                <p className="max-w-2xl text-base leading-8 text-[rgba(223,240,248,0.74)] md:text-lg">
                  {siteConfig.subheadline}
                </p>
              </div>

              <div className="flex flex-col gap-4 sm:flex-row">
                <button className="btn-warm rounded-2xl px-6 py-4 text-sm" onClick={() => openLink(siteConfig.downloadUrl)}>
                  <Download className="h-4 w-4" />
                  立即购买 / 获取下载
                </button>
                <button className="btn-secondary rounded-2xl px-6 py-4 text-sm font-semibold" onClick={() => openLink(siteConfig.demoUrl)}>
                  进入演示
                  <CirclePlay className="h-4 w-4" />
                </button>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                {signals.map((item) => (
                  <div key={item.label} className="surface-panel-soft rounded-3xl px-4 py-5">
                    <div className="display-font text-3xl text-white">{item.value}</div>
                    <div className="mt-2 text-sm leading-6 text-[rgba(223,240,248,0.6)]">{item.label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="relative">
              <div className="marketing-orb marketing-orb-cyan" aria-hidden />
              <div className="marketing-orb marketing-orb-warm" aria-hidden />
              <div className="monitor-frame relative overflow-hidden rounded-[28px] border border-[rgba(0,200,255,0.2)] p-5 md:p-6">
                <div className="relative z-10 space-y-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="signal-label">Revenue View</div>
                      <div className="signal-heading text-3xl">不是“剪辑软件”</div>
                    </div>
                    <div className="flex gap-2">
                      <span className="led-dot led-dot-active" />
                      <span className="led-dot led-dot-warm" />
                    </div>
                  </div>

                  <div className="grid gap-4">
                    <div className="rounded-3xl border border-white/8 bg-[rgba(6,16,28,0.92)] p-5">
                      <div className="text-xs uppercase tracking-[0.18em] text-[rgba(223,240,248,0.45)]">Sell this as</div>
                      <div className="mt-3 grid gap-3">
                        <div className="rounded-2xl border border-[rgba(0,200,255,0.16)] bg-[rgba(0,200,255,0.08)] px-4 py-3 text-sm text-[rgba(223,240,248,0.86)]">创作者提效工具</div>
                        <div className="rounded-2xl border border-[rgba(255,156,32,0.18)] bg-[rgba(255,156,32,0.08)] px-4 py-3 text-sm text-[rgba(255,240,220,0.88)]">工作室交付工具</div>
                        <div className="rounded-2xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-4 py-3 text-sm text-[rgba(223,240,248,0.72)]">团队定制服务入口</div>
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.04)] p-5">
                        <div className="signal-label">Output</div>
                        <div className="mt-2 text-xl font-semibold text-white">候选高光片段</div>
                        <div className="mt-3 text-sm leading-6 text-[rgba(223,240,248,0.62)]">先给你值得发的片段，再由人工做最后的判断与微调。</div>
                      </div>
                      <div className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.04)] p-5">
                        <div className="signal-label">Monetization</div>
                        <div className="mt-2 text-xl font-semibold text-white">支付、下载、售后</div>
                        <div className="mt-3 text-sm leading-6 text-[rgba(223,240,248,0.62)]">官网负责成交与自动交付，桌面版负责真正的使用和留存。</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="px-5 py-10 md:px-8 md:py-14">
          <div className="mx-auto grid max-w-7xl gap-5 md:grid-cols-3">
            {workflow.map((step) => {
              const Icon = step.icon;
              return (
                <article key={step.title} className="surface-panel marketing-card p-6 md:p-7">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/5">
                    <Icon className="h-5 w-5 text-[var(--color-accent)]" />
                  </div>
                  <h2 className="mt-5 text-2xl font-semibold text-white">{step.title}</h2>
                  <p className="mt-3 text-sm leading-7 text-[rgba(223,240,248,0.66)]">{step.body}</p>
                </article>
              );
            })}
          </div>
        </section>

        <section className="px-5 py-10 md:px-8 md:py-14">
          <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="surface-panel p-6 md:p-8">
              <p className="section-eyebrow">How It Makes Money</p>
              <h2 className="signal-heading mt-3 text-3xl md:text-4xl">这套产品现在就能承接的三种收入</h2>
              <div className="mt-6 space-y-4">
                {offers.map((offer) => (
                  <div key={offer} className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-4 text-sm leading-7 text-[rgba(223,240,248,0.78)]">
                    {offer}
                  </div>
                ))}
              </div>
            </div>

            <div className="surface-panel p-6 md:p-8">
              <p className="section-eyebrow">Channel Plan</p>
              <h2 className="signal-heading mt-3 text-3xl md:text-4xl">宣传不是一句“帮我推广”</h2>
              <div className="mt-6 grid gap-4">
                {channelPlan.map((item) => (
                  <div key={item} className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-4 text-sm leading-7 text-[rgba(223,240,248,0.76)]">
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="px-5 py-10 md:px-8 md:py-14">
          <div className="mx-auto max-w-7xl">
            <div className="mb-6">
              <p className="section-eyebrow">Pricing</p>
              <h2 className="signal-heading mt-3 text-3xl md:text-4xl">先用轻量定价开单，再根据成交继续迭代</h2>
            </div>

            <div className="grid gap-5 lg:grid-cols-3">
              {siteConfig.pricing.map((plan) => (
                <article
                  key={plan.name}
                  className={`surface-panel p-6 md:p-7 ${plan.featured ? 'marketing-card-featured' : ''}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="display-font text-sm uppercase tracking-[0.2em] text-[rgba(223,240,248,0.55)]">{plan.name}</div>
                      <div className="mt-4 text-4xl font-semibold text-white">{plan.price}</div>
                    </div>
                    {plan.featured ? (
                      <span className="rounded-full border border-[rgba(255,156,32,0.25)] bg-[rgba(255,156,32,0.08)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[rgba(255,220,183,0.88)]">
                        主推
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-4 text-sm leading-7 text-[rgba(223,240,248,0.68)]">{plan.description}</p>
                  <div className="mt-6 space-y-3">
                    {plan.bullets.map((bullet) => (
                      <div key={bullet} className="rounded-2xl border border-white/8 bg-white/4 px-4 py-3 text-sm text-[rgba(223,240,248,0.78)]">
                        {bullet}
                      </div>
                    ))}
                  </div>
                  <button
                    className={`mt-6 w-full rounded-2xl px-5 py-4 text-sm ${plan.featured ? 'btn-warm' : 'btn-secondary font-semibold'}`}
                    onClick={() => (plan.ctaUrl ? openLink(plan.ctaUrl) : scrollToLeadForm())}
                  >
                    {plan.ctaLabel}
                  </button>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="lead-form" className="px-5 py-10 md:px-8 md:py-14">
          <div className="mx-auto max-w-7xl">
            <MarketingLeadForm contactEmail={siteConfig.contactEmail} />
          </div>
        </section>

        <section className="px-5 pb-20 pt-6 md:px-8">
          <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="surface-panel p-6 md:p-8">
              <p className="section-eyebrow">FAQ</p>
              <div className="mt-5 space-y-4">
                {faq.map((item) => (
                  <div key={item.q} className="rounded-3xl border border-white/8 bg-[rgba(255,255,255,0.03)] px-5 py-5">
                    <div className="text-lg font-semibold text-white">{item.q}</div>
                    <div className="mt-2 text-sm leading-7 text-[rgba(223,240,248,0.7)]">{item.a}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="surface-panel p-6 md:p-8">
              <p className="section-eyebrow">CTA</p>
              <h2 className="signal-heading mt-3 text-3xl md:text-4xl">你现在最该做的不是继续堆功能</h2>
              <p className="mt-4 text-sm leading-7 text-[rgba(223,240,248,0.72)]">
                而是先把产品带到用户面前，拿到第一批真实线索、第一批试用和第一笔收入。你已经有核心能力，现在缺的是面向市场的入口和成交链路。
              </p>
              <div className="mt-6 flex flex-col gap-4">
                <button className="btn-warm rounded-2xl px-6 py-4 text-sm" onClick={() => openLink(siteConfig.downloadUrl)}>
                  <Download className="h-4 w-4" />
                  购买并下载产品
                </button>
                <button className="btn-secondary rounded-2xl px-6 py-4 text-sm font-semibold" onClick={() => openLink(siteConfig.bookingUrl)}>
                  预约演示 / 商务咨询
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
