/** catalogStore: dataset directory state + exponential-backoff polling (task 4.1).

Polling runs while any brief is in-flight (scan pending/scanning or profile
pending/profiling); delay doubles from 500ms up to a 5s cap and resets once idle.
 */

import { create } from 'zustand'

import { datasetsApi } from '@/api/client'
import type { Dataset, DatasetBrief, PreviewResult, RegisterBody, TableProfile } from '@/types/catalog'

const isBusy = (d: DatasetBrief) =>
  ['pending', 'scanning'].includes(d.scan_status) ||
  ['pending', 'profiling'].includes(d.profile_status)

interface CatalogState {
  briefs: DatasetBrief[]
  selectedId: string | null
  detail: Dataset | null
  profile: TableProfile | null
  preview: PreviewResult | null
  error: string | null
  submitting: boolean
  listLoaded: boolean
  refreshList: () => Promise<void>
  select: (id: string | null) => Promise<void>
  register: (body: RegisterBody) => Promise<void>
  rescan: () => Promise<void>
  setPrivacy: (privacy: boolean) => Promise<void>
  remove: (id: string) => Promise<void>
  clearError: () => void
}

let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollDelay = 500

function schedulePoll(get: () => CatalogState) {
  clearTimeout(pollTimer)
  if (!get().briefs.some(isBusy)) {
    pollDelay = 500
    return
  }
  pollTimer = setTimeout(async () => {
    await get().refreshList()
    schedulePoll(get)
  }, pollDelay)
  pollDelay = Math.min(pollDelay * 2, 5000)
}

export const useCatalogStore = create<CatalogState>((set, get) => ({
  briefs: [],
  selectedId: null,
  detail: null,
  profile: null,
  preview: null,
  error: null,
  submitting: false,
  listLoaded: false,

  clearError: () => set({ error: null }),

  refreshList: async () => {
    try {
      const briefs = await datasetsApi.list()
      set({ briefs, listLoaded: true, error: null })
      if (get().selectedId) await get().select(get().selectedId as string)
    } catch (e) {
      set({ error: String(e), listLoaded: true })
    }
  },

  select: async (id) => {
    if (!id) {
      set({ selectedId: null, detail: null, profile: null, preview: null })
      return
    }
    set({ selectedId: id, profile: null, preview: null })
    try {
      const detail = await datasetsApi.get(id)
      set({ detail })
      if (detail.scan_status === 'failed') return
      const profile = await datasetsApi.profile(id).catch(() => null)
      const preview = await datasetsApi.preview(id, 20).catch(() => null)
      set({ profile, preview })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  register: async (body) => {
    set({ submitting: true, error: null })
    try {
      await datasetsApi.register(body)
      await get().refreshList()
      schedulePoll(get)
    } catch (e) {
      set({ error: String(e) })
    } finally {
      set({ submitting: false })
    }
  },

  rescan: async () => {
    const id = get().selectedId
    if (!id) return
    try {
      await datasetsApi.rescan(id)
      await get().refreshList()
      schedulePoll(get)
    } catch (e) {
      set({ error: String(e) })
    }
  },

  setPrivacy: async (privacy) => {
    const id = get().selectedId
    if (!id) return
    try {
      await datasetsApi.patch(id, { privacy_mode: privacy })
      await get().select(id)
      await get().refreshList()
    } catch (e) {
      set({ error: String(e) })
    }
  },

  remove: async (id) => {
    try {
      await datasetsApi.remove(id)
      if (get().selectedId === id) await get().select(null)
      await get().refreshList()
    } catch (e) {
      set({ error: String(e) })
    }
  },
}))

export function stopCatalogPolling() {
  clearTimeout(pollTimer)
}
