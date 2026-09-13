import { useState } from 'react'

import DatasourcesPage from '@/pages/Datasources'
import WorkspaceDemo from '@/pages/WorkspaceDemo'

type Tab = 'workspace' | 'datasources'

const TABS: { id: Tab; label: string }[] = [
  { id: 'workspace', label: '工作台' },
  { id: 'datasources', label: '数据源' },
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
      </header>
      <div className="min-h-0 flex-1">{tab === 'workspace' ? <WorkspaceDemo /> : <DatasourcesPage />}</div>
    </div>
  )
}

export default App
