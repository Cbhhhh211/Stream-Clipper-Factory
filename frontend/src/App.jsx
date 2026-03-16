import { AppProvider, useAppStore } from './store/useAppStore';
import ImportPanel from './components/ImportPanel';
import ProcessingView from './components/ProcessingView';
import ReviewLayout from './components/ReviewLayout';
import ExportPanel from './components/ExportPanel';
import Header from './components/Header';

function AppContent() {
  const { state } = useAppStore();

  return (
    <div className="app-shell bg-ocean-shell relative flex h-full w-full flex-col overflow-hidden">
      <div className="app-backdrop" aria-hidden>
        <div className="grid-layer" />
        <div className="noise-layer" />
      </div>

      <div className="relative z-10 flex h-full w-full flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-3 md:px-6 md:pb-6">
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

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
