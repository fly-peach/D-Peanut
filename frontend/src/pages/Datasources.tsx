/** Datasources page (N1, task 4.2): register folder/file/sql, status polling,
 * profile + preview cards, privacy switch, delete. Paths are DATA_ROOT-absolute. */

import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Spinner } from '@/components/ui/spinner'
import { stopCatalogPolling, useCatalogStore } from '@/stores/catalogStore'
import type { DatasetBrief, DatasetKind, ScanStatus, ProfileStatus } from '@/types/catalog'

function StatusBadge({ label, status }: { label: string; status: ScanStatus | ProfileStatus }) {
  const busy = status === 'pending' || status === 'scanning' || status === 'profiling'
  const variant =
    status === 'failed' || status === 'outdated'
      ? 'destructive'
      : status === 'stale'
        ? 'outline'
        : busy
          ? 'secondary'
          : 'default'
  return (
    <Badge variant={variant} className="gap-1">
      {busy && <Spinner className="size-3" />}
      {label}:{status}
    </Badge>
  )
}

function RegisterForm() {
  const register = useCatalogStore((s) => s.register)
  const submitting = useCatalogStore((s) => s.submitting)
  const [kind, setKind] = useState<DatasetKind>('folder')
  const [path, setPath] = useState('')
  const [table, setTable] = useState('')
  const [name, setName] = useState('')
  const [privacy, setPrivacy] = useState(false)

  const canSubmit = path.trim() !== '' && (kind !== 'sql' || table.trim() !== '')

  const submit = async () => {
    const body = {
      kind,
      name: name.trim() || undefined,
      privacy_mode: privacy ? true : undefined,
      ...(kind === 'file' && { path }),
      ...(kind === 'folder' && { root: path }),
      ...(kind === 'sql' && { conn_target: path, table }),
    }
    await register(body)
    setPath('')
    setTable('')
    setName('')
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">注册数据源</h2>
      <Select value={kind} onValueChange={(v) => setKind(v as DatasetKind)}>
        <SelectTrigger size="sm" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="folder">挂载文件夹（glob 展开）</SelectItem>
          <SelectItem value="file">单个文件 CSV/Parquet/XLSX</SelectItem>
          <SelectItem value="sql">SQLite 库（只读反射）</SelectItem>
        </SelectContent>
      </Select>
      <Input
        value={path}
        onChange={(e) => setPath(e.target.value)}
        placeholder={kind === 'sql' ? '/data/x.db 库文件路径' : '/data/... 容器内绝对路径'}
        className="font-mono text-xs"
      />
      {kind === 'sql' && (
        <Input value={table} onChange={(e) => setTable(e.target.value)} placeholder="表名" className="text-xs" />
      )}
      <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="别名（默认取文件名）" className="text-xs" />
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} />
        隐私模式（schema-only，禁止原始行）
      </label>
      <Button size="sm" disabled={!canSubmit || submitting} onClick={submit} className="w-full">
        {submitting ? <Spinner className="size-4" /> : '注册'}
      </Button>
      <p className="text-muted-foreground text-[11px]">路径须在 DATA_ROOT 卷内（注册即异步扫描+画像）</p>
    </div>
  )
}

function BriefRow({ brief, active, onClick }: { brief: DatasetBrief; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full space-y-1 rounded-md border p-2 text-left transition-colors hover:bg-accent ${
        active ? 'border-primary bg-accent' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs">{brief.name}</span>
        <Badge variant="outline" className="shrink-0 text-[10px]">{brief.kind}</Badge>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <StatusBadge label="scan" status={brief.scan_status} />
        <StatusBadge label="profile" status={brief.profile_status} />
        {brief.privacy_mode && <Badge variant="outline" className="text-[10px]">🔒</Badge>}
        {brief.row_count != null && (
          <span className="text-muted-foreground text-[11px]">{brief.row_count.toLocaleString()} 行</span>
        )}
      </div>
    </button>
  )
}

function DetailPanel() {
  const detail = useCatalogStore((s) => s.detail)
  const profile = useCatalogStore((s) => s.profile)
  const preview = useCatalogStore((s) => s.preview)
  const rescan = useCatalogStore((s) => s.rescan)
  const setPrivacy = useCatalogStore((s) => s.setPrivacy)
  const remove = useCatalogStore((s) => s.remove)
  const select = useCatalogStore((s) => s.select)
  const [confirmDelete, setConfirmDelete] = useState(false)

  if (!detail) return <div className="text-muted-foreground grid h-full place-items-center text-sm">选择左侧数据集查看画像</div>

  const effectivePrivacy = detail.privacy_mode ?? false
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-2 font-mono text-base font-semibold">{detail.name}</h2>
        <StatusBadge label="scan" status={detail.scan_status} />
        <StatusBadge label="profile" status={detail.profile_status} />
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => { rescan(); setConfirmDelete(false) }}>重跑扫描</Button>
          <Button size="sm" variant="outline" onClick={() => setPrivacy(!effectivePrivacy)}>
            {effectivePrivacy ? '关闭隐私' : '开启隐私'}
          </Button>
          {confirmDelete ? (
            <Button size="sm" variant="destructive" onClick={() => { remove(detail.id); select(null); setConfirmDelete(false) }}>
              确认删除？
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirmDelete(true)}>删除</Button>
          )}
        </div>
      </div>
      {detail.last_error && (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 p-2 font-mono text-xs text-destructive">
          {detail.last_error}
        </p>
      )}
      <p className="text-muted-foreground font-mono text-[11px]">rev={detail.revision || '-'} · id={detail.id}</p>

      <Separator />
      {profile ? (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">画像 · {profile.row_count.toLocaleString()} 行 × {profile.columns.length} 列</h3>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-xs">
              <thead className="bg-muted/50">
                <tr>
                  <th className="p-2 text-left font-medium">列</th>
                  <th className="p-2 text-left font-medium">类型</th>
                  <th className="p-2 text-right font-medium">缺失%</th>
                  <th className="p-2 text-right font-medium">基数</th>
                  <th className="p-2 text-left font-medium">分布/时间</th>
                  <th className="p-2 text-left font-medium">样本</th>
                </tr>
              </thead>
              <tbody>
                {profile.columns.map((c) => (
                  <tr key={c.name} className="border-t">
                    <td className="p-2 font-mono">
                      {c.name}
                      {c.pk_hint && <span title="主键候选"> 🔑</span>}
                      {c.is_time && <span title="时间列"> ⏱</span>}
                    </td>
                    <td className="p-2 text-muted-foreground">{c.dtype}</td>
                    <td className="p-2 text-right">{(c.null_rate * 100).toFixed(1)}</td>
                    <td className="p-2 text-right">{c.cardinality ?? '-'}</td>
                    <td className="p-2 font-mono">
                      {c.num_range ? `${c.num_range[0].toPrecision(4)}..${c.num_range[1].toPrecision(4)}` : ''}
                      {c.is_time && c.time_min ? `${c.time_min.slice(0, 10)}..${(c.time_max ?? '').slice(0, 10)}` : ''}
                      {c.top_values.length > 0 && (
                        <span className="text-muted-foreground"> top: {c.top_values.map(String).join(' | ')}</span>
                      )}
                    </td>
                    <td className="p-2 font-mono text-muted-foreground">{c.sample_values.map(String).join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        detail.scan_status === 'failed' ? null : <p className="text-muted-foreground text-sm">画像尚未就绪（轮询中…）</p>
      )}

      {preview && (
        <>
          <Separator />
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">
              预览 · {preview.mode === 'rows' ? '原始行' : '统计摘要（隐私模式）'}
              {preview.mode === 'rows' && preview.truncated && <span className="text-muted-foreground font-normal"> （已截断）</span>}
            </h3>
            {preview.mode === 'rows' ? (
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      {preview.columns.map((c) => <th key={c} className="p-2 text-left font-medium">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r, i) => (
                      <tr key={i} className="border-t">
                        {preview.columns.map((c) => (
                          <td key={c} className="max-w-60 truncate p-2 font-mono">{r[c] == null ? '' : String(r[c])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-2 text-left font-medium">列</th>
                      <th className="p-2 text-left font-medium">类型</th>
                      <th className="p-2 text-right font-medium">缺失%</th>
                      <th className="p-2 text-right font-medium">基数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.columns.map((c) => (
                      <tr key={c.name} className="border-t">
                        <td className="p-2 font-mono">{c.name}</td>
                        <td className="p-2 text-muted-foreground">{c.dtype}</td>
                        <td className="p-2 text-right">{(c.null_rate * 100).toFixed(1)}</td>
                        <td className="p-2 text-right">{c.cardinality ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function DatasourcesPage() {
  const briefs = useCatalogStore((s) => s.briefs)
  const error = useCatalogStore((s) => s.error)
  const selectedId = useCatalogStore((s) => s.selectedId)
  const listLoaded = useCatalogStore((s) => s.listLoaded)
  const refreshList = useCatalogStore((s) => s.refreshList)
  const select = useCatalogStore((s) => s.select)
  const clearError = useCatalogStore((s) => s.clearError)

  useEffect(() => {
    refreshList()
    return stopCatalogPolling
  }, [refreshList])

  return (
    <div className="mx-auto flex h-full w-full max-w-6xl gap-4 px-4 py-4">
      <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto">
        <RegisterForm />
        {error && (
          <p className="cursor-pointer rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive" onClick={clearError} title="点击清除">
            {error}
          </p>
        )}
        {briefs.length === 0 && listLoaded && (
          <p className="text-muted-foreground p-2 text-center text-xs">尚无数据集 — 注册上方路径开始</p>
        )}
        {briefs.map((b) => (
          <BriefRow key={b.id} brief={b} active={b.id === selectedId} onClick={() => select(b.id)} />
        ))}
      </aside>
      <section className="min-w-0 flex-1 overflow-y-auto rounded-lg border p-4">
        <DetailPanel />
      </section>
    </div>
  )
}
