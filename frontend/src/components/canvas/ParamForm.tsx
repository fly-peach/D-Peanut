/** ParamForm — generated from asset param_spec (the only form truth source).
 * appearance fields preview locally at once; saving persists params, data
 * changes additionally flag the card dirty (re-run stays manual, DoD #2). */

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useCanvasStore } from '@/stores/canvasStore'
import type { ChartAsset, ParamField } from '@/types/assets'

function Field({ f, value, onChange }: {
  f: ParamField
  value: unknown
  onChange: (v: unknown) => void
}) {
  const id = `p-${f.key}`
  return (
    <label htmlFor={id} className="flex items-center justify-between gap-3 text-xs">
      <span>
        {f.label}
        <span className="text-muted-foreground ml-1">
          ({f.affects === 'appearance' ? '外观·即时' : '数据·需重跑'})
        </span>
      </span>
      {f.type === 'bool' ? (
        <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      ) : f.type === 'select' ? (
        <select id={id} className="h-7 rounded-md border bg-background px-2 text-xs"
                value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(f.options ?? []).map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
        </select>
      ) : (
        <input id={id} type={f.type === 'int' || f.type === 'float' ? 'number' : 'text'}
               className="h-7 w-28 rounded-md border bg-background px-2 text-xs"
               min={f.min ?? undefined} max={f.max ?? undefined}
               value={value == null ? '' : String(value)}
               onChange={(e) => onChange(f.type === 'int' ? Number.parseInt(e.target.value, 10)
                               : f.type === 'float' ? Number.parseFloat(e.target.value) : e.target.value)} />
      )}
    </label>
  )
}

export function ParamForm({ assetId }: { assetId: string }) {
  const detail = useCanvasStore((s) => s.detail)
  const saveParams = useCanvasStore((s) => s.saveParams)
  const setAppearanceOverride = useCanvasStore((s) => s.setAppearanceOverride)
  const replay = useCanvasStore((s) => s.replay)
  const [asset, setAsset] = useState<ChartAsset | null>(null)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void detail(assetId).then((a) => {
      setAsset(a)
      if (a) setDraft({ ...a.params })
    })
  }, [assetId, detail])

  if (!asset) return <p className="text-muted-foreground text-xs">加载参数…</p>

  const onChange = (key: string, v: unknown) => {
    const next = { ...draft, [key]: v }
    setDraft(next)
    const spec = asset.param_spec.find((p) => p.key === key)
    if (spec?.affects === 'appearance' && typeof v === 'number' || spec?.affects === 'appearance' && typeof v === 'boolean') {
      setAppearanceOverride(assetId, { [key]: v })
    }
  }

  const appearanceKeys = asset.param_spec.filter((p) => p.affects === 'appearance').map((p) => p.key)
  const dataChanged = asset.param_spec
    .filter((p) => p.affects === 'data')
    .some((p) => JSON.stringify(draft[p.key]) !== JSON.stringify(asset.params[p.key]))
  const appearanceChanged = appearanceKeys.some(
    (k) => JSON.stringify(draft[k]) !== JSON.stringify(asset.params[k]))

  const save = async () => {
    setBusy(true)
    await saveParams(assetId, draft, asset.version, dataChanged)
    if (dataChanged) await replay(assetId).catch(() => undefined) // keep manual semantics for pure edits
    setBusy(false)
  }

  const groups: { title: string; keys: ParamField[] }[] = [
    { title: '数据参数', keys: asset.param_spec.filter((p) => p.affects === 'data') },
    { title: '外观参数（本地即时预览，零网络）', keys: asset.param_spec.filter((p) => p.affects === 'appearance') },
  ]

  return (
    <div className="space-y-4">
      {groups.map((g) => g.keys.length > 0 && (
        <div key={g.title} className="space-y-2">
          <p className="text-muted-foreground text-[11px] font-medium">{g.title}</p>
          {g.keys.map((f) => <Field key={f.key} f={f} value={draft[f.key]} onChange={(v) => onChange(f.key, v)} />)}
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <Button size="sm" disabled={busy || (!dataChanged && !appearanceChanged)} onClick={save}>
          {busy ? '保存中…' : dataChanged ? '保存并重跑' : '保存外观'}
        </Button>
        <span className="text-muted-foreground text-[11px]">当前 v{asset.version} · {asset.status}</span>
      </div>
    </div>
  )
}
