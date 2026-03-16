import { Scissors, RotateCcw } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

const PHASES = ['import', 'processing', 'review', 'export'];
const LABELS = {
  import: '导入',
  processing: '处理中',
  review: '复核',
  export: '导出',
};

export default function Header() {
  const { state, dispatch } = useAppStore();
  const currentIdx = PHASES.indexOf(state.phase);

  return (
    <header className="relative z-40 shrink-0 border-b border-white/8 bg-[#15263a]/92 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1560px] items-center justify-between gap-4 px-4 md:h-18 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[linear-gradient(145deg,#9ebfdb_0%,#7faed2_100%)] text-white">
            <Scissors size={18} strokeWidth={2.1} />
          </div>
          <div className="min-w-0">
            <div className="truncate text-lg font-extrabold tracking-[-0.04em] text-text-primary">
              流剪工坊
            </div>
            <div className="hidden text-xs text-text-muted md:block">
              面向创作者的高效高光剪辑流程
            </div>
          </div>
        </div>

        <nav className="hidden items-center gap-2 rounded-full border border-white/8 bg-[#1a2c41] px-2 py-2 md:flex">
          {PHASES.map((phase, index) => {
            const isActive = state.phase === phase;
            const isPast = currentIdx > index;
            return (
              <div key={phase} className="flex items-center">
                {index > 0 && <div className="mx-1 h-px w-6 bg-white/8" />}
                <div
                  className={`rounded-full px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] ${
                    isActive
                      ? 'bg-[#29384a] text-text-primary shadow-sm'
                      : isPast
                        ? 'text-text-secondary'
                        : 'text-text-muted'
                  }`}
                >
                  {LABELS[phase]}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <div className="rounded-full border border-white/8 bg-[#1a2c41] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-text-muted md:hidden">
            {LABELS[state.phase]}
          </div>
          {state.phase !== 'import' && (
            <button
              onClick={() => dispatch({ type: 'RESET' })}
              className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-[#1a2c41] px-3.5 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-text-secondary transition-colors hover:bg-[#24384f] hover:text-text-primary"
            >
              <RotateCcw size={13} />
              <span className="hidden sm:inline">新建</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
