// Mirrors backend Pydantic models

export type RowStatus =
  | 'pending'
  | 'searching'
  | 'llm_deciding'
  | 'ambiguous'
  | 'decomposing'
  | 'matched'
  | 'calculated'
  | 'error';

export type DecisionType = 'match' | 'ambiguous' | 'decompose';
export type ProcessingMode = 'auto' | 'review';

export interface InputRowCreate {
  scope?: string;
  kategorie?: string;
  unterkategorie?: string;
  bezeichnung: string;
  produktinformationen?: string;
  referenzeinheit: string;
  region?: string;
  referenzjahr?: string;
}

export interface InputRow extends InputRowCreate {
  id: number;
  job_id: string;
  row_index: number;
  bezeichnung_norm?: string;
  produktinfo_norm?: string;
  region_norm: string;
  status: RowStatus;
  error_message?: string;
  result?: RowResult | null;
}

export interface AmbiguousCandidate {
  uuid: string;
  activity_name: string;
  product_name: string;
  geography: string;
  unit: string;
  why_short: string;
  rank: number;
}

export interface RowResult {
  id: number;
  input_row_id: number;
  decision_type: DecisionType;
  selected_uuid?: string;
  candidates_json?: string;
  components_json?: string;
  biogenic_t?: string;
  common_t?: string;
  beschreibung?: string;
  quelle?: string;
  detailed_calc?: string;
  provenance_json?: string;
  created_at: string;
}

export interface Job {
  id: string;
  created_at: string;
  mode: ProcessingMode;
  status: string;
  total_rows: number;
  done_rows: number;
}

export interface JobProgress {
  job_id: string;
  job_status: string;
  total: number;
  pending: number;
  processing: number;
  done: number;
  calculated: number;
  ambiguous: number;
  errors: number;
  rows: RowSummary[];
}

export interface RowSummary {
  id: number;
  row_index: number;
  bezeichnung: string;
  status: RowStatus;
  error_message?: string;
  has_result: boolean;
  biogenic_t?: string;
  common_t?: string;
}

export interface AmbiguityRow {
  id: number;
  row_index: number;
  bezeichnung: string;
  produktinformationen?: string;
  referenzeinheit: string;
  region?: string;
  candidates: AmbiguousCandidate[];
}

export interface UploadResponse {
  job_id: string;
  total_rows: number;
  rows: InputRow[];
}
