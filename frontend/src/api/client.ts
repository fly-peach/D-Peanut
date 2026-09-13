/** REST client for the datasets + settings endpoints (Vite proxies /api → :8000). */

import type {
  Dataset,
  DatasetBrief,
  PreviewResult,
  RegisterBody,
  TableProfile,
} from '@/types/catalog'

const BASE = '/api'

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const datasetsApi = {
  list: (kind?: string) =>
    http<DatasetBrief[]>(`/datasets${kind ? `?kind=${kind}` : ''}`),
  get: (id: string) => http<Dataset>(`/datasets/${id}`),
  register: (body: RegisterBody) =>
    http<{ datasets: string[] }>('/datasets', { method: 'POST', body: JSON.stringify(body) }),
  rescan: (id: string) => http<{ status: string }>(`/datasets/${id}/rescan`, { method: 'POST' }),
  profile: (id: string) => http<TableProfile>(`/datasets/${id}/profile`),
  preview: (id: string, n: number) => http<PreviewResult>(`/datasets/${id}/preview?n=${n}`),
  patch: (id: string, body: Partial<Pick<Dataset, 'name' | 'description' | 'privacy_mode' | 'tags'>>) =>
    http<Dataset>(`/datasets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  remove: (id: string) => http<void>(`/datasets/${id}`, { method: 'DELETE' }),
}

export interface SettingsView {
  settings: Record<string, unknown>
  secrets: Record<string, string>
  data_root: string
  workspace_root: string
}

export const settingsApi = {
  get: () => http<SettingsView>('/settings'),
  put: (body: { settings?: Record<string, unknown>; secrets?: Record<string, string> }) =>
    http<SettingsView>('/settings', { method: 'PUT', body: JSON.stringify(body) }),
}
