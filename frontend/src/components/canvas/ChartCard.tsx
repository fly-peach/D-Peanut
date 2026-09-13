/** ChartCard: ECharts renderer for one ChartAsset (frontend render contract half).
 * appearance overrides are local-only (zero network); data changes need re-run. */

import type { ECharts } from 'echarts'
import { BarChart3, Download, FileSpreadsheet, History, RefreshCw, Ruler, Settings2, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { ParamForm } from '@/components/canvas/ParamForm'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { buildOption } from '@/lib/chartRender'
import { useCanvasStore } from '@/stores/canvasStore'
import type { AssetIndexRow, RenderBundle } from '@/types/assets'

export function ChartCard({ row, bundle }: { row: AssetIndexRow; bundle?: RenderBundle }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ECharts | null>(null)
  const appearance = useCanvasStore((s) => s.appearance[row.id])
  const dirty = useCanvasStore((s) => s.dirty[row.id])
  const replay = useCanvasStore((s) => s.replay)
  const setPlacement = useCanvasStore((s) => s.setPlacement)
  const rollback = useCanvasStore((s) => s.rollback)
  const remove = useCanvasStore((s) => s.remove)
  const [showParams, setShowParams] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<{ versions: number[]; replays: Record<string, unknown>[] } | null>(null)
  const [replaying, setReplaying] = useState(false)
  const [gateNote, setGateNote] = useState<string[] | null>(null)

  useEffect(() => {
    let disposed = false
    void import('echarts').then((echarts) => {
      if (disposed || !ref.current) return
      chartRef.current = echarts.init(ref.current)
      redraw()
    })
    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      disposed = true
      window.removeEventListener('resize', onResize)
      chartRef.current?.dispose()
      chartRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function redraw() {
    if (!chartRef.current || !bundle) return
    const merged = { ...bundle.config.appearance, ...(appearance ?? {}) }
    const option = buildOption(bundle.render, bundle.config, merged)
    chartRef.current.setOption(option, { notMerge: true })
    chartRef.current.resize()
  }

  useEffect(redraw, [bundle, appearance])

  const exportPng = () => {
    const chart = chartRef.current
    if (!chart) return
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#191a1b' })
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.name}.png`
    a.click()
  }

  const exportCsv = () => {
    if (!bundle) return
    const t = bundle.render.tables.main ?? Object.values(bundle.render.tables)[0]
    if (!t) return
    const esc = (v: unknown) => {
      const s = v == null ? '' : String(v)
      return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
    }
    const lines = [t.dimensions.join(',')]
    const len = t.source[0]?.values.length ?? 0
    for (let i = 0; i < len; i++) {
      lines.push(t.source.map((c) => esc(c.values[i])).join(','))
    }
    const blob = new Blob(["﻿" + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${row.name}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const doReplay = async () => {
    setReplaying(true)
    const r = await replay(row.id)
    setGateNote(r.passed ? null : r.errors)
    setReplaying(false)
  }

  const openHistory = async () => {
    setShowHistory(true)
    const { assetsApi } = await import('@/api/client')
    setHistory(await assetsApi.history(row.id))
  }

  const height = Number(appearance?.height ?? bundle?.config.appearance.height ?? 320)
  const failed = row.gate_passed === false

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center gap-1 border-b border-border/60 px-3 py-1.5">
        <BarChart3 className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate text-xs font-medium">{row.name}</span>
        <Badge variant="outline" className="ml-1 shrink-0 text-[10px]">{row.chart_type}</Badge>
        <span className="text-muted-foreground shrink-0 text-[10px]">v{row.version}</span>
        {dirty && <Badge variant="secondary" className="shrink-0 text-[10px]">参数已改·待重跑</Badge>}
        {row.stale_data && (
          <Badge variant="outline" className="border-amber-500/60 text-amber-500 shrink-0 text-[10px]">
            数据已更新·待重跑
          </Badge>
        )}
        {failed && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="destructive" className="shrink-0 text-[10px]">⚠ 未过闸</Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-80 text-xs">{(row.gate_at ?? '') + ' 上次重放失败'}</TooltipContent>
          </Tooltip>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <Button size="icon-xs" variant="ghost" title="导出 PNG" onClick={exportPng} disabled={!bundle}>
            <Download className="size-3" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="导出 CSV" onClick={exportCsv} disabled={!bundle}>
            <FileSpreadsheet className="size-3" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="重跑" onClick={doReplay} disabled={replaying}>
            <RefreshCw className={replaying ? 'size-3 animate-spin' : 'size-3'} />
          </Button>
          <Button size="icon-xs" variant="ghost" title="参数" onClick={() => setShowParams(true)}>
            <Settings2 className="size-3" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="历史" onClick={openHistory}>
            <History className="size-3" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="切换宽度 (4→6→8→10)"
                  onClick={() => {
                    const steps = [4, 6, 8, 10]
                    const next = steps[(steps.indexOf(row.placement.w) + 1) % steps.length]
                    setPlacement(row.id, next, row.placement.h)
                  }}>
            <Ruler className="size-3" />
          </Button>
          <Button size="icon-xs" variant="ghost" title="删除" onClick={() => remove(row.id)}>
            <Trash2 className="size-3" />
          </Button>
        </div>
      </div>

      <div ref={ref} style={{ height }} className="w-full" />

      {gateNote && (
        <div className="border-t border-destructive/30 bg-destructive/10 px-3 py-1.5">
          {gateNote.map((e) => <p key={e} className="text-[11px] text-destructive">{e}</p>)}
        </div>
      )}
      {!bundle && !failed && (
        <div className="grid h-24 place-items-center text-xs text-muted-foreground">
          {row.status === 'broken' ? '源文件漂移，等待重新验证' : '尚无过闸渲染 — 点重跑'}
        </div>
      )}

      <Dialog open={showParams} onOpenChange={setShowParams}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>参数 · {row.name}</DialogTitle></DialogHeader>
          <ParamForm assetId={row.id} />
        </DialogContent>
      </Dialog>

      <Dialog open={showHistory} onOpenChange={setShowHistory}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>历史 · {row.name}</DialogTitle></DialogHeader>
          {history && (
            <div className="space-y-2 text-xs">
              <p className="text-muted-foreground">快照版本：{history.versions.join(' / ') || '无'}</p>
              {history.replays.slice(0, 12).map((r, i) => (
                <div key={i} className="flex items-center gap-2 border-b border-border/50 pb-1">
                  <span className={r.passed ? 'text-green-500' : 'text-destructive'}>
                    {r.passed ? '✓' : '✗'}
                  </span>
                  <span>v{String(r.version)}</span>
                  <span className="text-muted-foreground">{String(r.trigger)}</span>
                  <span className="text-muted-foreground ml-auto">{String(r.ran_at).slice(4, 16)}</span>
                </div>
              ))}
              {history.versions.map((v) => (
                <Button key={v} size="xs" variant="outline"
                        onClick={() => { rollback(row.id, v); setShowHistory(false) }}>
                  回到 v{v}
                </Button>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
