/** Settings page: N2 shows the merged masked view (runtime settings + secret
 * names) read-only; model area + AI toggle editor land in N3 (model_factory). */

import { useEffect, useState } from 'react'

import { settingsApi, type SettingsView } from '@/api/client'

export default function Settings() {
  const [view, setView] = useState<SettingsView | null>(null)
  useEffect(() => {
    void settingsApi.get().then(setView).catch(() => setView(null))
  }, [])
  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-6">
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">模型（N3 启用）</h2>
        <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-xs">
          provider 预设下拉 / base_url / 模型名 / API key 掩码回显 / [测试连接] ——
          随 ai-coding-loop 交付（model_factory 每次 Run 现造实例，保存热生效）。
        </p>
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">运行配置</h2>
        {view && (
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
              {Object.entries(view.settings).map(([k, v]) => (
                <tr key={k} className="border-b border-border/60">
                  <td className="text-muted-foreground py-1 pr-4">{k}</td>
                  <td className="font-mono">{JSON.stringify(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">敏感项（仅显示名称与掩码）</h2>
        {view && Object.keys(view.secrets).length === 0 && (
          <p className="text-muted-foreground text-xs">尚无密钥/连接串</p>
        )}
        {view && Object.entries(view.secrets).map(([k, masked]) => (
          <div key={k} className="flex justify-between text-xs">
            <span className="text-muted-foreground">{k}</span>
            <span className="font-mono">{masked}</span>
          </div>
        ))}
      </section>
    </div>
  )
}
