import { useState } from 'react'

import DatasourcesPage from '@/pages/Datasources'
import Settings from '@/pages/Settings'
import Workspace from '@/pages/Workspace'

type Tab = 'workspace' | 'datasources' | 'settings'

const TABS: { id: Tab; label: string }[] = [
  { id: 'workspace', label: '工作台' },
  { id: 'datasources', label: '数据源' },
  { id: 'settings', label: '设置' },
]

function App() {
  const [tab, setTab] = useState<Tab>('workspace')
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
        <span className="bg-primary ml-auto inline-block size-2 rounded-full" title="服务在线" />
      </header>
      <div className="min-h-0 flex-1">
        {tab === 'workspace' && <Workspace />}
        {tab === 'datasources' && <DatasourcesPage />}
        {tab === 'settings' && <Settings />}
      </div>
    </div>
  )
}

export default App
