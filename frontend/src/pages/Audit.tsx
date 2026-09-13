/** Audit page (N4): per-asset lifecycle (versions + replay timeline) and the
 * message/run copy of sessions — the "who touched what, when, passed?" screen. */

import { useEffect, useState } from 'react'

import { assetsApi } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { useCanvasStore } from '@/stores/canvasStore'
import { useChatStore } from '@/stores/chatStore'

interface Replay { version: number; trigger: string; passed: boolean; errors: string[];
  elapsed_s: number; ran_at: string }

export default function AuditPage() {
  const assets = useCanvasStore((s) => s.assets)
  const loadAll = useCanvasStore((s) => s.loadAll)
  const sessions = useChatStore((s) => s.sessions)
  const loadSessions = useChatStore((s) => s.loadSessions)
  const [sel, setSel] = useState<string | null>(null)
  const [history, setHistory] = useState<{ versions: number[]; replays: Replay[] } | null>(null)
  const [sessionMsgs, setSessionMsgs] = useState<{ id: string; msgs: unknown[] } | null>(null)

  useEffect(() => {
    void loadAll()
    void loadSessions()
  }, [loadAll, loadSessions])

  useEffect(() => {
    if (!sel) return
    void assetsApi.history(sel).then((h) => setHistory(h as unknown as { versions: number[]; replays: Replay[] }))
  }, [sel])

  const openSession = async (id: string) => {
    const ms = await fetch(`/api/sessions/${id}/messages`).then((r) => (r.ok ? r.json() : []))
    setSessionMsgs({ id, msgs: ms })
  }

  return (
    <div className="mx-auto grid h-full w-full max-w-6xl grid-cols-1 gap-4 overflow-y-auto px-4 py-4 lg:grid-cols-2">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">资产生命周期</h2>
        {assets.length === 0 && <p className="text-muted-foreground text-xs">尚无资产</p>}
        <div className="space-y-1">
          {assets.map((a) => (
            <button key={a.id} onClick={() => setSel(a.id)}
                    className={`w-full rounded-md border p-2 text-left text-xs hover:bg-accent ${
                      sel === a.id ? 'border-primary' : ''}`}>
              <span className="font-medium">{a.name}</span>
              <span className="text-muted-foreground ml-2 font-mono">v{a.version} · {a.chart_type}</span>
              <span className="float-right flex gap-1">
                {a.stale_data && <Badge variant="outline" className="border-amber-500/60 text-amber-500 text-[10px]">stale</Badge>}
                {a.gate_passed === false && <Badge variant="destructive" className="text-[10px]">闸门失败</Badge>}
                <Badge variant="secondary" className="text-[10px]">{a.status}</Badge>
              </span>
            </button>
          ))}
        </div>
        {sel && history && (
          <div className="space-y-1.5 rounded-lg border bg-card p-3 text-xs">
            <p className="text-muted-foreground">快照版本：{history.versions.join(' / ') || '无'}</p>
            <div className="max-h-96 space-y-1 overflow-y-auto">
              {history.replays.map((r, i) => (
                <div key={i} className="flex items-start gap-2 border-b border-border/40 pb-1">
                  <span className={r.passed ? 'text-emerald-500' : 'text-destructive'}>
                    {r.passed ? '✓' : '✗'}
                  </span>
                  <span className="font-mono">v{r.version}</span>
                  <span className="text-muted-foreground">{r.trigger}</span>
                  <span className="text-muted-foreground ml-auto shrink-0 font-mono text-[10px]">
                    {r.elapsed_s}s · {r.ran_at.slice(5, 19)}
                  </span>
                </div>
              ))}
              {history.replays.find((r) => !r.passed)?.errors.map((e) => (
                <p key={e} className="text-destructive/90 break-all text-[10px]">{e}</p>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">会话副本（服务端恢复源）</h2>
        {sessions.length === 0 && <p className="text-muted-foreground text-xs">尚无会话</p>}
        <div className="space-y-1">
          {sessions.map((s) => (
            <button key={s.id} onClick={() => void openSession(s.id)}
                    className="w-full rounded-md border p-2 text-left text-xs hover:bg-accent">
              <span className="font-mono">{s.title || s.id}</span>
              <span className="text-muted-foreground ml-2 text-[10px]">{s.updated_at?.slice(0, 19)}</span>
            </button>
          ))}
        </div>
        {sessionMsgs && (
          <div className="rounded-lg border bg-card p-3 text-xs">
            <p className="text-muted-foreground mb-1">
              {sessionMsgs.id} · {sessionMsgs.msgs.length} 条消息
            </p>
            <pre className="max-h-96 overflow-auto font-mono text-[10px] leading-tight">
              {JSON.stringify(sessionMsgs.msgs.map((raw) => {
                const m = raw as { role?: string; parts?: { type: string }[] }
                return { role: m.role, parts: (m.parts ?? []).map((p) => p.type) }
              }), null, 1)}
            </pre>
          </div>
        )}
      </section>
    </div>
  )
}
