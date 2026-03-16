import { useState } from 'react';
import { Download, BrainCircuit } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';

const SCORE_BANDS = [
  { label: '75-100', min: 0.75, max: 1.01, color: 'rgba(210,161,99,0.85)' },
  { label: '50-74', min: 0.5, max: 0.75, color: 'rgba(127,174,210,0.78)' },
  { label: '25-49', min: 0.25, max: 0.5, color: 'rgba(127,174,210,0.45)' },
  { label: '0-24', min: 0, max: 0.25, color: 'rgba(201,215,230,0.9)' },
];

export default function ScoreOverview({ totalClips, selectedCount, totalDuration, avgScore }) {
  const { state, dispatch } = useAppStore();
  const [retraining, setRetraining] = useState(false);

  const handleRetrain = async () => {
    setRetraining(true);
    try {
      await api.retrainFeedbackModel({});
    } catch {
      // Keep current model if retraining fails.
    } finally {
      setRetraining(false);
    }
  };

  const highlights = state.highlights;
  const maxBandCount = Math.max(
    1,
    ...SCORE_BANDS.map((band) => highlights.filter((h) => h.score >= band.min && h.score < band.max).length)
  );

  return (
    <div className="flex h-full flex-col justify-between">
      <div>
        <div className="mb-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">分析</div>
          <h3 className="mt-1 text-lg font-semibold text-text-primary">评分概览</h3>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-3">
          <StatCard label="已保留片段" value={`${selectedCount}/${totalClips}`} />
          <StatCard label="平均分" value={`${avgScore}`} />
          <StatCard label="总时长" value={`${totalDuration}秒`} />
          <StatCard label="平均片长" value={`${selectedCount > 0 ? Math.max(1, Math.round(totalDuration / selectedCount)) : 0}秒`} />
        </div>

        {highlights.length > 0 && (
          <div>
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-muted">分布</div>
            <div className="space-y-2.5">
              {SCORE_BANDS.map((band) => {
                const count = highlights.filter((h) => h.score >= band.min && h.score < band.max).length;
                const barW = (count / maxBandCount) * 100;
                return (
                  <div key={band.label} className="flex items-center gap-3">
                    <span className="w-12 shrink-0 text-right text-[10px] font-mono text-text-muted">{band.label}</span>
                    <div className="h-[7px] flex-1 overflow-hidden rounded-full bg-[#20364f]">
                      <div className="h-full rounded-full" style={{ width: `${barW}%`, background: band.color }} />
                    </div>
                    <span className="w-4 shrink-0 text-[11px] font-mono text-text-secondary">{count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="mt-6 flex gap-3">
        <button
          onClick={() => dispatch({ type: 'SET_EXPORT_PLATFORM', payload: 'bilibili' })}
          className="btn-warm flex-1 rounded-full px-5 py-3 text-sm"
        >
          <Download size={15} />
          导出
        </button>
        <button
          onClick={handleRetrain}
          disabled={retraining}
          title="重新训练反馈模型"
          className="btn-secondary rounded-full px-5"
        >
          <BrainCircuit size={16} className={retraining ? 'animate-pulse' : ''} />
        </button>
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-[18px] border border-white/8 bg-[#12283e] px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">{label}</div>
      <div className="mt-2 text-2xl font-extrabold tracking-[-0.04em] text-text-primary">{value}</div>
    </div>
  );
}
