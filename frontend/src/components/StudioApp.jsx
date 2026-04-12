import { AppProvider, useAppStore } from '../store/useAppStore';
import ImportPanel from './ImportPanel';
import ProcessingView from './ProcessingView';
import ReviewLayout from './ReviewLayout';
import ExportPanel from './ExportPanel';
import Header from './Header';

function StudioContent() {
  const { state } = useAppStore();

  return (
    <div className="app-shell bg-ocean-shell relative flex h-full w-full flex-col overflow-hidden">
      <div className="app-backdrop" aria-hidden>
        <div className="noise-layer" />
      </div>

      <div className="relative z-10 flex h-full w-full flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-3 md:px-5 md:pb-5">
          <section key={state.phase} className="app-stage min-h-full phase-enter">
            {state.phase === 'import' && <ImportPanel />}
            {state.phase === 'processing' && <ProcessingView />}
            {state.phase === 'review' && <ReviewLayout />}
            {state.phase === 'export' && <ExportPanel />}
          </section>
        </main>
      </div>
    </div>
  );
}

export default function StudioApp() {
  return (
    <AppProvider>
      <StudioContent />
    </AppProvider>
  );
}
