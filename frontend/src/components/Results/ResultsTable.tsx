import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';
import { useAppStore } from '../../store';
import { getRows } from '../../api/endpoints';
import type { InputRow } from '../../api/types';

export default function ResultsTable() {
  const jobId = useAppStore((s) => s.jobId);
  const progress = useAppStore((s) => s.progress);
  const [rows, setRows] = useState<InputRow[]>([]);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const load = async () => {
      try {
        const data = await getRows(jobId);
        setRows(data.rows);
      } catch (e) {
        console.error('Failed to load rows:', e);
      }
    };
    load();
  }, [jobId, progress]);

  if (!rows.length) {
    return (
      <div className="text-center py-12 text-gray-500">
        No results yet. Upload a template and start processing.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 w-8"></th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                #
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Bezeichnung
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Status
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Biogene Emissionen [t CO2-Eq]
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Common Factor [t CO2-Eq]
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Beschreibung
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                Quelle
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row, idx) => {
              const result = row.result;
              const isExpanded = expandedRow === row.id;
              return (
                <>
                  <tr
                    key={row.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() =>
                      setExpandedRow(isExpanded ? null : row.id)
                    }
                  >
                    <td className="px-3 py-2">
                      {result?.detailed_calc ? (
                        isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-gray-400" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-gray-400" />
                        )
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-gray-400">{idx + 1}</td>
                    <td className="px-3 py-2 font-medium text-gray-900">
                      {row.bezeichnung}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-3 py-2">
                      {result?.biogenic_t ? (
                        <CopyField value={result.biogenic_t} />
                      ) : (
                        <span className="text-gray-300">&mdash;</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {result?.common_t ? (
                        <CopyField value={result.common_t} />
                      ) : (
                        <span className="text-gray-300">&mdash;</span>
                      )}
                    </td>
                    <td className="px-3 py-2 max-w-xs">
                      {result?.beschreibung ? (
                        <CopyField
                          value={result.beschreibung}
                          truncate={80}
                        />
                      ) : (
                        <span className="text-gray-300">&mdash;</span>
                      )}
                    </td>
                    <td className="px-3 py-2 max-w-xs">
                      {result?.quelle ? (
                        <CopyField value={result.quelle} truncate={60} />
                      ) : (
                        <span className="text-gray-300">&mdash;</span>
                      )}
                    </td>
                  </tr>
                  {isExpanded && result?.detailed_calc && (
                    <tr key={`${row.id}-detail`} className="bg-gray-50">
                      <td colSpan={8} className="px-6 py-4">
                        <div className="flex justify-between items-start mb-2">
                          <span className="text-xs font-medium text-gray-500 uppercase">
                            Detailed Calculation
                          </span>
                          <CopyButton text={result.detailed_calc} />
                        </div>
                        <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono bg-white p-3 rounded border border-gray-200 max-h-96 overflow-y-auto">
                          {result.detailed_calc}
                        </pre>
                        {row.error_message && (
                          <div className="mt-2 p-2 bg-red-50 text-red-700 text-xs rounded">
                            Error: {row.error_message}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CopyField({
  value,
  truncate,
}: {
  value: string;
  truncate?: number;
}) {
  const display = truncate && value.length > truncate
    ? value.slice(0, truncate) + '...'
    : value;

  return (
    <div className="flex items-center gap-1 group">
      <span className="text-gray-700 text-xs" title={value}>
        {display}
      </span>
      <CopyButton text={value} />
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-blue-600 transition-all"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-500" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
    </button>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    searching: 'bg-yellow-100 text-yellow-700',
    llm_deciding: 'bg-yellow-100 text-yellow-700',
    ambiguous: 'bg-orange-100 text-orange-700',
    decomposing: 'bg-purple-100 text-purple-700',
    matched: 'bg-green-100 text-green-700',
    calculated: 'bg-green-100 text-green-700',
    error: 'bg-red-100 text-red-700',
  };

  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
        colors[status] || 'bg-gray-100 text-gray-600'
      }`}
    >
      {status}
    </span>
  );
}
