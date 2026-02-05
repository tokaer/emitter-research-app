import { useAppStore } from './store';
import Header from './components/Layout/Header';
import FileUpload from './components/Upload/FileUpload';
import InputGrid from './components/Grid/InputGrid';
import ProcessButton from './components/Controls/ProcessButton';
import ResultsTable from './components/Results/ResultsTable';
import AmbiguityPanel from './components/Resolution/AmbiguityPanel';

export default function App() {
  const jobId = useAppStore((s) => s.jobId);
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const progress = useAppStore((s) => s.progress);
  const ambiguities = useAppStore((s) => s.ambiguities);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />

      <main className="max-w-7xl mx-auto px-6 py-6">
        {!jobId ? (
          <FileUpload />
        ) : (
          <>
            {/* Tab navigation */}
            <div className="flex items-center gap-6 border-b border-gray-200 mb-6">
              <TabButton
                active={activeTab === 'input'}
                onClick={() => setActiveTab('input')}
                label="Input"
              />
              <TabButton
                active={activeTab === 'results'}
                onClick={() => setActiveTab('results')}
                label="Results"
                badge={
                  progress
                    ? `${progress.calculated}/${progress.total}`
                    : undefined
                }
              />
              <TabButton
                active={activeTab === 'resolve'}
                onClick={() => setActiveTab('resolve')}
                label="Resolve"
                badge={
                  ambiguities.length > 0
                    ? String(ambiguities.length)
                    : undefined
                }
                badgeColor="orange"
              />
            </div>

            {/* Process controls */}
            <div className="mb-6">
              <ProcessButton />
            </div>

            {/* Tab content */}
            {activeTab === 'input' && <InputGrid />}
            {activeTab === 'results' && <ResultsTable />}
            {activeTab === 'resolve' && <AmbiguityPanel />}
          </>
        )}
      </main>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
  badge,
  badgeColor = 'blue',
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  badge?: string;
  badgeColor?: 'blue' | 'orange';
}) {
  const badgeColors = {
    blue: 'bg-blue-100 text-blue-700',
    orange: 'bg-orange-100 text-orange-700',
  };

  return (
    <button
      onClick={onClick}
      className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-blue-600 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'
      }`}
    >
      {label}
      {badge && (
        <span
          className={`ml-2 px-1.5 py-0.5 rounded text-xs font-medium ${badgeColors[badgeColor]}`}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
