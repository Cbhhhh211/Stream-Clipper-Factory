export const defaultSiteConfig = {
  brandName: '流剪工坊',
  heroBadge: 'AI Highlight Engine for Creators',
  headline: '把长直播回放更快变成可发布的短视频素材',
  subheadline:
    '面向主播、剪辑师和小团队的本地 AI 切片工具。导入素材后自动转写、打分、生成候选片段，再由人工快速复核导出。',
  contactEmail: 'founder@example.com',
  bookingUrl: 'mailto:founder@example.com?subject=Stream%20Clipper%20Demo',
  downloadUrl: '/buy/studio',
  demoUrl: '/studio',
  pricing: [
    {
      name: '创作者版',
      price: 'CNY 9.9',
      description: '适合个人主播和兼职剪辑，先跑通从直播回放到短视频的基础工作流。',
      bullets: ['本地导入与自动切片', '候选片段复核与导出', '适合每天 1-2 场直播'],
      ctaLabel: '立即购买',
      ctaUrl: '/buy/creator',
      featured: false,
    },
    {
      name: '工作室版',
      price: 'CNY 29.9',
      description: '适合小团队和工作室，强调更稳定的交付效率与更清晰的售后支持。',
      bullets: ['推荐作为主推成交款', '更适合高频批量任务', '优先支持与交付说明'],
      ctaLabel: '购买工作室版',
      ctaUrl: '/buy/studio',
      featured: true,
    },
    {
      name: '团队定制',
      price: 'CNY 999+',
      description: '适合机构和团队部署，按你的流程、培训和服务范围定制。',
      bullets: ['定制部署与培训', '团队售后与支持', '商务咨询与方案沟通'],
      ctaLabel: '预约咨询',
      ctaUrl: 'mailto:founder@example.com?subject=Stream%20Clipper%20Demo',
      featured: false,
    },
  ],
};

export function normalizeSiteConfig(value) {
  const incoming = value && typeof value === 'object' ? value : {};
  const pricing = Array.isArray(incoming.pricing) && incoming.pricing.length
    ? incoming.pricing
    : defaultSiteConfig.pricing;

  return {
    ...defaultSiteConfig,
    ...incoming,
    pricing: pricing.map((plan, index) => ({
      ...defaultSiteConfig.pricing[index % defaultSiteConfig.pricing.length],
      ...plan,
      bullets: Array.isArray(plan?.bullets) && plan.bullets.length
        ? plan.bullets
        : defaultSiteConfig.pricing[index % defaultSiteConfig.pricing.length].bullets,
    })),
  };
}
