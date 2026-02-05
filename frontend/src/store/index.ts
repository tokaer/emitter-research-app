import { create } from 'zustand';
import type {
  AmbiguityRow,
  InputRow,
  JobProgress,
  ProcessingMode,
} from '../api/types';

interface AppState {
  // Job state
  jobId: string | null;
  mode: ProcessingMode;
  setJobId: (id: string | null) => void;
  setMode: (mode: ProcessingMode) => void;

  // Input rows
  inputRows: InputRow[];
  setInputRows: (rows: InputRow[]) => void;
  addInputRow: (row: InputRow) => void;
  updateInputRow: (id: number, updates: Partial<InputRow>) => void;
  removeInputRow: (id: number) => void;

  // Progress
  progress: JobProgress | null;
  setProgress: (progress: JobProgress | null) => void;
  isProcessing: boolean;
  setIsProcessing: (v: boolean) => void;

  // Ambiguities
  ambiguities: AmbiguityRow[];
  setAmbiguities: (a: AmbiguityRow[]) => void;
  removeAmbiguity: (rowId: number) => void;

  // UI
  activeTab: 'input' | 'results' | 'resolve';
  setActiveTab: (tab: 'input' | 'results' | 'resolve') => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Job
  jobId: null,
  mode: 'auto',
  setJobId: (id) => set({ jobId: id }),
  setMode: (mode) => set({ mode }),

  // Input rows
  inputRows: [],
  setInputRows: (rows) => set({ inputRows: rows }),
  addInputRow: (row) => set((s) => ({ inputRows: [...s.inputRows, row] })),
  updateInputRow: (id, updates) =>
    set((s) => ({
      inputRows: s.inputRows.map((r) =>
        r.id === id ? { ...r, ...updates } : r,
      ),
    })),
  removeInputRow: (id) =>
    set((s) => ({ inputRows: s.inputRows.filter((r) => r.id !== id) })),

  // Progress
  progress: null,
  setProgress: (progress) => set({ progress }),
  isProcessing: false,
  setIsProcessing: (v) => set({ isProcessing: v }),

  // Ambiguities
  ambiguities: [],
  setAmbiguities: (a) => set({ ambiguities: a }),
  removeAmbiguity: (rowId) =>
    set((s) => ({
      ambiguities: s.ambiguities.filter((a) => a.id !== rowId),
    })),

  // UI
  activeTab: 'input',
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
