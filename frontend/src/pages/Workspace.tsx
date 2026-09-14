/** VSCode-style Workspace: left tree (sessions/datasets) · center canvas (main
 * work area) · right AI panel placeholder (goes live in N3). */

import { Database, Folder, FileText, PanelLeftClose, PanelLeftOpen, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ChatPanel } from '@/components/chat/ChatPanel'
import { ChartCard } from '@/components/canvas/ChartCard'
import { Button } from '@/components/ui/button'
import { useCanvasStore } from '@/stores/canvasStore'
import { useCatalogStore } from '@/stores/catalogStore'
import { useChatStore } from '@/stores/chatStore'
import { stopCatalogPolling } from '@/stores/catalogStore'
import { BAR_TOPN_SOURCE } from '@/lib/seedProcessors'

/* ---- sidebar width/collapse（持久化，带上下限）---- */
const SB_MIN = 180
const SB_MAX = 420
const SB_DEFAULT = 240
const clampW = (w: number) => Math.min(SB_MAX, Math.max(SB_MIN, Math.round(w)))

function useSidebarState() {
  const [width, setWidthState] = useState(() => {
    const n = Number(localStorage.getItem('data-agent.sidebar.width'))
    return Number.isFinite(n) && n > 0 ? clampW(n) : SB_DEFAULT
  })
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('data-agent.sidebar.collapsed') === '1')
  useEffect(() => { localStorage.setItem('data-agent.sidebar.width', String(width)) }, [width])
  useEffect(() => { localStorage.setItem('data-agent.sidebar.collapsed', collapsed ? '1' : '0') }, [collapsed])
  const setWidth = (w: number) => setWidthState(clampW(w))
  return { width, setWidth, collapsed, setCollapsed }
}

function LeftTree({ width, onResize, onCollapse }: {
  width: number
  onResize: (w: number) => void
  onCollapse: () => void
}) {
  const briefs = useCatalogStore((s) => s.briefs)
  const refresh = useCatalogStore((s) => s.refreshList)
  const drag = useRef<{ startX: number; startW: number } | null>(null)
  useEffect(() => {
    void refresh()
    return stopCatalogPolling
  }, [refresh])
  const onDragStart = (e: React.PointerEvent<HTMLDivElement>) => {
    drag.current = { startX: e.clientX, startW: width }
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }
  const onDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    onResize(drag.current.startW + (e.clientX - drag.current.startX))
  }
  const onDragEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    drag.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
  }
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
    <aside style={{ width }} className="relative flex shrink-0 flex-col gap-0.5 overflow-y-auto border-r bg-sidebar px-2 py-3">
      <p className="text-muted-foreground flex items-center gap-1 px-1 pb-1 text-[11px] font-medium">
        <Database className="size-3" /> 数据源（{briefs.length}）
        <button onClick={onCollapse} title="折叠侧边栏"
                className="ml-auto rounded p-0.5 hover:bg-accent hover:text-foreground">
          <PanelLeftClose className="size-3.5" />
        </button>
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
      {/* 拖拽把手：右缘 1px 视觉线 + 5px 命中区；双击恢复默认宽 */}
      <div
        role="separator" aria-orientation="vertical"
        onPointerDown={onDragStart} onPointerMove={onDragMove} onPointerUp={onDragEnd}
        onDoubleClick={() => onResize(SB_DEFAULT)}
        title="拖拽调宽 · 双击复位（180–420px）"
        className="absolute inset-y-0 right-0 z-10 w-[5px] cursor-col-resize select-none transition-colors hover:bg-primary/40"
      />
    </aside>
  )
}

function CanvasArea({ showSidebarToggle, onToggleSidebar }: {
  showSidebarToggle: boolean
  onToggleSidebar: () => void
}) {
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
        {showSidebarToggle && (
          <button onClick={onToggleSidebar} title="展开侧边栏"
                  className="text-muted-foreground rounded p-1 transition-colors hover:bg-accent hover:text-foreground">
            <PanelLeftOpen className="size-4" />
          </button>
        )}
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
  const aiEnabled = useChatStore((s) => s.aiEnabled)
  const sessions = useChatStore((s) => s.sessions)
  const activeSid = useChatStore((s) => s.activeSid)
  const select = useChatStore((s) => s.select)
  const newSession = useChatStore((s) => s.newSession)
  const loadSessions = useChatStore((s) => s.loadSessions)
  useEffect(() => {
    void loadSessions()
  }, [loadSessions])

  return (
    <aside className="flex w-96 shrink-0 flex-col border-l bg-sidebar">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Sparkles className="size-4 text-primary" />
        <span className="text-sm font-medium">AI 编码面板</span>
        {aiEnabled
          ? <span className="bg-primary/10 text-primary ml-auto rounded-full px-2 py-0.5 text-[10px]">ON</span>
          : <span className="bg-secondary text-muted-foreground ml-auto rounded-full px-2 py-0.5 text-[10px]">OFF</span>}
        <Button size="xs" variant="outline" onClick={() => void newSession()}>新会话</Button>
      </div>
      {sessions.length > 1 && (
        <div className="flex gap-1 overflow-x-auto border-b px-2 py-1">
          {sessions.slice(0, 8).map((s) => (
            <button key={s.id} onClick={() => select(s.id)}
                    className={`shrink-0 rounded px-2 py-0.5 text-[10px] ${
                      s.id === activeSid ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:bg-accent'}`}>
              {s.title || s.id.slice(3, 9)}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        {activeSid ? <ChatPanel /> : (
          <p className="text-muted-foreground p-4 text-center text-xs">点「新会话」开始与 AI 协作</p>
        )}
      </div>
    </aside>
  )
}

export default function Workspace() {
  const sidebar = useSidebarState()
  return (
    <div className="flex h-full min-h-0">
      {!sidebar.collapsed && (
        <LeftTree width={sidebar.width} onResize={sidebar.setWidth}
                  onCollapse={() => sidebar.setCollapsed(true)} />
      )}
      <CanvasArea showSidebarToggle={sidebar.collapsed}
                  onToggleSidebar={() => sidebar.setCollapsed(false)} />
      <RightAiPanel />
    </div>
  )
}
