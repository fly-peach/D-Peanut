/** Canvas asset API types — mirror of backend/src/data_agent/canvas/models.py (N2 contract). */

export type AssetStatus = 'draft' | 'validated' | 'on_canvas' | 'broken'

export interface RenderColumn { name: string; dtype: string; values: unknown[] }
export interface RenderTable { dimensions: string[]; source: RenderColumn[] }
export interface RenderData {
  tables: Record<string, RenderTable>
  row_count: number
  payload_bytes: number
}

export interface Appearance {
  height: number
  width: number | null
  font_size: number
  color_palette: string[] | null
  show_legend: boolean
  show_label: boolean
}

export interface ChartConfig {
  chart_type: string
  title: string
  option_template: Record<string, unknown>
  data_map: { map: Record<string, string> }
  appearance: Appearance
}

export interface ParamField {
  key: string
  label: string
  type: 'int' | 'float' | 'str' | 'bool' | 'date' | 'select' | 'multiselect' | 'column_ref'
  default?: unknown
  min?: number | null
  max?: number | null
  options?: unknown[] | null
  affects: 'data' | 'appearance'
}

export interface DataSourceBinding { alias: string; dataset: { dataset_id: string; name: string; revision: string } }

export interface GateReport {
  asset_id: string
  version: number
  passed: boolean
  checks: { kind: string; expected: string; actual: string; passed: boolean; detail?: string }[]
  errors: string[]
  elapsed_s: number
  ran_at: string
}

export interface ChartAsset {
  id: string
  name: string
  status: AssetStatus
  version: number
  bindings: DataSourceBinding[]
  param_spec: ParamField[]
  params: Record<string, unknown>
  chart_type: string
  placement: { x: number; y: number; w: number; h: number; z: number }
  provenance: { created_by: string }
  last_gate: GateReport | null
  description: string
}

export interface AssetIndexRow {
  id: string
  name: string
  status: AssetStatus
  version: number
  chart_type: string
  placement: { x: number; y: number; w: number; h: number; z: number }
  gate_passed: boolean | null
  gate_at: string | null
  has_render: boolean
  stale_data: boolean
}

export interface RenderBundle {
  render: RenderData
  config: ChartConfig
  version: number
  gate_passed: boolean | null
}
