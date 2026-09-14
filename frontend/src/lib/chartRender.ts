/** ECharts option builder — frontend half of the (RenderData, ChartConfig) contract.

 - data_map channels ("table.column") resolve against columnar RenderData
 - option_template is deep-merged over the generated base (pure JSON enforced here,
   mirroring backend assert_json_safe — function-ish strings are REJECTED)
 - appearance: height/font/palette/legend/label; palette falls back to --chart-1..5
 */

import type { Appearance, ChartConfig, RenderData, RenderTable } from '@/types/assets'

const FORBIDDEN = ['function', '=>', 'javascript:', 'eval(', 'new function']

export function assertJsonSafe(value: unknown, path = '$'): void {
  if (typeof value === 'string') {
    const low = value.toLowerCase()
    for (const bad of FORBIDDEN) {
      if (low.includes(bad)) throw new Error(`forbidden token ${bad} at ${path}`)
    }
  } else if (Array.isArray(value)) {
    value.forEach((v, i) => assertJsonSafe(v, `${path}[${i}]`))
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) assertJsonSafe(v, `${path}.${k}`)
  }
}

function deepMerge<T extends Record<string, unknown>>(base: T, over: T): T {
  const out: Record<string, unknown> = { ...base }
  for (const [k, v] of Object.entries(over)) {
    const cur = out[k]
    out[k] = isPlainObject(cur) && isPlainObject(v)
      ? deepMerge(cur as Record<string, unknown>, v as Record<string, unknown>)
      : v
  }
  return out as T
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v)

function table(render: RenderData, ref: string): RenderTable {
  const name = ref.includes('.') ? ref.split('.')[0] : 'main'
  const t = render.tables[name]
  if (!t) throw new Error(`table ${name} missing`)
  return t
}

function col(render: RenderData, ref: string, map: Record<string, string>, channel: string): string[] {
  const src = map[channel] ?? ref
  if (!src) throw new Error(`channel ${channel} unmapped`)
  const [, cname] = src.includes('.') ? src.split('.') : ['main', src]
  const c = table(render, src).source.find((x) => x.name === cname)
  if (!c) throw new Error(`column ${src} not found`)
  return c.values.map((v) => (v == null ? '' : String(v)))
}

export function cssPalette(): string[] {
  const s = getComputedStyle(document.documentElement)
  return ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5']
    .map((v) => s.getPropertyValue(v).trim())
    .filter(Boolean)
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values)).sort()
}

function seriesColor(index: number, palette: string[]): string {
  return palette[index % palette.length]
}

export function buildOption(
  render: RenderData,
  config: ChartConfig,
  appearance: Appearance,
): Record<string, unknown> {
  const map = config.data_map.map
  const palette = appearance.color_palette?.length ? appearance.color_palette : cssPalette()
  const dark = document.documentElement.classList.contains('dark')
  const th = (d: string, l: string) => (dark ? d : l)
  const axisText = { color: th('#8a8f98', '#6b7078'), fontSize: appearance.font_size }
  const label = { show: appearance.show_label, color: th('#d0d6e0', '#3c3f44'), fontSize: appearance.font_size }
  const base: Record<string, unknown> = {
    backgroundColor: 'transparent',
    color: palette,
    textStyle: { fontFamily: 'Inter, system-ui, sans-serif' },
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: appearance.show_legend ? 56 : 36, bottom: 40, containLabel: true },
  }
  const type = config.chart_type

  if (type === 'bar' || type === 'line' || type === 'area' || type === 'histogram') {
    const xs = col(render, 'x', map, 'x')
    const ys = col(render, 'y', map, 'y')
    const seriesType = type === 'line' || type === 'area' ? 'line' : 'bar'
    base.xAxis = { type: 'category', data: xs, axisLabel: axisText, axisLine: { lineStyle: { color: th('rgba(255,255,255,0.12)', 'rgba(0,0,0,0.12)') } } }
    base.yAxis = { type: 'value', axisLabel: axisText, splitLine: { lineStyle: { color: th('rgba(255,255,255,0.06)', 'rgba(0,0,0,0.06)') } } }
    base.series = [{
      type: seriesType,
      data: ys.map(Number),
      areaStyle: type === 'area' ? { opacity: 0.25 } : undefined,
      label,
      itemStyle: { color: seriesColor(0, palette), borderRadius: type === 'bar' ? [3, 3, 0, 0] : 0 },
      emphasis: { focus: 'series' },
    }]
    // extra series channels: series.<name> -> column
    for (const [k, ref] of Object.entries(map)) {
      if (!k.startsWith('series.')) continue
      base.series = [
        ...((base.series as unknown[]) ?? []),
        { type: seriesType, name: k.slice(7), data: col(render, '', map, k).map(Number), label },
      ]
      void ref
    }
  } else if (type === 'pie') {
    const names = col(render, 'name', map, 'name')
    const values = col(render, 'value', map, 'value')
    base.tooltip = { trigger: 'item' }
    base.series = [{
      type: 'pie', radius: ['38%', '66%'], label: { ...label, show: appearance.show_label },
      data: names.map((n, i) => ({ name: n, value: Number(values[i]) })),
    }]
  } else if (type === 'scatter') {
    const xs = col(render, 'x', map, 'x').map(Number)
    const ys = col(render, 'y', map, 'y').map(Number)
    base.xAxis = { type: 'value', axisLabel: axisText }
    base.yAxis = { type: 'value', axisLabel: axisText }
    base.series = [{ type: 'scatter', data: xs.map((x, i) => [x, ys[i]]), itemStyle: { color: seriesColor(0, palette) } }]
  } else if (type === 'heatmap') {
    const xvals = col(render, '', map, 'x')
    const yvals = col(render, '', map, 'y')
    const vs = col(render, '', map, 'v').map(Number)
    const xs = unique(xvals)
    const ys = unique(yvals)
    base.grid = { ...(base.grid as object), bottom: 64 }
    base.xAxis = { type: 'category', data: xs, axisLabel: { ...axisText, rotate: 30 } }
    base.yAxis = { type: 'category', data: ys, axisLabel: axisText }
    base.tooltip = { trigger: 'item' }
    base.visualMap = {
      min: Math.min(...vs), max: Math.max(...vs), calculable: true,
      orient: 'horizontal', left: 'center', bottom: 8, textStyle: axisText,
      inRange: { color: ['#15202e', seriesColor(0, palette)] },
    }
    base.series = [{
      type: 'heatmap',
      data: xvals.map((x, i) => [xs.indexOf(x), ys.indexOf(yvals[i]), vs[i]]),
      label: { ...label, show: appearance.show_label },
    }]
  } else {
    // box / unknown: honest fallback — bars on x/y if mapped, else empty option
    if (map.x && map.y) return buildOption(render, { ...config, chart_type: 'bar' }, appearance)
  }
  if (appearance.show_legend) base.legend = { textStyle: axisText, top: 8 }
  if (config.title) {
    base.title = { text: config.title, left: 12, top: 4, textStyle: { color: '#f7f8f8', fontSize: appearance.font_size + 2, fontWeight: 500 } }
  }
  assertJsonSafe(config.option_template ?? {}, '$.option_template')
  return deepMerge(base, (config.option_template ?? {}) as Record<string, unknown>)
}
