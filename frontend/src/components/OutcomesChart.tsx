'use client'

interface OutcomesChartProps {
  trendsData: any[]
  quarter: string
}

const OUTCOME_CONFIG = [
  { key: 'deaths', label: 'Death', code: 'DE', color: '#000000', icon: '' },
  { key: 'hospitalizations', label: 'Hospitalization', code: 'HO', color: '#0055ff', icon: '' },
  { key: 'life_threatening', label: 'Life-Threatening', code: 'LT', color: '#000000', icon: '' },
  { key: 'female_cases', label: 'Female', code: 'F', color: '#008800', icon: '' },
  { key: 'male_cases', label: 'Male', code: 'M', color: '#0055ff', icon: '' },
]

export default function OutcomesChart({ trendsData, quarter }: OutcomesChartProps) {
  const quarterData = trendsData.find(d => d.quarter === quarter) || trendsData[trendsData.length - 1]

  if (!quarterData) return (
    <div className="empty-state" style={{ padding: '40px 20px' }}>
      <div className="empty-state-title">No outcomes data</div>
    </div>
  )

  const total = quarterData.total_cases || 1

  return (
    <div>
      {/* Summary text */}
      <div style={{
        padding: '12px 16px',
        background: 'rgba(59,130,246,0.06)',
        borderRadius: 8,
        marginBottom: 16,
        fontSize: 13,
        color: 'var(--text-secondary)',
      }}>
        <strong style={{ color: 'var(--text-primary)' }}>
          {(total).toLocaleString()}
        </strong> total cases in {quarter.replace('q', ' Q').toUpperCase()}
      </div>

      {/* Donut chart (CSS) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {OUTCOME_CONFIG.map(outcome => {
          const count = quarterData[outcome.key] || 0
          const pct = total > 0 ? (count / total * 100) : 0

          return (
            <div key={outcome.key}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>{outcome.icon}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {outcome.label}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({outcome.code})</span>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: outcome.color }}>
                    {count.toLocaleString()}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {pct.toFixed(1)}%
                  </span>
                </div>
              </div>
              <div style={{ height: 6, background: 'rgba(255,255,255,0.05)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${Math.min(pct * 2, 100)}%`,   // Scale up for visibility
                  background: outcome.color,
                  borderRadius: 3,
                  transition: 'width 0.8s ease',
                  boxShadow: `0 0 8px ${outcome.color}60`,
                }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Avg age note */}
      {quarterData.avg_age && (
        <div style={{
          marginTop: 16,
          padding: '10px 14px',
          background: 'rgba(16,185,129,0.08)',
          borderRadius: 8,
          fontSize: 12,
          color: 'var(--text-secondary)',
        }}>
          Average patient age: <strong style={{ color: 'var(--accent-emerald)' }}>{quarterData.avg_age}y</strong>
          &nbsp;·&nbsp; Reporting from <strong style={{ color: 'var(--accent-emerald)' }}>{quarterData.reporting_countries}</strong> countries
        </div>
      )}
    </div>
  )
}
