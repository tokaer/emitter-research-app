import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useAppStore } from '../../store';
import { addRow, deleteRow } from '../../api/endpoints';
import type { InputRowCreate } from '../../api/types';

const EMPTY_ROW: InputRowCreate = {
  scope: '',
  kategorie: '',
  unterkategorie: '',
  bezeichnung: '',
  produktinformationen: '',
  referenzeinheit: '',
  region: '',
  referenzjahr: '',
};

export default function InputGrid() {
  const inputRows = useAppStore((s) => s.inputRows);
  const jobId = useAppStore((s) => s.jobId);
  const addInputRow = useAppStore((s) => s.addInputRow);
  const removeInputRow = useAppStore((s) => s.removeInputRow);
  const [newRow, setNewRow] = useState<InputRowCreate>({ ...EMPTY_ROW });

  const handleAddRow = async () => {
    if (!jobId || !newRow.bezeichnung || !newRow.referenzeinheit) return;
    try {
      const created = await addRow(jobId, newRow);
      addInputRow(created);
      setNewRow({ ...EMPTY_ROW });
    } catch (e) {
      console.error('Failed to add row:', e);
    }
  };

  const handleDelete = async (rowId: number) => {
    if (!jobId) return;
    try {
      await deleteRow(jobId, rowId);
      removeInputRow(rowId);
    } catch (e) {
      console.error('Failed to delete row:', e);
    }
  };

  const columns = [
    { key: 'scope', label: 'Scope', width: 'w-16' },
    { key: 'kategorie', label: 'Kategorie', width: 'w-20' },
    { key: 'unterkategorie', label: 'Unterkategorie', width: 'w-20' },
    { key: 'bezeichnung', label: 'Bezeichnung *', width: 'w-40' },
    { key: 'produktinformationen', label: 'Produktinformationen', width: 'w-64' },
    { key: 'referenzeinheit', label: 'Referenzeinheit *', width: 'w-28' },
    { key: 'region', label: 'Region', width: 'w-20' },
    { key: 'referenzjahr', label: 'Referenzjahr', width: 'w-24' },
  ];

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase w-8">
                #
              </th>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase ${col.width}`}
                >
                  {col.label}
                </th>
              ))}
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase w-16">
                Status
              </th>
              <th className="px-3 py-2 w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {inputRows.map((row, idx) => (
              <tr key={row.id} className="hover:bg-gray-50">
                <td className="px-3 py-2 text-gray-400">{idx + 1}</td>
                {columns.map((col) => (
                  <td key={col.key} className="px-3 py-2 text-gray-700">
                    {(row as any)[col.key] || ''}
                  </td>
                ))}
                <td className="px-3 py-2">
                  <StatusBadge status={row.status} />
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => handleDelete(row.id)}
                    className="text-gray-400 hover:text-red-500 transition-colors"
                    title="Delete row"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
            {/* Add new row form */}
            <tr className="bg-blue-50/50">
              <td className="px-3 py-2 text-gray-400">
                <Plus className="h-4 w-4" />
              </td>
              {columns.map((col) => (
                <td key={col.key} className="px-3 py-1">
                  <input
                    type="text"
                    value={(newRow as any)[col.key] || ''}
                    onChange={(e) =>
                      setNewRow({ ...newRow, [col.key]: e.target.value })
                    }
                    placeholder={col.label.replace(' *', '')}
                    className="w-full px-2 py-1 text-sm border border-gray-200 rounded focus:border-blue-400 focus:outline-none"
                  />
                </td>
              ))}
              <td className="px-3 py-2" />
              <td className="px-3 py-2">
                <button
                  onClick={handleAddRow}
                  disabled={!newRow.bezeichnung || !newRow.referenzeinheit}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Add
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
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
