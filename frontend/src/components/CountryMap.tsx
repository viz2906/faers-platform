'use client'

interface CountryMapProps {
  data: any[]
}

export default function CountryMap({ data }: CountryMapProps) {
  if (!data.length) return (
    <div className="empty-state" style={{ padding: '40px 20px' }}>
      <div className="empty-state-title">No country data</div>
    </div>
  )

  const maxCount = Math.max(...data.map(d => d.report_count || 0))

  const FLAG_MAP: Record<string, string> = {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 300, overflowY: 'auto' }}>
      {data.map((row, i) => {
        const pct = maxCount > 0 ? (row.report_count / maxCount) * 100 : 0
        const flag = ''
        const deathPct = row.report_count > 0 ? ((row.death_count || 0) / row.report_count * 100).toFixed(1) : '0'

        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '6px 8px', borderRadius: 8, transition: 'background 0.15s',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(59,130,246,0.06)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <span style={{ fontSize: 16, flexShrink: 0 }}>{flag}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {row.country}
                </span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--color-death)' }}>Deaths: {deathPct}%</span>
                  <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: 'var(--accent-cyan)' }}>
                    {(row.report_count || 0).toLocaleString()}
                  </span>
                </div>
              </div>
              <div style={{ height: 4, background: 'rgba(59,130,246,0.1)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', width: `${pct}%`, borderRadius: 2,
                  background: i === 0
                    ? 'linear-gradient(90deg, #3b82f6, #7c3aed)'
                    : 'linear-gradient(90deg, #06b6d4, #3b82f6)',
                  transition: 'width 0.6s ease',
                }} />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
