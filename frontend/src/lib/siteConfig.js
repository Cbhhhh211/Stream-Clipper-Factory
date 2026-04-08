export const defaultSiteConfig = {
  brandName: 'Stream Clipper',
  heroBadge: 'AI Highlight Engine for Creators',
  headline: '把长直播切成能发、能涨粉、能成交的短视频。',
  subheadline:
    '面向主播、切片团队和内容工作室的本地 AI 高光剪辑工具。导入视频后自动转写、打分、出片、复核、导出。',
  contactEmail: 'founder@example.com',
  bookingUrl: 'mailto:founder@example.com?subject=Stream%20Clipper%20Demo',
  downloadUrl: '/studio',
  demoUrl: '/studio',
  pricing: [
    {
      name: '创作者版',
      price: '¥99 / 月',
      description: '给单人创作者和主播，快速把一场直播拆成多个可发片段。',
      bullets: ['本地导入与自动切片', '剪辑复核与批量导出', '适合每天 1-2 场直播'],
      ctaLabel: '立即开通',
      ctaUrl: '',
      featured: false,
    },
    {
      name: '工作室版',
      price: '¥299 / 月',
      description: '给小团队和职业切片号，追求更稳定的出片效率和复用能力。',
      bullets: ['反馈学习与边界微调', '更适合高频批量任务', '优先支持定制流程'],
      ctaLabel: '购买工作室版',
      ctaUrl: '',
      featured: true,
    },
    {
      name: '团队定制',
      price: '¥999 起 / 月',
      description: '给 MCN、品牌直播团队和企业内容团队，按流程与数据要求定制。',
      bullets: ['私有部署或内部流程接入', '批量任务和协作方案', '专属培训与支持'],
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
