import axios from 'axios'
import type {
  DatasetProfile,
  PreprocessingResult,
  GenerateRequest,
  GenerationStatus,
  PreviewResponse,
  ValidationReport,
  PrivacyReport,
  CohortProfileResponse,
} from '../types'

const BASE = '/api'

const client = axios.create({ baseURL: BASE, timeout: 30000 })

// ── Dataset ───────────────────────────────────────────────────────────────────

export async function uploadDataset(file: File): Promise<DatasetProfile> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await client.post('/dataset/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
  return data
}

export async function uploadDemoDataset(): Promise<DatasetProfile> {
  const { data } = await client.post('/dataset/upload-demo')
  return data
}

export async function getDatasetProfile(datasetId: string): Promise<DatasetProfile> {
  const { data } = await client.get(`/dataset/${datasetId}/profile`)
  return data
}

export async function getCohortProfile(datasetId: string): Promise<CohortProfileResponse> {
  const { data } = await client.get(`/dataset/${datasetId}/cohort-profile`)
  return data
}

export async function preprocessDataset(
  datasetId: string,
  approvedColumns: string[],
  columnMapping?: Record<string, string>
): Promise<PreprocessingResult> {
  const { data } = await client.post(`/dataset/${datasetId}/preprocess`, {
    approved_columns: approvedColumns,
    column_mapping: columnMapping ?? {},
  })
  return data
}

// ── Generation ───────────────────────────────────────────────────────────────

export async function startGeneration(req: GenerateRequest): Promise<{ generation_id: string }> {
  const { data } = await client.post('/generate', req)
  return data
}

export async function getGenerationStatus(generationId: string): Promise<GenerationStatus> {
  const { data } = await client.get(`/generation/${generationId}/status`)
  return data
}

export async function getPreview(
  generationId: string,
  page = 1,
  pageSize = 50,
  search?: string,
  sortCol?: string,
  sortDir?: 'asc' | 'desc'
): Promise<PreviewResponse> {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (search) params.search = search
  if (sortCol) params.sort_col = sortCol
  if (sortDir) params.sort_dir = sortDir
  const { data } = await client.get(`/generation/${generationId}/preview`, { params })
  return data
}

// ── Validation ───────────────────────────────────────────────────────────────

export async function runValidation(generationId: string): Promise<ValidationReport> {
  const { data } = await client.post(`/validation/${generationId}`)
  return data
}

export async function getValidationReport(generationId: string): Promise<ValidationReport> {
  const { data } = await client.get(`/validation/${generationId}/report`)
  return data
}

// ── Privacy ───────────────────────────────────────────────────────────────────

export async function runPrivacyCheck(generationId: string): Promise<PrivacyReport> {
  const { data } = await client.post(`/privacy/${generationId}`)
  return data
}

export async function getPrivacyReport(generationId: string): Promise<PrivacyReport> {
  const { data } = await client.get(`/privacy/${generationId}/report`)
  return data
}

// ── Export ────────────────────────────────────────────────────────────────────

export function getCsvUrl(generationId: string): string {
  return `${BASE}/export/${generationId}/csv`
}

export function getXlsxUrl(generationId: string): string {
  return `${BASE}/export/${generationId}/xlsx`
}

export function getReportXlsxUrl(generationId: string): string {
  return `${BASE}/export/${generationId}/report-xlsx`
}

// ── Error helper ──────────────────────────────────────────────────────────────

export function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join(', ')
    return err.message
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred'
}

// ── Health / dependency check ─────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  service: string
  dependencies: {
    sdv_installed: boolean
    sdv_version: string | null
    ctgan_available: boolean
    tvae_available: boolean
    gaussian_copula_available: boolean
    generation_ready: boolean
  }
}

export async function checkHealth(): Promise<HealthResponse> {
  const { data } = await client.get('/health')
  return data
}
