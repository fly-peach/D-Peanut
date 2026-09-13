/** VSCode-style Workspace: left tree (sessions/datasets) · center canvas (main
 * work area) · right AI panel placeholder (goes live in N3). */

import { Database, Folder, FileText, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { ChartCard } from '@/components/canvas/ChartCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCanvasStore } from '@/stores/canvasStore'
import { useCatalogStore } from '@/stores/catalogStore'
import { stopCatalogPolling } from '@/stores/catalogStore'
import { BAR_TOPN_SOURCE } from '@/lib/seedProcessors'

function LeftTree() {
  const briefs = useCatalogStore((s) => s.briefs)
  const refresh = useCatalogStore((s) => s.refreshList)
  useEffect(() => {
    void refresh()
    return stopCatalogPolling
  }, [refresh])
  const { parents, childrenOf } = useMemo(() => {
    const parents = briefs.filter((b) => !b.parent_id)
    const childrenOf = new Map<string, typeof briefs>()
    for (const b of briefs.filter((x) => x.parent_id)) {
      const list = childrenOf.get(b.parent_id as string) ?? []
      list.push(b)
      childrenOf.set(b.parent_id as string, list)
    }
    return { parents, childrenOf }
  }, [briefs])
  return (
    <aside className="flex w-60 shrink-0 flex-col gap-0.5 overflow-y-auto border-r bg-sidebar px-2 py-3">
      <p className="text-muted-foreground flex items-center gap-1 px-1 pb-1 text-[11px] font-medium">
        <Database className="size-3" /> 数据源（{briefs.length}）
      </p>
      {parents.map((b) => (
        <div key={b.id}>
          <div className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs">
            {b.kind === 'folder' ? <Folder className="size-3.5 shrink-0 text-muted-foreground" />
              : <FileText className="size-3.5 shrink-0 text-muted-foreground" />}
            <span className="truncate">{b.name}</span>
            {b.profile_status !== 'ready' && b.kind !== 'folder' && (
              <span className="bg-muted ml-auto rounded px-1 text-[10px]">{b.profile_status}</span>
            )}
          </div>
          {(childrenOf.get(b.id) ?? []).map((c) => (
            <div key={c.id} className="ml-5 flex items-center gap-1.5 truncate rounded px-1 py-0.5 text-[11px] text-muted-foreground">
              <FileText className="size-3 shrink-0" />
              <span className="truncate">{c.name.split('/').pop()}</span>
              {c.row_count != null && <span className="ml-auto shrink-0">{c.row_count}</span>}
            </div>
          ))}
        </div>
      ))}
      {briefs.length === 0 && <p className="px-1 text-[11px] text-muted-foreground">先到「数据源」页注册路径</p>}
    </aside>
  )
}

function CanvasArea() {
  const assets = useCanvasStore((s) => s.assets)
  const renders = useCanvasStore((s) => s.renders)
  const loaded = useCanvasStore((s) => s.loaded)
  const loadAll = useCanvasStore((s) => s.loadAll)
  const createSeed = useCanvasStore((s) => s.createSeed)
  const error = useCanvasStore((s) => s.error)
  const briefs = useCatalogStore((s) => s.briefs)
  const [nameSeq, setNameSeq] = useState(1)

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const fileBriefs = briefs.filter((b) => b.kind === 'file' && b.profile_status === 'ready')
  const createDemo = async () => {
    const pick = fileBriefs[0]
    if (!pick) {
      alert('没有 ready 的文件数据集，先到数据源页注册')
      return
    }
    await createSeed(`示例TopN_${nameSeq}`, BAR_TOPN_SOURCE, pick.name)
    setNameSeq((n) => n + 1)
  }

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <h2 className="text-sm font-medium">画布</h2>
        <span className="text-muted-foreground text-xs">{assets.length} 张卡</span>
        <div className="ml-auto flex gap-2">
          <Button size="xs" variant="outline" onClick={() => loadAll()}>刷新</Button>
          <Button size="xs" onClick={() => void createDemo()}>创建示例卡（seed processor）</Button>
        </div>
      </div>
      {error && <p className="border-b border-destructive/30 bg-destructive/10 px-4 py-1.5 text-xs text-destructive">{error}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {assets.length === 0 ? (
          <div className="text-muted-foreground grid h-full place-items-center text-sm">
            {loaded ? '画布为空 — 点右上「创建示例卡」体验确定性重放，N3 起由 AI 建卡' : '加载…'}
          </div>
        ) : (
          <div className="grid auto-rows-min grid-cols-12 gap-4">
            {assets.map((a) => (
              <div key={a.id} style={{ gridColumn: `span ${Math.min(12, a.placement.w)}` }}
                   className="col-span-12 md:col-auto">
                <ChartCard row={a} bundle={renders[a.id]} />
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}

function RightAiPanel() {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-l bg-sidebar">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Sparkles className="size-4 text-primary" />
        <span className="text-sm font-medium">AI 编码面板</span>
        <span className="bg-secondary text-muted-foreground ml-auto rounded-full px-2 py-0.5 text-[10px]">N3 启用</span>
      </div>
      <div className="flex-1 p-3">
        <p className="text-muted-foreground text-xs leading-relaxed">
          这里是数据画布的“作者”。到 N3（ai-coding-loop）阶段，它将支持：
          自然语言 → 试跑内核验证 → write_processor（审批弹窗）→
          闸门自修 → save_asset 落画布；轻模式即席问数；promote 转卡；
          以及顶部 AI toggle 的开关在场控制。
        </p>
        <div className="text-muted-foreground/60 mt-6 rounded-lg border border-dashed p-4 text-center text-xs">
          对话输入将在 N3 接入 useChat 流
        </div>
      </div>
      <div className="border-t px-3 py-2">
        <Input disabled placeholder="AI 面板未启用（N3）" className="h-7 text-xs" />
      </div>
    </aside>
  )
}

export default function Workspace() {
  return (
    <div className="flex h-full min-h-0">
      <LeftTree />
      <CanvasArea />
      <RightAiPanel />
    </div>
  )
}
