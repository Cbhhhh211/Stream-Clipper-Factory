import { useMemo, useState } from 'react';
import { api } from '../hooks/useApi';

const initialForm = {
  name: '',
  email: '',
  role: 'creator',
  platform: 'bilibili',
  goal: '',
  monthlyBudget: '',
  notes: '',
};

export default function MarketingLeadForm({ contactEmail = 'founder@example.com' }) {
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState({ type: 'idle', text: '' });
  const [submitting, setSubmitting] = useState(false);

  const isValid = useMemo(() => {
    return form.name.trim().length >= 2 && /\S+@\S+\.\S+/.test(form.email.trim());
  }, [form.email, form.name]);

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!isValid || submitting) return;

    setSubmitting(true);
    setStatus({ type: 'idle', text: '' });
    try {
      await api.submitLead({
        ...form,
        source: 'marketing-site',
      });
      setForm(initialForm);
      setStatus({
        type: 'success',
        text: `已记录你的需求，我们会通过 ${contactEmail} 或你填写的邮箱尽快联系你。`,
      });
    } catch (error) {
      setStatus({
        type: 'error',
        text: error instanceof Error ? error.message : '线索提交失败，请稍后重试。',
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="surface-panel marketing-form space-y-4 p-6 md:p-7">
      <div className="space-y-2">
        <p className="section-eyebrow">Start Selling</p>
        <h3 className="signal-heading text-2xl md:text-3xl">获取试用、演示和付费线索</h3>
        <p className="max-w-xl text-sm leading-6 text-[rgba(223,240,248,0.72)]">
          这不是“留个微信以后再说”的空表单。它会把线索写入后端，方便你后续做邀测、跟进和成交。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">称呼</span>
          <input
            className="bento-input"
            value={form.name}
            onChange={(event) => updateField('name', event.target.value)}
            placeholder="例如：阿南 / 星空工作室"
            required
          />
        </label>
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">邮箱</span>
          <input
            className="bento-input"
            type="email"
            value={form.email}
            onChange={(event) => updateField('email', event.target.value)}
            placeholder="name@example.com"
            required
          />
        </label>
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">身份</span>
          <select
            className="bento-input"
            value={form.role}
            onChange={(event) => updateField('role', event.target.value)}
          >
            <option value="creator">主播 / 创作者</option>
            <option value="editor">剪辑师 / 切片团队</option>
            <option value="brand">品牌 / 商家</option>
            <option value="mcn">MCN / 机构</option>
          </select>
        </label>
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">主要平台</span>
          <select
            className="bento-input"
            value={form.platform}
            onChange={(event) => updateField('platform', event.target.value)}
          >
            <option value="bilibili">Bilibili</option>
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
            <option value="kuaishou">快手</option>
            <option value="youtube">YouTube</option>
          </select>
        </label>
      </div>

      <label className="space-y-2">
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">你的目标</span>
        <input
          className="bento-input"
          value={form.goal}
          onChange={(event) => updateField('goal', event.target.value)}
          placeholder="例如：一场 3 小时直播，30 分钟内产出 10 条可发切片"
        />
      </label>

      <div className="grid gap-4 md:grid-cols-[0.8fr_1.2fr]">
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">预算区间</span>
          <input
            className="bento-input"
            value={form.monthlyBudget}
            onChange={(event) => updateField('monthlyBudget', event.target.value)}
            placeholder="例如：100-300 元 / 月"
          />
        </label>
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[rgba(223,240,248,0.58)]">补充说明</span>
          <textarea
            className="bento-input min-h-28 resize-y"
            value={form.notes}
            onChange={(event) => updateField('notes', event.target.value)}
            placeholder="你现在用什么方式剪片、最痛的环节是什么、希望什么时候开始试用。"
          />
        </label>
      </div>

      <div className="flex flex-col gap-3 border-t border-white/8 pt-4 md:flex-row md:items-center md:justify-between">
        <div className="text-sm text-[rgba(223,240,248,0.62)]">
          提交后会写入销售线索池，便于后续邀测、转化和复购跟进。
        </div>
        <button
          type="submit"
          className="btn-warm rounded-2xl px-6 py-4 text-sm"
          disabled={!isValid || submitting}
        >
          {submitting ? '提交中...' : '申请试用 / 咨询'}
        </button>
      </div>

      {status.text ? (
        <div
          className={`rounded-2xl border px-4 py-3 text-sm ${
            status.type === 'success'
              ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-100'
              : 'border-rose-400/25 bg-rose-400/10 text-rose-100'
          }`}
        >
          {status.text}
        </div>
      ) : null}
    </form>
  );
}
