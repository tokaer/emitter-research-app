import { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronRight } from 'lucide-react';
import { useAppStore } from '../../store';
import { resolveAmbiguity, resolveBatch, getProgress } from '../../api/endpoints';
import type { AmbiguityRow, AmbiguousCandidate } from '../../api/types';

export default function AmbiguityPanel() {
  const ambiguities = useAppStore((s) => s.ambiguities);
  const removeAmbiguity = useAppStore((s) => s.removeAmbiguity);
  const setProgress = useAppStore((s) => s.setProgress);
  const jobId = useAppStore((s) => s.jobId);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [selections, setSelections] = useState<Record<number, string>>({});
  const [resolving, setResolving] = useState(false);

  if (!ambiguities.length) {
    return (
      <div className="text-center py-12 text-gray-500">
        No ambiguities to resolve.
      </div>
    );
  }

  const handleSelect = (rowId: number, uuid: string) => {
    setSelections({ ...selections, [rowId]: uuid });
  };

  const handleResolveSingle = async (rowId: number) => {
    if (!jobId || !selections[rowId]) return;
    setResolving(true);
    try {
      await resolveAmbiguity(jobId, rowId, selections[rowId]);
      removeAmbiguity(rowId);
      const { [rowId]: _, ...rest } = selections;
      setSelections(rest);
      // Refresh progress to update calculated counter
      const prog = await getProgress(jobId);
      setProgress(prog);
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Resolution failed');
    } finally {
      setResolving(false);
    }
  };

  const handleBatchResolve = async () => {
    if (!jobId) return;
    const resolutions = Object.entries(selections)
      .filter(([_, uuid]) => uuid)
      .map(([rowId, uuid]) => ({ row_id: parseInt(rowId), selected_uuid: uuid }));

    if (!resolutions.length) {
      alert('Select at least one candidate for batch resolution');
      return;
    }

    setResolving(true);
    try {
      const result = await resolveBatch(jobId, resolutions);
      for (const r of resolutions) {
        removeAmbiguity(r.row_id);
      }
      setSelections({});
      // Refresh progress to update calculated counter
      const prog = await getProgress(jobId);
      setProgress(prog);
      if (result.errors.length) {
        alert(
          `Resolved ${result.resolved} rows. Errors:\n${result.errors
            .map((e) => `Row ${e.row_id}: ${e.error}`)
            .join('\n')}`,
        );
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Batch resolution failed');
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-orange-500" />
          <h3 className="text-lg font-medium text-gray-900">
            Ambiguous Matches ({ambiguities.length})
          </h3>
        </div>
        <button
          onClick={handleBatchResolve}
          disabled={resolving || Object.keys(selections).length === 0}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {resolving ? 'Resolving...' : `Confirm Selected (${Object.keys(selections).length})`}
        </button>
      </div>

      {ambiguities.map((amb) => (
        <AmbiguityCard
          key={amb.id}
          ambiguity={amb}
          expanded={expandedId === amb.id}
          onToggle={() =>
            setExpandedId(expandedId === amb.id ? null : amb.id)
          }
          selectedUuid={selections[amb.id] || null}
          onSelect={(uuid) => handleSelect(amb.id, uuid)}
          onResolve={() => handleResolveSingle(amb.id)}
          resolving={resolving}
        />
      ))}
    </div>
  );
}

function AmbiguityCard({
  ambiguity,
  expanded,
  onToggle,
  selectedUuid,
  onSelect,
  onResolve,
  resolving,
}: {
  ambiguity: AmbiguityRow;
  expanded: boolean;
  onToggle: () => void;
  selectedUuid: string | null;
  onSelect: (uuid: string) => void;
  onResolve: () => void;
  resolving: boolean;
}) {
  return (
    <div className="border border-orange-200 rounded-lg overflow-hidden">
      <div
        className="flex items-center justify-between px-4 py-3 bg-orange-50 cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-gray-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-500" />
          )}
          <div>
            <span className="font-medium text-gray-900">
              {ambiguity.bezeichnung}
            </span>
            {ambiguity.produktinformationen && (
              <span className="ml-2 text-sm text-gray-500">
                ({ambiguity.produktinformationen})
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">
            {ambiguity.candidates.length} candidates
          </span>
          {selectedUuid && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onResolve();
              }}
              disabled={resolving}
              className="px-3 py-1 bg-green-600 text-white rounded text-xs hover:bg-green-700 disabled:opacity-50"
            >
              <Check className="h-3 w-3 inline mr-1" />
              Confirm
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="p-4 space-y-2">
          {ambiguity.candidates.map((candidate) => (
            <CandidateOption
              key={candidate.uuid}
              candidate={candidate}
              selected={selectedUuid === candidate.uuid}
              onSelect={() => onSelect(candidate.uuid)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CandidateOption({
  candidate,
  selected,
  onSelect,
}: {
  candidate: AmbiguousCandidate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
        selected
          ? 'bg-blue-50 border border-blue-300'
          : 'bg-gray-50 border border-transparent hover:bg-gray-100'
      }`}
    >
      <div
        className={`mt-0.5 w-4 h-4 rounded-full border-2 flex-shrink-0 ${
          selected ? 'border-blue-600 bg-blue-600' : 'border-gray-300'
        }`}
      >
        {selected && (
          <div className="w-full h-full flex items-center justify-center">
            <div className="w-1.5 h-1.5 bg-white rounded-full" />
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-900">
          {candidate.activity_name}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">
          Product: {candidate.product_name} &middot; Region:{' '}
          {candidate.geography} &middot; Unit: {candidate.unit}
        </div>
        {candidate.why_short && (
          <div className="text-xs text-blue-600 mt-1">
            {candidate.why_short}
          </div>
        )}
        <div className="text-xs text-gray-400 mt-1 font-mono">
          {candidate.uuid}
        </div>
      </div>
    </div>
  );
}
