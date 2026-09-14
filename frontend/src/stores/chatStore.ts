/** chatStore: session list + active session + AI toggle state. */

import { create } from 'zustand'

const BASE = '/api'

export interface SessionInfo { id: string; title: string; updated_at: string }

interface ChatState {
  sessions: SessionInfo[]
  activeSid: string | null
  aiEnabled: boolean
  loaded: boolean
  loadSessions: () => Promise<void>
  newSession: () => Promise<string>
  rename: (sid: string, title: string) => Promise<void>
  select: (sid: string | null) => void
  remove: (sid: string) => Promise<void>
  loadAiToggle: () => Promise<void>
  setAiToggle: (on: boolean) => Promise<void>
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' }, ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.status === 204 ? (undefined as T) : res.json()
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSid: null,
  aiEnabled: true,
  loaded: false,

  loadSessions: async () => {
    try {
      const sessions = await http<SessionInfo[]>('/sessions?limit=50')
      set({ sessions, loaded: true })
      if (!get().activeSid && sessions[0]) set({ activeSid: sessions[0].id })
    } catch {
      set({ loaded: true })
    }
  },

  newSession: async () => {
    const { id } = await http<{ id: string }>('/sessions', { method: 'POST', body: '{}' })
    set((s) => ({ sessions: [{ id, title: '', updated_at: '' }, ...s.sessions], activeSid: id }))
    return id
  },

  select: (sid) => set({ activeSid: sid }),

  rename: async (sid, title) => {
    await http(`/sessions/${sid}`, { method: 'PATCH', body: JSON.stringify({ title }) })
    set((s) => ({ sessions: s.sessions.map((x) => (x.id === sid ? { ...x, title } : x)) }))
  },

  remove: async (sid) => {
    await http(`/sessions/${sid}`, { method: 'DELETE' })
    if (get().activeSid === sid) set({ activeSid: null })
    await get().loadSessions()
  },

  loadAiToggle: async () => {
    try {
      const view = await http<{ settings: Record<string, unknown> }>('/settings')
      set({ aiEnabled: view.settings.ai_enabled !== false })
    } catch { /* keep default */ }
  },

  setAiToggle: async (on) => {
    await http('/settings', { method: 'PUT', body: JSON.stringify({ settings: { ai_enabled: on } }) })
    set({ aiEnabled: on })
  },
}))
