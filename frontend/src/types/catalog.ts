/** Catalog API types — mirror of backend/src/data_agent/catalog/models.py (N1 contract). */

export type DatasetKind = 'file' | 'folder' | 'sql'
export type ScanStatus = 'pending' | 'scanning' | 'ready' | 'stale' | 'failed'
export type ProfileStatus = 'pending' | 'profiling' | 'ready' | 'outdated' | 'failed'

export interface DatasetRef {
  dataset_id: string
  name: string
  revision: string
}

export interface ColumnProfile {
  name: string
  dtype: string
  null_rate: number
  cardinality: number | null
  num_range: [number, number] | null
  time_min: string | null
  time_max: string | null
  top_values: unknown[]
  sample_values: unknown[]
  is_time: boolean
  pk_hint: boolean
}

export interface TableProfile {
  dataset_id: string
  revision: string
  row_count: number
  columns: ColumnProfile[]
  profiled_at: string
}

export interface FileMeta {
  path: string
  format: 'csv' | 'parquet' | 'xlsx'
  sheet: string | null
  size_bytes: number
}
export interface FolderMeta {
  root: string
  extensions: string[]
  fingerprint: string
  child_ids: string[]
}
export interface SqlMeta {
  engine: string
  conn_ref: string
  db_schema: string
  table: string
  column_allowlist: string[] | null
}

export interface Dataset {
  id: string
  name: string
  kind: DatasetKind
  meta: FileMeta | FolderMeta | SqlMeta
  revision: string
  parent_id: string | null
  description: string
  tags: string[]
  privacy_mode: boolean | null
  scan_status: ScanStatus
  profile_status: ProfileStatus
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface DatasetBrief {
  id: string
  name: string
  kind: DatasetKind
  revision: string
  parent_id: string | null
  scan_status: ScanStatus
  profile_status: ProfileStatus
  privacy_mode: boolean | null
  row_count: number | null
}

export type PreviewResult =
  | { mode: 'rows'; columns: string[]; rows: Record<string, unknown>[]; truncated: boolean }
  | {
      mode: 'summary'
      row_count: number
      columns: {
        name: string
        dtype: string
        null_rate: number
        cardinality: number | null
        num_range: number[] | null
        is_time: boolean
        time_range: [string | null, string | null] | null
      }[]
    }

export interface RegisterBody {
  kind: DatasetKind
  path?: string
  root?: string
  extensions?: string[]
  conn_target?: string
  table?: string
  name?: string
  description?: string
  privacy_mode?: boolean
}
