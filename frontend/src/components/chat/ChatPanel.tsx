/** ChatPanel: the right-hand AI coding panel (N3) — useChat against
 * /api/sessions/{sid}/chat with AI SDK v7 tool-approval flow.
 *
 * Part rendering:
 *  text -> Streamdown; tool-* -> ToolCard (run_in_kernel shows code+stdout);
 *  approval-requested -> inline approve/deny; tool-final_result -> FinalAnswer
 *  card with numbers provenance; tool-emit_adhoc_chart -> one-off chart card
 *  with promote button; data-asset-changed -> triggers canvasStore refresh. */

import { useChat } from '@ai-sdk/react'
import type { UIMessage } from 'ai'
import { DefaultChatTransport } from 'ai'
import { Check, ChevronDown, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Streamdown } from 'streamdown'

import { Button } from '@/components/ui/button'
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from '@/components/ai-elements/reasoning'
import { buildOption } from '@/lib/chartRender'
import { diffLines } from '@/lib/diffLines'
import { useCanvasStore } from '@/stores/canvasStore'
import { useChatStore } from '@/stores/chatStore'
import type { ChartConfig, RenderData } from '@/types/assets'

/* eslint-disable @typescript-eslint/no-explicit-any */
type Part = Record<string, any>

function AdhocCard({ input }: { input: Part }) {
  const ref = useRef<HTMLDivElement>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let disposed = false
    let chart: Awaited<ReturnType<typeof import('echarts').init>> | null = null
    if (!input?.render || !input?.config) return
    void import('echarts').then((echarts) => {
      if (disposed || !ref.current) return
      const config = input.config as ChartConfig
      chart = echarts.init(ref.current)
      try {
        chart.setOption(buildOption(input.render as RenderData, config, config.appearance))
      } catch (e) {
        setErr(String(e).slice(0, 120))
      }
    })
    return () => { disposed = true; chart?.dispose() }
  }, [input])

  const promote = async () => {
    const aid = String(input?.adhoc_id ?? '')
    if (!aid) return
    const r = await fetch('/api/assets/promote', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adhoc_id: aid }),
    })
    if (!r.ok) return
    const { seed_message } = await r.json()
    window.dispatchEvent(new CustomEvent('da:promote', { detail: seed_message }))
  }

  return (
    <div className="space-y-1 rounded-lg border bg-card p-2">
      <p className="text-xs font-medium">{String(input?.title ?? '即席图')}</p>
      <div ref={ref} style={{ height: 240 }} className="w-full" />
      {err && <p className="text-[10px] text-destructive">{err}</p>}
      <div className="flex justify-end">
        <Button size="xs" variant="outline" onClick={promote}>转为图表卡</Button>
      </div>
    </div>
  )
}

function FinalAnswerCard({ input }: { input: Part }) {
  const [open, setOpen] = useState(false)
  const numbers: Record<string, string> = input?.numbers ?? {}
  return (
    <div className="space-y-1.5 rounded-lg border border-primary/30 bg-primary/5 p-2.5">
      <div className="prose prose-sm dark:prose-invert max-w-none [&_p]:my-1 [&_table]:text-xs">
        <Streamdown>{String(input?.summary ?? '')}</Streamdown>
      </div>
      {Array.isArray(input?.key_findings) && input.key_findings.length > 0 && (
        <ul className="text-muted-foreground list-disc space-y-0.5 pl-4 text-xs">
          {input.key_findings.map((k: string) => <li key={k}>{k}</li>)}
        </ul>
      )}
      {Object.keys(numbers).length > 0 && (
        <button onClick={() => setOpen(!open)}
                className="text-muted-foreground flex items-center gap-1 text-[11px]">
          <ChevronDown className={`size-3 transition-transform ${open ? 'rotate-180' : ''}`} />
          数值来源（{Object.keys(numbers).length}）
        </button>
      )}
      {open && (
        <ul className="space-y-0.5 text-[11px]">
          {Object.entries(numbers).map(([n, src]) => (
            <li key={n} className="font-mono">{n} ← {src}</li>
          ))}
        </ul>
      )}
      {Array.isArray(input?.followups) && input.followups.length > 0 && (
        <p className="text-muted-foreground text-[11px]">建议：{input.followups.join('；')}</p>
      )}
    </div>
  )
}

function ApprovalDiff({ part }: { part: Part }) {
  const name = String(part.type ?? '').replace(/^tool-/, '')
  const [oldSrc, setOldSrc] = useState<string | null>(null)
  useEffect(() => {
    const aid = part.input?.asset_id
    if (name !== 'write_processor' || !aid) return
    void fetch(`/api/assets/${aid}`).then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setOldSrc(String(j.source ?? '')))
      .catch(() => setOldSrc(''))
  }, [name, part.input?.asset_id])

  if (name === 'save_asset') {
    return (
      <div className="space-y-1 text-[11px]">
        <p className="text-muted-foreground">上画布确认 —— 该资产已过闸，params 决定首次渲染：</p>
        <pre className="bg-muted/60 rounded p-1 font-mono text-[10px]">{JSON.stringify(part.input)}</pre>
      </div>
    )
  }
  const newSrc = String(part.input?.source ?? '')
  const rows = oldSrc != null && newSrc ? diffLines(oldSrc, newSrc) : null
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-[11px]">
        {part.input?.name ?? part.input?.asset_id ?? '新资产'}
        {' · 绑定 '}{JSON.stringify(part.input?.bindings ?? []).slice(0, 120)}
        {part.input?.chart_type ? ` · ${part.input.chart_type}` : ''}
      </p>
      {rows ? (
        <div className="bg-muted/40 max-h-40 overflow-auto rounded p-1 font-mono text-[10px] leading-tight">
          {rows.map((r, i) => (
            <div key={i} className={r.kind === 'add' ? 'text-emerald-500'
              : r.kind === 'del' ? 'text-destructive' : 'text-muted-foreground'}>
              {r.kind === 'add' ? '+ ' : r.kind === 'del' ? '- ' : '  '}{r.text}
            </div>
          ))}
        </div>
      ) : newSrc ? (
        <pre className="bg-muted/60 max-h-40 overflow-auto rounded p-1 font-mono text-[10px] leading-tight">
          {newSrc.slice(0, 1600)}
        </pre>
      ) : (
        <pre className="bg-muted/60 max-h-32 overflow-auto rounded p-1 font-mono text-[10px]">
          {JSON.stringify(part.input).slice(0, 800)}
        </pre>
      )}
    </div>
  )
}

function ToolCard({ part, onApprove }: { part: Part; onApprove: (approved: boolean, reason?: string) => void }) {
  const name = String(part.type ?? '').replace(/^tool-/, '')
  const state: string = part.state ?? ''
  const out = part.output
  const outText = typeof out === 'string' ? out : out == null ? '' : JSON.stringify(out)
  const isRun = name === 'run_in_kernel'
  const badge = state === 'output-error' ? 'destructive'
    : state.startsWith('approval') ? 'outline' : 'secondary'
  const failed = out?.ok === false || state === 'output-error'

  return (
    <div className="rounded-lg border bg-card p-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] font-medium">{name}</span>
        <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${
          badge === 'destructive' ? 'bg-destructive/15 text-destructive'
            : badge === 'outline' ? 'border text-[10px]' : 'bg-secondary text-secondary-foreground'}`}>
          {state.replace(/-/g, ' ')}
        </span>
        {typeof part.input?.purpose === 'string' && (
          <span className="text-muted-foreground truncate text-[10px]">{part.input.purpose}</span>
        )}
      </div>
      {part.input && (isRun || name === 'write_processor') && (
        <pre className="bg-muted/60 mt-1.5 max-h-40 overflow-auto rounded p-1.5 font-mono text-[10px] leading-tight">
          {String(part.input.code ?? part.input.source ?? '').slice(0, 2000)}
        </pre>
      )}
      {state === 'approval-requested' && (
        <div className="mt-2 space-y-1.5 rounded-md border border-primary/40 bg-primary/10 p-2">
          <p className="text-xs font-medium">需要你的批准：{name}</p>
          {part.approval?.requestReason && (
            <p className="text-muted-foreground text-[11px]">{part.approval.requestReason}</p>
          )}
          <ApprovalDiff part={part} />
          <div className="flex justify-end gap-2">
            <Button size="xs" variant="outline" onClick={() => onApprove(false, '用户拒绝')}><X className="size-3" />拒绝</Button>
            <Button size="xs" onClick={() => onApprove(true)}><Check className="size-3" />批准</Button>
          </div>
        </div>
      )}
      {(state === 'output-available' || state === 'output-error') && out != null && (
        !isRun ? (
          <p className="text-muted-foreground mt-1 font-mono text-[10px]">{outText.slice(0, 300)}</p>
        ) : (
          <pre className={`mt-1.5 max-h-44 overflow-auto rounded p-1.5 font-mono text-[10px] leading-tight ${
            failed ? 'bg-destructive/10 text-destructive' : 'bg-muted/60'}`}>
            {String(out.stdout ?? out.error ?? outText).slice(0, 1500)}
          </pre>
        )
      )}
    </div>
  )
}

export function ChatPanel() {
  const sid = useChatStore((s) => s.activeSid)
  const [restored, setRestored] = useState<UIMessage[] | null>(null)

  useEffect(() => {
    setRestored(null)
    if (!sid) return
    void fetch(`/api/sessions/${sid}/messages`)
      .then((r) => (r.ok ? r.json() : []))
      .then((ms) => setRestored(Array.isArray(ms) ? ms : []))
      .catch(() => setRestored([]))
  }, [sid])

  if (!sid) return <p className="text-muted-foreground p-4 text-xs">未选择会话</p>
  if (restored === null) return <p className="text-muted-foreground p-4 text-xs">恢复会话…</p>
  // key forces re-init of useChat with the restored copy when switching sessions
  return <ChatInner key={`${sid}:${restored.length}`} sid={sid} initial={restored} />
}

function ChatInner({ sid, initial }: { sid: string; initial: UIMessage[] }) {
  const aiEnabled = useChatStore((s) => s.aiEnabled)
  const newSession = useChatStore((s) => s.newSession)
  const loadAll = useCanvasStore((s) => s.loadAll)
  const [text, setText] = useState('')
  const seenAssets = useRef(new Set<string>())

  const transport = useMemo(
    () => new DefaultChatTransport({ api: `/api/sessions/${sid}/chat` }),
    [sid],
  )

  const { messages, sendMessage, status, addToolApprovalResponse } = useChat({
    id: sid,
    messages: initial.length ? initial : undefined,
    transport,
    sendAutomaticallyWhen: ({ messages: ms }: { messages: UIMessage[] }) => {
      const last = ms[ms.length - 1]
      if (!last || last.role !== 'assistant') return false
      const tools = (last.parts as Part[]).filter((p) => String(p.type).startsWith('tool-'))
      return tools.length > 0 && tools.every((p) => p.state === 'approval-responded')
    },
  } as never)

  // data-asset-changed -> refresh canvas (dedupe by asset+version)
  useEffect(() => {
    for (const m of messages) {
      for (const p of m.parts as Part[]) {
        if (p.type === 'data-asset-changed' && p.data) {
          const key = `${p.data.asset_id}:${p.data.version}:${p.data.gate_passed}`
          if (!seenAssets.current.has(key)) {
            seenAssets.current.add(key)
            void loadAll()
          }
        }
      }
    }
  }, [messages, loadAll])

  // promote event -> send seed message into this chat
  useEffect(() => {
    const h = (e: Event) => {
      const detail = (e as CustomEvent).detail as string
      if (detail) void sendMessage({ text: detail })
    }
    window.addEventListener('da:promote', h)
    return () => window.removeEventListener('da:promote', h)
  }, [sendMessage])

  const submit = async () => {
    const t = text.trim()
    if (!t) return
    setText('')
    if (!sid) await newSession()
    void sendMessage({ text: t })
  }

  const busy = status === 'streaming' || status === 'submitted'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {messages.length === 0 && (
          <div className="text-muted-foreground flex flex-col items-center gap-2 pt-10 text-center text-xs">
            <Sparkles className="size-5 text-primary" />
            <p>让 AI 探查数据、试跑并编写图表 processor。<br />写资产与上画布会请求你的批准。</p>
          </div>
        )}
        {messages.map((m: UIMessage) => (
          <div key={m.id} className={m.role === 'user' ? 'flex justify-end' : ''}>
            {m.role === 'user' ? (
              <div className="bg-primary text-primary-foreground max-w-[85%] rounded-2xl px-3 py-1.5 text-sm">
                {(m.parts as Part[]).filter((p) => p.type === 'text').map((p, i) => (
                  <span key={i}>{p.text}</span>
                ))}
              </div>
            ) : (
              <div className="w-full space-y-1.5">
                {(m.parts as Part[]).map((p, i) => {
                  if (p.type === 'text') {
                    return String(p.text).trim() ? (
                      <div key={i} className="prose prose-sm dark:prose-invert max-w-none text-sm [&_p]:my-1">
                        <Streamdown>{String(p.text)}</Streamdown>
                      </div>
                    ) : null
                  }
                  if (p.type === 'reasoning') {
                    return (
                      <Reasoning key={i} isStreaming={p.state === 'streaming'}>
                        <ReasoningTrigger />
                        <ReasoningContent>{String(p.text ?? '')}</ReasoningContent>
                      </Reasoning>
                    )
                  }
                  if (String(p.type).startsWith('data-')) {
                    return p.type === 'data-run' ? (
                      <p key={i} className="text-muted-foreground font-mono text-[10px]">
                        run {p.data?.status} · {p.data?.tokens ?? 0} tok · reflects {p.data?.reflects_used ?? 0}
                        {p.data?.error ? ` · ${String(p.data.error).slice(0, 100)}` : ''}
                      </p>
                    ) : null
                  }
                  if (p.type === 'tool-emit_adhoc_chart' && p.state === 'input-available') {
                    const aid = /adhoc: (ad_\w+)/.exec(String(p.output ?? ''))?.[1]
                    return <AdhocCard key={i} input={{ ...p.input, adhoc_id: aid }} />
                  }
                  if (p.type === 'tool-final_result') {
                    return <FinalAnswerCard key={i} input={p.input ?? p.output ?? {}} />
                  }
                  if (String(p.type).startsWith('tool-')) {
                    return (
                      <ToolCard key={i} part={p}
                                onApprove={(approved, reason) =>
                                  addToolApprovalResponse({ id: p.approval?.id, approved, reason } as never)} />
                    )
                  }
                  return null
                })}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="border-t p-2">
        <div className="flex items-end gap-2">
          <textarea
            value={text}
            disabled={!aiEnabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void submit() } }}
            placeholder={aiEnabled ? '描述你要的图表 / 问数（Enter 发送）' : 'AI 已关闭（顶栏开关恢复）'}
            rows={2}
            className="min-h-[2.5rem] flex-1 resize-none rounded-md border bg-background px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-primary disabled:opacity-50"
          />
          <Button size="sm" onClick={submit} disabled={busy || !text.trim() || !aiEnabled}>
            {busy ? '…' : '发送'}
          </Button>
        </div>
      </div>
    </div>
  )
}
