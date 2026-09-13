/** canvasStore: cold-load index + lazy per-card renders; appearance overrides
 * stay local (zero network), data param edits mark the card dirty. */

import { create } from 'zustand'

import { assetsApi } from '@/api/client'
import type { AssetIndexRow, ChartAsset, RenderBundle } from '@/types/assets'

interface CanvasState {
  assets: AssetIndexRow[]
  details: Record<string, ChartAsset>
  renders: Record<string, RenderBundle>
  appearance: Record<string, Record<string, unknown>> // local-only override per asset
  dirty: Record<string, boolean> // data params changed, replay pending
  loaded: boolean
  error: string | null
  loadAll: () => Promise<void>
  detail: (id: string) => Promise<ChartAsset | null>
  ensureRender: (id: string) => Promise<void>
  replay: (id: string) => Promise<{ passed: boolean; errors: string[] }>
  setAppearanceOverride: (id: string, patch: Record<string, unknown>) => void
  saveParams: (id: string, params: Record<string, unknown>, expectedVersion: number,
               dataChanged: boolean) => Promise<ChartAsset | null>
  createSeed: (name: string, source: string, datasetName: string) => Promise<ChartAsset | null>
  setPlacement: (id: string, w: number, h: number) => Promise<void>
  rollback: (id: string, toVersion: number) => Promise<void>
  remove: (id: string) => Promise<void>
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  assets: [],
  details: {},
  renders: {},
  appearance: {},
  dirty: {},
  loaded: false,
  error: null,

  loadAll: async () => {
    try {
      const assets = await assetsApi.list()
      set({ assets, loaded: true, error: null })
      for (const a of assets) if (a.has_render) void get().ensureRender(a.id)
    } catch (e) {
      set({ error: String(e), loaded: true })
    }
  },

  detail: async (id) => {
    const cached = get().details[id]
    if (cached) return cached
    try {
      const { asset } = await assetsApi.get(id)
      set((s) => ({ details: { ...s.details, [id]: asset } }))
      return asset
    } catch (e) {
      set({ error: String(e) })
      return null
    }
  },

  ensureRender: async (id) => {
    try {
      const bundle = await assetsApi.render(id)
      set((s) => ({ renders: { ...s.renders, [id]: bundle } }))
    } catch {
      /* 409 no render yet — the card shows its status instead */
    }
  },

  replay: async (id) => {
    const r = await assetsApi.replay(id)
    await get().loadAll()
    await get().ensureRender(id)
    set((s) => ({ dirty: { ...s.dirty, [id]: false }, details: { ...s.details, [id]: undefined as unknown as ChartAsset } }))
    void get().detail(id)
    return { passed: r.gate.passed, errors: r.gate.errors }
  },

  setAppearanceOverride: (id, patch) =>
    set((s) => ({ appearance: { ...s.appearance, [id]: { ...s.appearance[id], ...patch } } })),

  saveParams: async (id, params, expectedVersion, dataChanged) => {
    try {
      const { asset } = await assetsApi.putParams(id, params, expectedVersion)
      set((s) => ({
        details: { ...s.details, [id]: asset },
        dirty: { ...s.dirty, [id]: dataChanged ? true : !!s.dirty[id] },
      }))
      await get().loadAll()
      return asset
    } catch (e) {
      set({ error: String(e) })
      return null
    }
  },

  createSeed: async (name, source, datasetName) => {
    try {
      const { asset } = await assetsApi.create({
        name, source, chart_type: 'bar',
        bindings: [{ alias: 'sales', dataset: datasetName }],
      })
      await get().loadAll()
      await get().ensureRender(asset.id)
      set((s) => ({ details: { ...s.details, [asset.id]: asset } }))
      return asset
    } catch (e) {
      set({ error: String(e) })
      return null
    }
  },

  setPlacement: async (id, w, h) => {
    const a = get().assets.find((x) => x.id === id)
    if (!a) return
    const p = { ...a.placement, w, h }
    set((s) => ({ assets: s.assets.map((x) => (x.id === id ? { ...x, placement: p } : x)) }))
    try {
      await assetsApi.setPlacement(id, p)
    } catch (e) {
      set({ error: String(e) })
    }
  },

  rollback: async (id, toVersion) => {
    try {
      const { asset } = await assetsApi.rollback(id, toVersion)
      set((s) => ({ details: { ...s.details, [id]: asset }, renders: { ...s.renders, [id]: undefined as unknown as RenderBundle } }))
      await get().ensureRender(id)
      await get().loadAll()
    } catch (e) {
      set({ error: String(e) })
    }
  },

  remove: async (id) => {
    try {
      await assetsApi.remove(id)
      await get().loadAll()
    } catch (e) {
      set({ error: String(e) })
    }
  },
}))
