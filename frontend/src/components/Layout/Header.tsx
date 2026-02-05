import { useAppStore } from '../../store';

export default function Header() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const jobId = useAppStore((s) => s.jobId);

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            Emitter Research App
          </h1>
          <p className="text-sm text-gray-500">
            Emission Factor Matching &middot; ecoinvent 3.12
          </p>
        </div>
        <div className="flex items-center gap-4">
          {jobId && (
            <span className="text-xs text-gray-400 font-mono">
              Job: {jobId.slice(0, 8)}
            </span>
          )}
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
            <button
              onClick={() => setMode('auto')}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                mode === 'auto'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Auto
            </button>
            <button
              onClick={() => setMode('review')}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                mode === 'review'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Review
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
