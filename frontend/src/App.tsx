import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

import DatasourcesPage from '@/pages/Datasources'
import AuditPage from '@/pages/Audit'
import Settings from '@/pages/Settings'
import Workspace from '@/pages/Workspace'
import { settingsApi } from '@/api/client'
import { useCanvasStore } from '@/stores/canvasStore'
import { useChatStore } from '@/stores/chatStore'

type Tab = 'workspace' | 'datasources' | 'audit' | 'settings'

const TABS: { id: Tab; label: string }[] = [
  { id: 'workspace', label: '工作台' },
  { id: 'datasources', label: '数据源' },
  { id: 'audit', label: '审计' },
  { id: 'settings', label: '设置' },
]

type Theme = 'dark' | 'light'

function App() {
  const [tab, setTab] = useState<Tab>('workspace')
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('data-agent-theme')
    return saved === 'light' ? 'light' : 'dark'
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('data-agent-theme', theme)
  }, [theme])
  const aiEnabled = useChatStore((s) => s.aiEnabled)
  const setAiToggle = useChatStore((s) => s.setAiToggle)
  const loadAiToggle = useChatStore((s) => s.loadAiToggle)
  const [modelDot, setModelDot] = useState('')

  useEffect(() => {
    void loadAiToggle()
    void settingsApi.get().then((v) => {
      setModelDot(String(v.settings.llm_model || v.settings.llm_provider || 'test'))
    }).catch(() => setModelDot('?'))
  }, [loadAiToggle])

  // light canvas poll so auto-rescan stale badges appear without manual refresh
  useEffect(() => {
    const t = setInterval(() => { void useCanvasStore.getState().loadAll() }, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-1 border-b px-4">
        <span className="mr-4 text-sm font-semibold">data-agent</span>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={
              'px-3 py-2 text-sm transition-colors ' +
              (tab === t.id
                ? 'border-primary text-foreground border-b-2 font-medium'
                : 'text-muted-foreground hover:text-foreground')
            }
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="主题：黑色 / 白色"
            className="text-muted-foreground rounded p-1.5 transition-colors hover:bg-accent hover:text-foreground"
          >
            {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <button
            onClick={() => void setAiToggle(!aiEnabled).catch(() => undefined)}
            title="AI toggle：关闭后 AI 对话入口下线，画布/表单/重放照常"
            className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors ${
              aiEnabled ? 'bg-primary/15 text-primary' : 'bg-secondary text-muted-foreground'}`}
          >
            <span className={`inline-block size-1.5 rounded-full ${aiEnabled ? 'bg-primary' : 'bg-muted-foreground/50'}`} />
            AI {aiEnabled ? 'ON' : 'OFF'}
          </button>
          <span className="text-muted-foreground font-mono text-[10px]" title={`当前模型 ${modelDot}`}>
            {modelDot}
          </span>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        {tab === 'workspace' && <Workspace />}
        {tab === 'datasources' && <DatasourcesPage />}
        {tab === 'audit' && <AuditPage />}
        {tab === 'settings' && <Settings />}
      </div>
    </div>
  )
}

export default App
