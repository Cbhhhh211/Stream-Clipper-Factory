import { CheckCircle2 } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function ClipList() {
  const { state, dispatch } = useAppStore();

  return (
    <div className="flex flex-col gap-1.5">
      {state.highlights.map((clip, idx) => {
        const isActive = clip.id === state.selectedClipId;
        const description = clip.contentSummary || clip.topKeywords?.slice(0, 2).join(' · ') || '暂无摘要';

        return (
          <button
            key={clip.id}
            onClick={() => dispatch({ type: 'SELECT_CLIP', payload: clip.id })}
            className={`w-full rounded-xl border px-3.5 py-3 text-left transition-all duration-200 ${
              isActive
                ? 'border-accent/20 bg-accent/5'
                : 'border-[var(--color-border)] bg-panel-strong hover:bg-bg-hover'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold text-text-muted">
                  片段 {String(idx + 1).padStart(2, '0')}
                </div>
                <div className="mt-1 text-sm font-semibold text-text-primary">
                  {formatTime(clip.clipStart)} - {formatTime(clip.clipEnd)}
                </div>
              </div>
              <div className="text-xs font-mono text-text-muted">{Math.round((clip.score || 0) * 100)}</div>
            </div>
            <div className="mt-1.5 text-sm leading-5 text-text-secondary line-clamp-2">{description}</div>
            <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
              <span>{Math.max(0, Math.round(clip.clipEnd - clip.clipStart))}秒</span>
              {clip.selected && (
                <span className="inline-flex items-center gap-1 text-success">
                  <CheckCircle2 size={11} />
                  已保留
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
