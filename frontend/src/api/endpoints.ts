import client from './client';
import type {
  AmbiguityRow,
  InputRow,
  InputRowCreate,
  Job,
  JobProgress,
  ProcessingMode,
  RowResult,
  UploadResponse,
} from './types';

export async function uploadTemplate(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await client.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function createJob(): Promise<{ job_id: string; status: string }> {
  const { data } = await client.post('/jobs');
  return data;
}

export async function getJob(jobId: string): Promise<Job> {
  const { data } = await client.get(`/jobs/${jobId}`);
  return data;
}

export async function getRows(jobId: string): Promise<{ job_id: string; rows: InputRow[] }> {
  const { data } = await client.get(`/jobs/${jobId}/rows`);
  return data;
}

export async function addRow(jobId: string, row: InputRowCreate): Promise<InputRow> {
  const { data } = await client.post(`/jobs/${jobId}/rows`, row);
  return data;
}

export async function updateRow(
  jobId: string,
  rowId: number,
  updates: Partial<InputRowCreate>,
): Promise<InputRow> {
  const { data } = await client.put(`/jobs/${jobId}/rows/${rowId}`, updates);
  return data;
}

export async function deleteRow(jobId: string, rowId: number): Promise<void> {
  await client.delete(`/jobs/${jobId}/rows/${rowId}`);
}

export async function startProcessing(
  jobId: string,
  mode: ProcessingMode,
): Promise<{ status: string }> {
  const { data } = await client.post(`/jobs/${jobId}/process`, { mode });
  return data;
}

export async function getProgress(jobId: string): Promise<JobProgress> {
  const { data } = await client.get(`/jobs/${jobId}/progress`);
  return data;
}

export async function getAmbiguities(
  jobId: string,
): Promise<{ job_id: string; ambiguities: AmbiguityRow[] }> {
  const { data } = await client.get(`/jobs/${jobId}/ambiguities`);
  return data;
}

export async function resolveAmbiguity(
  jobId: string,
  rowId: number,
  selectedUuid: string,
): Promise<RowResult> {
  const { data } = await client.post(`/jobs/${jobId}/rows/${rowId}/resolve`, {
    selected_uuid: selectedUuid,
  });
  return data;
}

export async function resolveBatch(
  jobId: string,
  resolutions: { row_id: number; selected_uuid: string }[],
): Promise<{ resolved: number; errors: { row_id: number; error: string }[] }> {
  const { data } = await client.post(`/jobs/${jobId}/resolve-batch`, { resolutions });
  return data;
}

export function getExportUrl(jobId: string): string {
  return `/api/v1/jobs/${jobId}/export`;
}

export async function getHealth(): Promise<{
  status: string;
  db_rows: number;
  index_loaded: boolean;
  units: string[];
}> {
  const { data } = await client.get('/health');
  return data;
}
