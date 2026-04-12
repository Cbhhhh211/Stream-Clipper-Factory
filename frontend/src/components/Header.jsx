import { RotateCcw, Check } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

const PHASES = ['import', 'processing', 'review', 'export'];
const LABELS = { import: '导入', processing: '处理', review: '复核', export: '导出' };

export default function Header() {
  const { state, dispatch } = useAppStore();
  const currentIdx = PHASES.indexOf(state.phase);

  return (
    <header className="header-signal relative z-40 shrink-0">
      <div className="mx-auto flex h-14 max-w-[1560px] items-center justify-between gap-4 px-4 md:px-6">

        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-bold"
            style={{
              background: 'var(--color-accent)',
              color: '#fff',
            }}
          >
            S
          </div>
          <div>
            <div className="text-sm font-bold text-text-primary tracking-tight">
              流剪工坊
            </div>
            <div className="text-[10px] font-medium text-text-muted tracking-wide font-mono hidden md:block">
              Stream Clipper
            </div>
          </div>
        </div>

        {/* Phase Stepper */}
        <nav className="hidden items-center gap-1 md:flex">
          {PHASES.map((phase, index) => {
            const isActive = state.phase === phase;
            const isPast = currentIdx > index;
            return (
              <div key={phase} className="flex items-center">
                {index > 0 && (
                  <div
                    className="mx-2 h-px w-8 rounded-full transition-all duration-400"
                    style={{
                      background: isPast
                        ? 'rgba(124, 109, 238, 0.35)'
                        : 'var(--color-border)',
                    }}
                  />
                )}
                <div className="flex items-center gap-2">
                  <div
                    className="flex h-6 w-6 items-center justify-center rounded-md text-[11px] font-bold transition-all duration-300"
                    style={{
                      background: isActive
                        ? 'var(--color-accent)'
                        : isPast
                          ? 'var(--color-accent-dim)'
                          : 'transparent',
                      border: `1px solid ${isActive ? 'var(--color-accent)' : isPast ? 'rgba(124,109,238,0.2)' : 'var(--color-border)'}`,
                      color: isActive ? '#fff' : isPast ? 'var(--color-accent)' : 'var(--color-text-muted)',
                    }}
                  >
                    {isPast ? <Check size={11} strokeWidth={2.5} /> : index + 1}
                  </div>
                  <span
                    className="text-[12px] font-semibold transition-colors duration-300"
                    style={{
                      color: isActive ? 'var(--color-text-primary)' : isPast ? 'var(--color-text-secondary)' : 'var(--color-text-muted)',
                    }}
                  >
                    {LABELS[phase]}
                  </span>
                </div>
              </div>
            );
          })}
        </nav>

        {/* Right */}
        <div className="flex items-center gap-2">
          <div
            className="rounded-md border px-2.5 py-1 text-[11px] font-semibold md:hidden"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            {LABELS[state.phase]}
          </div>
          {state.phase !== 'import' && (
            <button
              onClick={() => dispatch({ type: 'RESET' })}
              className="btn-secondary inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-all"
            >
              <RotateCcw size={12} />
              <span className="hidden sm:inline">新建</span>
            </button>
          )}
        </div>
      </div>

      <div className="header-accent-line" />
    </header>
  );
}
