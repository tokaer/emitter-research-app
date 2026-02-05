import { useCallback, useEffect, useRef } from 'react';
import { Play, Download, Loader2 } from 'lucide-react';
import { useAppStore } from '../../store';
import {
  startProcessing,
  getProgress,
  getAmbiguities,
  getExportUrl,
} from '../../api/endpoints';

export default function ProcessButton() {
  const jobId = useAppStore((s) => s.jobId);
  const mode = useAppStore((s) => s.mode);
  const inputRows = useAppStore((s) => s.inputRows);
  const isProcessing = useAppStore((s) => s.isProcessing);
  const setIsProcessing = useAppStore((s) => s.setIsProcessing);
  const setProgress = useAppStore((s) => s.setProgress);
  const setAmbiguities = useAppStore((s) => s.setAmbiguities);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const progress = useAppStore((s) => s.progress);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollProgress = useCallback(async () => {
    if (!jobId) return;
    try {
      const prog = await getProgress(jobId);
      setProgress(prog);

      if (prog.job_status === 'completed' || prog.job_status === 'error') {
        setIsProcessing(false);
        stopPolling();
        setActiveTab('results');

        // Load ambiguities if any
        if (prog.ambiguous > 0) {
          const amb = await getAmbiguities(jobId);
          setAmbiguities(amb.ambiguities);
        }
      }
    } catch (e) {
      console.error('Polling error:', e);
    }
  }, [jobId, setProgress, setIsProcessing, stopPolling, setActiveTab, setAmbiguities]);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const handleStart = async () => {
    if (!jobId) return;
    try {
      await startProcessing(jobId, mode);
      setIsProcessing(true);
      setActiveTab('results');

      // Start polling every 2 seconds
      pollRef.current = setInterval(pollProgress, 2000);
      // Also poll immediately
      pollProgress();
    } catch (e: any) {
      console.error('Failed to start processing:', e);
      alert(e.response?.data?.detail || 'Failed to start processing');
    }
  };

  const hasPending = inputRows.some((r) => r.status === 'pending');

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleStart}
        disabled={!jobId || isProcessing || !hasPending}
        className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isProcessing ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <Play className="h-4 w-4" />
            Start Processing
          </>
        )}
      </button>

      {progress && progress.done > 0 && (
        <a
          href={getExportUrl(jobId!)}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
          download
        >
          <Download className="h-4 w-4" />
          Export Excel
        </a>
      )}

      {progress && (
        <span className="text-sm text-gray-500">
          {progress.calculated} calculated / {progress.ambiguous} ambiguous /{' '}
          {progress.errors} errors / {progress.total} total
        </span>
      )}
    </div>
  );
}
