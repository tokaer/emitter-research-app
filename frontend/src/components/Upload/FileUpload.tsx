import { useCallback, useState } from 'react';
import { Upload, PlusCircle } from 'lucide-react';
import { uploadTemplate, createJob } from '../../api/endpoints';
import { useAppStore } from '../../store';

export default function FileUpload() {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [creatingManual, setCreatingManual] = useState(false);
  const setJobId = useAppStore((s) => s.setJobId);
  const setInputRows = useAppStore((s) => s.setInputRows);
  const setActiveTab = useAppStore((s) => s.setActiveTab);

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.endsWith('.xlsx')) {
        setError('Only .xlsx files are supported');
        return;
      }
      setError(null);
      setLoading(true);
      try {
        const result = await uploadTemplate(file);
        setJobId(result.job_id);
        setInputRows(result.rows);
        setActiveTab('input');
      } catch (e: any) {
        setError(e.response?.data?.detail || e.message || 'Upload failed');
      } finally {
        setLoading(false);
      }
    },
    [setJobId, setInputRows, setActiveTab],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleCreateManual = useCallback(async () => {
    setError(null);
    setCreatingManual(true);
    try {
      const result = await createJob();
      setJobId(result.job_id);
      setInputRows([]);
      setActiveTab('input');
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to create job');
    } finally {
      setCreatingManual(false);
    }
  }, [setJobId, setInputRows, setActiveTab]);

  return (
    <div className="space-y-6">
      {/* Excel Upload Option */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-xl p-12 text-center transition-colors ${
          dragging
            ? 'border-blue-400 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
        <p className="text-lg font-medium text-gray-700 mb-2">
          Upload Excel Template
        </p>
        <p className="text-sm text-gray-500 mb-4">
          Drag &amp; drop your .xlsx file or click to browse
        </p>
        <label className="inline-block cursor-pointer">
          <span className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition-colors">
            {loading ? 'Uploading...' : 'Choose File'}
          </span>
          <input
            type="file"
            accept=".xlsx"
            onChange={onFileInput}
            className="hidden"
            disabled={loading}
          />
        </label>
      </div>

      {/* Divider */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-gray-300"></div>
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="px-2 bg-gray-50 text-gray-500">oder</span>
        </div>
      </div>

      {/* Manual Entry Option */}
      <div className="border-2 border-dashed rounded-xl p-12 text-center border-gray-300 hover:border-gray-400 transition-colors">
        <PlusCircle className="mx-auto h-12 w-12 text-gray-400 mb-4" />
        <p className="text-lg font-medium text-gray-700 mb-2">
          Manuelle Eingabe
        </p>
        <p className="text-sm text-gray-500 mb-4">
          Zeilen direkt in die Tabelle eintragen
        </p>
        <button
          onClick={handleCreateManual}
          disabled={creatingManual}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 transition-colors disabled:opacity-50"
        >
          {creatingManual ? 'Erstelle...' : 'Neue Tabelle erstellen'}
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-600 text-center">{error}</p>
      )}
    </div>
  );
}
