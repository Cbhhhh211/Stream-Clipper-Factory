import { useAppStore } from '../store/useAppStore';
import { MessageSquare } from 'lucide-react';

export default function DanmakuDensity() {
  const { state, dispatch } = useAppStore();
  const highlights = state.highlights;
  const maxDanmaku = Math.max(1, ...highlights.map((h) => h.danmakuCount));

  const formatTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="signal-label">互动</div>
          <h3 className="mt-1 text-base font-semibold text-text-primary">弹幕密度</h3>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/8 text-accent">
          <MessageSquare size={15} />
        </div>
      </div>

      <div className="flex min-h-[220px] flex-1 items-end gap-1 rounded-xl border border-[var(--color-border)] bg-black/20 px-3 py-4">
        {highlights.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-sm text-text-muted">暂无数据</div>
        ) : (
          highlights.map((clip, i) => {
            const densityH = Math.max(10, (clip.danmakuCount / maxDanmaku) * 100);
            const isSelected = clip.id === state.selectedClipId;

            return (
              <button
                key={clip.id}
                onClick={() => dispatch({ type: 'SELECT_CLIP', payload: clip.id })}
                className="group relative flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-end gap-1"
                title={`${formatTime(clip.clipStart)} · ${clip.danmakuCount} 条弹幕`}
              >
                <div
                  className={`w-full rounded-t-sm transition-opacity ${
                    isSelected ? 'opacity-100' : 'opacity-70 group-hover:opacity-100'
                  }`}
                  style={{
                    height: `${densityH}%`,
                    background: isSelected
                      ? 'linear-gradient(to top, var(--color-warm), var(--color-accent))'
                      : 'linear-gradient(to top, rgba(124,109,238,0.5), rgba(124,109,238,0.12))',
                  }}
                />
                {(i === 0 || i === highlights.length - 1 || i % Math.max(1, Math.floor(highlights.length / 5)) === 0) && (
                  <span className="absolute -bottom-5 text-[8px] font-mono text-text-muted">{formatTime(clip.clipStart)}</span>
                )}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
