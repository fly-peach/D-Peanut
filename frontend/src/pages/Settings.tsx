/** Settings page (N3): model area (provider presets / base_url / key masked /
 * test connection) + read-only runtime config + masked secret names. */

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { settingsApi, type SettingsView } from '@/api/client'

const PROVIDERS = [
  { id: 'test', label: 'test（离线演示，无需 key）', url: '', model: '' },
  { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com/v1', model: 'gpt-4.1' },
  { id: 'deepseek', label: 'DeepSeek', url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { id: 'dashscope', label: '阿里 DashScope (兼容)', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { id: 'zhipu', label: '智谱 GLM', url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus' },
  { id: 'moonshot', label: 'Moonshot', url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-32k' },
  { id: 'custom', label: 'Custom（OpenAI 兼容网关）', url: '', model: '' },
]

function ModelSection({ view, refresh }: { view: SettingsView; refresh: () => void }) {
  const s = view.settings
  const [provider, setProvider] = useState(String(s.llm_provider ?? 'test'))
  const [baseUrl, setBaseUrl] = useState(String(s.llm_base_url ?? ''))
  const [model, setModel] = useState(String(s.llm_model ?? ''))
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  const preset = PROVIDERS.find((p) => p.id === provider)

  const save = async () => {
    setBusy(true)
    try {
      await settingsApi.put({
        settings: { llm_provider: provider, llm_base_url: baseUrl, llm_model: model },
        ...(key ? { secrets: { 'llm.api_key': key } } : {}),
      })
      setResult('已保存（热生效，无需重启）')
      refresh()
    } catch (e) {
      setResult(String(e))
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    setBusy(true)
    try {
      const r = await fetch('/api/settings/llm/test', { method: 'POST' })
      const j = await r.json()
      setResult(j.ok ? `✓ 连通 ${j.latency_ms}ms · ${j.model}` : `✗ ${j.error}`)
    } catch (e) {
      setResult(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 text-xs">
        <label className="space-y-1">
          <span className="text-muted-foreground">Provider</span>
          <select value={provider} className="h-8 w-full rounded-md border bg-background px-2"
                  onChange={(e) => {
                    setProvider(e.target.value)
                    const p = PROVIDERS.find((x) => x.id === e.target.value)
                    if (p && p.id !== 'custom' && p.id !== 'test') {
                      setBaseUrl(p.url)
                      if (p.model) setModel(p.model)
                    }
                  }}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-muted-foreground">模型名</span>
          <Input value={model} onChange={(e) => setModel(e.target.value)} className="h-8 text-xs"
                 placeholder={preset?.model || 'gpt-4.1 / deepseek-chat …'} />
        </label>
        <label className="col-span-2 space-y-1">
          <span className="text-muted-foreground">Base URL（OpenAI 兼容端点）</span>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
                 className="h-8 font-mono text-xs" placeholder="https://..." disabled={provider === 'test'} />
        </label>
        <label className="col-span-2 space-y-1">
          <span className="text-muted-foreground">
            API key（当前：{view.secrets['llm.api_key'] ?? '未设置'}，留空不覆盖）
          </span>
          <Input value={key} onChange={(e) => setKey(e.target.value)} type="password"
                 className="h-8 font-mono text-xs" placeholder="sk-..." />
        </label>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={busy} onClick={() => void save()}>保存</Button>
        <Button size="sm" variant="outline" disabled={busy || provider === 'test'} onClick={() => void test()}>
          测试连接
        </Button>
        {result && <span className="text-muted-foreground text-[11px]">{result.slice(0, 120)}</span>}
      </div>
    </div>
  )
}

export default function Settings() {
  const [view, setView] = useState<SettingsView | null>(null)
  const refresh = () => void settingsApi.get().then(setView).catch(() => setView(null))
  useEffect(refresh, [])
  if (!view) return <p className="text-muted-foreground p-6 text-sm">加载配置…</p>
  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">模型</h2>
        <ModelSection view={view} refresh={refresh} />
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">运行配置</h2>
        <table className="w-full text-xs">
          <tbody>
            <tr className="border-b border-border/60">
              <td className="text-muted-foreground py-1 pr-4">DATA_ROOT</td>
              <td className="font-mono">{view.data_root}</td>
            </tr>
            <tr className="border-b border-border/60">
              <td className="text-muted-foreground py-1 pr-4">WORKSPACE_ROOT</td>
              <td className="font-mono">{view.workspace_root}</td>
            </tr>
            {Object.entries(view.settings)
              .filter(([k]) => !k.startsWith('llm_'))
              .map(([k, v]) => (
                <tr key={k} className="border-b border-border/60">
                  <td className="text-muted-foreground py-1 pr-4">{k}</td>
                  <td className="font-mono">{JSON.stringify(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">敏感项（仅名称与掩码）</h2>
        {Object.keys(view.secrets).length === 0 ? (
          <p className="text-muted-foreground text-xs">尚无密钥/连接串</p>
        ) : (
          Object.entries(view.secrets).map(([k, masked]) => (
            <div key={k} className="flex justify-between text-xs">
              <span className="text-muted-foreground">{k}</span>
              <span className="font-mono">{masked}</span>
            </div>
          ))
        )}
      </section>
    </div>
  )
}
