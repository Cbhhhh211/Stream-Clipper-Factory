import { Download } from 'lucide-react';
import HighlightTimeline from './HighlightTimeline';
import ClipPreview from './ClipPreview';
import ClipList from './ClipList';
import DanmakuDensity from './DanmakuDensity';
import ScoreOverview from './ScoreOverview';
import { useAppStore } from '../store/useAppStore';

export default function ReviewLayout() {
  const { state, dispatch } = useAppStore();

  const selectedCount = state.highlights.filter((h) => h.selected).length;
  const totalDuration = Math.round(
    state.highlights.reduce((sum, clip) => sum + (clip.clipEnd - clip.clipStart), 0)
  );
  const avgScore = state.highlights.length
    ? Math.round((state.highlights.reduce((sum, clip) => sum + clip.score, 0) / state.highlights.length) * 100)
    : 0;

  return (
    <div className="min-h-full w-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4">
        <section className="surface-panel px-5 py-5 md:px-7 md:py-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="mb-2 signal-label">复核</div>
              <h1 className="text-3xl font-extrabold tracking-tight text-text-primary md:text-4xl">
                保留最精彩片段，其余内容按需裁剪。
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-text-secondary">
                复核界面保持简洁：片段列表 + 预览 + 时间轴，确认后直接导出。
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <MetricChip label="已选" value={`${selectedCount}/${state.highlights.length || 0}`} />
              <MetricChip label="总时长" value={`${totalDuration}秒`} />
              <MetricChip label="平均分" value={`${avgScore}`} />
              <button
                onClick={() => dispatch({ type: 'SET_EXPORT_PLATFORM', payload: 'bilibili' })}
                disabled={selectedCount === 0}
                className="btn-warm rounded-xl px-5 py-3 text-sm"
              >
                <Download size={15} />
                导出
              </button>
            </div>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <section className="surface-panel p-4">
              <div className="mb-3 text-sm font-semibold text-text-primary">片段列表</div>
              <div className="max-h-[720px] overflow-y-auto pr-1">
                <ClipList />
              </div>
            </section>
          </aside>

          <div className="flex min-w-0 flex-col gap-4">
            <section className="surface-panel min-h-[460px] overflow-hidden p-4">
              <ClipPreview />
            </section>

            <section className="surface-panel p-4 md:p-5">
              <HighlightTimeline />
            </section>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <section className="surface-panel p-4 md:p-5">
            <DanmakuDensity />
          </section>
          <section className="surface-panel p-4 md:p-5">
            <ScoreOverview
              totalClips={state.highlights.length}
              selectedCount={selectedCount}
              totalDuration={totalDuration}
              avgScore={avgScore}
            />
          </section>
        </div>
      </div>
    </div>
  );
}

function MetricChip({ label, value }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-panel-strong px-3 py-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">{label}</span>
      <span className="ml-2 text-xs font-mono text-text-primary">{value}</span>
    </div>
  );
}
