'use client'

interface TopDrugsTableProps {
  data: any[]
  isDeaths?: boolean
}

export default function TopDrugsTable({ data, isDeaths = false }: TopDrugsTableProps) {
  if (!data.length) return (
    <div className="empty-state">
      <div className="empty-state-icon"></div>
      <div className="empty-state-title">No data loaded</div>
      <div className="empty-state-desc">Run the ingestion pipeline to load FAERS data</div>
    </div>
  )

  const maxCount = Math.max(...data.map(d => d.total_reports || d.death_reports || 0))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {data.map((row, i) => {
        const count = row.total_reports || row.death_reports || 0
        const pct = maxCount > 0 ? (count / maxCount) * 100 : 0

        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '8px 10px',
              borderRadius: 8,
              transition: 'background 0.15s',
              cursor: 'pointer',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(59,130,246,0.06)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <span style={{
              width: 20, height: 20, borderRadius: 6,
              background: isDeaths ? 'rgba(244,63,94,0.15)' : 'rgba(59,130,246,0.15)',
              color: isDeaths ? 'var(--color-death)' : 'var(--accent-blue)',
              fontSize: 10, fontWeight: 700, display: 'flex', alignItems: 'center',
              justifyContent: 'center', flexShrink: 0,
            }}>
              {i + 1}
            </span>

            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13, fontWeight: 600,
                color: 'var(--text-primary)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {(row.drug || '').replace(/^\s+|\s+$/g, '') || '—'}
              </div>
              {row.active_ingredient && row.active_ingredient !== row.drug && (
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1 }}>
                  {row.active_ingredient}
                </div>
              )}
              {/* Progress bar */}
              <div style={{ marginTop: 4, height: 3, background: 'rgba(59,130,246,0.1)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${pct}%`,
                  borderRadius: 2,
                  background: isDeaths
                    ? 'linear-gradient(90deg, #f43f5e, #f97316)'
                    : 'linear-gradient(90deg, #3b82f6, #7c3aed)',
                  transition: 'width 0.6s ease',
                }} />
              </div>
            </div>

            <span style={{
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: 13,
              fontWeight: 600,
              color: isDeaths ? 'var(--color-death)' : 'var(--accent-cyan)',
              flexShrink: 0,
            }}>
              {count.toLocaleString()}
            </span>
          </div>
        )
      })}
    </div>
  )
}
