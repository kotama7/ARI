import { lazy, Suspense, useEffect, useState } from 'react';
import type { LazyExoticComponent, ComponentType } from 'react';
import { AppProvider } from './context/AppContext';
import { Layout } from './components/Layout';
import './styles/dashboard.css';

// Lazy-load page components
const HomePage = lazy(() => import('./components/Home/HomePage').then((m) => ({ default: m.HomePage })));
const ExperimentsPage = lazy(() => import('./components/Experiments/ExperimentsPage').then((m) => ({ default: m.ExperimentsPage })));
const MonitorPage = lazy(() => import('./components/Monitor/MonitorPage').then((m) => ({ default: m.MonitorPage })));
const TreePage = lazy(() => import('./components/Tree/TreePage').then((m) => ({ default: m.TreePage })));
const ResultsPage = lazy(() => import('./components/Results/ResultsPage').then((m) => ({ default: m.ResultsPage })));
const WizardPage = lazy(() => import('./components/Wizard/WizardPage').then((m) => ({ default: m.WizardPage })));
const IdeaPage = lazy(() => import('./components/Idea/IdeaPage'));
const WorkflowPage = lazy(() => import('./components/Workflow/WorkflowPage'));
const SettingsPage = lazy(() => import('./components/Settings/SettingsPage'));

// ── helpers ──

function parseHash(): string {
  const raw = window.location.hash.replace(/^#\/?/, '');
  // Map legacy "new" route to "wizard"
  if (raw === 'new') return 'wizard';
  return raw || 'home';
}

const PAGE_MAP: Record<string, LazyExoticComponent<ComponentType>> = {
  home: HomePage,
  experiments: ExperimentsPage,
  monitor: MonitorPage,
  tree: TreePage,
  results: ResultsPage,
  new: WizardPage,
  wizard: WizardPage,
  idea: IdeaPage,
  workflow: WorkflowPage,
  settings: SettingsPage,
};

// ── inner router (uses context) ──

function Router() {
  const [page, setPage] = useState<string>(parseHash);

  useEffect(() => {
    const onHashChange = () => setPage(parseHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const PageComponent = PAGE_MAP[page] ?? HomePage;

  return (
    <Layout>
      <Suspense
        fallback={
          <div style={{ flex: 1, padding: 28, textAlign: 'center', paddingTop: 80 }}>
            <div className="spinner" />
          </div>
        }
      >
        <PageComponent />
      </Suspense>
    </Layout>
  );
}

// ── App ──

export default function App() {
  return (
    <AppProvider>
      <Router />
    </AppProvider>
  );
}
