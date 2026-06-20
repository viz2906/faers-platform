'use client'

interface QuarterlyTrendsProps {
  data: any[]
}

export default function QuarterlyTrends({ data }: QuarterlyTrendsProps) {
  if (!data.length) return (
    <div className="empty-state" style={{ padding: '40px 20px' }}>
      <div className="empty-state-title">No trend data available</div>
      <div className="empty-state-desc">Load multiple quarters to see trends</div>
    </div>
  )

  const maxCases = Math.max(...data.map(d => d.total_cases || 0))

  const SERIES = [
    { key: 'total_cases', label: 'Total Cases', color: '#3b82f6' },
    { key: 'deaths', label: 'Deaths', color: '#f43f5e' },
    { key: 'hospitalizations', label: 'Hospitalizations', color: '#f59e0b' },
    { key: 'life_threatening', label: 'Life-Threatening', color: '#a855f7' },
  ]

  const chartHeight = 200
  const chartWidth = 100  // percentage-based

  return (
    <div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 16, flexWrap: 'wrap' }}>
        {SERIES.map(s => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
            <div style={{ width: 12, height: 3, borderRadius: 2, background: s.color }} />
            {s.label}
          </div>
        ))}
      </div>

      {/* Chart — SVG line chart */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          width="100%"
          height={chartHeight + 40}
          viewBox={`0 0 ${Math.max(data.length * 80, 600)} ${chartHeight + 40}`}
          preserveAspectRatio="xMidYMid meet"
          style={{ display: 'block' }}
        >
          {/* Grid lines */}
          {[0.25, 0.5, 0.75, 1].map(frac => (
            <line
              key={frac}
              x1={0} y1={chartHeight - frac * chartHeight}
              x2={data.length * 80} y2={chartHeight - frac * chartHeight}
              stroke="rgba(59,130,246,0.1)" strokeWidth={1}
            />
          ))}

          {/* Lines per series */}
          {SERIES.map(series => {
            const points = data.map((d, i) => {
              const x = i * 80 + 40
              const y = chartHeight - ((d[series.key] || 0) / maxCases) * (chartHeight - 20)
              return `${x},${y}`
            }).join(' ')

            return (
              <g key={series.key}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={series.color}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity={0.9}
                />
                {data.map((d, i) => {
                  const x = i * 80 + 40
                  const y = chartHeight - ((d[series.key] || 0) / maxCases) * (chartHeight - 20)
                  return (
                    <circle
                      key={i}
                      cx={x} cy={y} r={3}
                      fill={series.color}
                      stroke="var(--bg-primary)"
                      strokeWidth={2}
                    >
                      <title>{series.label}: {(d[series.key] || 0).toLocaleString()}</title>
                    </circle>
                  )
                })}
              </g>
            )
          })}

          {/* X-axis labels */}
          {data.map((d, i) => (
            <text
              key={i}
              x={i * 80 + 40}
              y={chartHeight + 20}
              textAnchor="middle"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {d.quarter?.replace('q', ' Q').toUpperCase()}
            </text>
          ))}
        </svg>
      </div>

      {/* Summary table below chart */}
      {data.length > 0 && (
        <div style={{ marginTop: 16, overflowX: 'auto' }}>
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th>Quarter</th>
                <th style={{ textAlign: 'right' }}>Cases</th>
                <th style={{ textAlign: 'right' }}>Deaths</th>
                <th style={{ textAlign: 'right' }}>Hosp.</th>
                <th style={{ textAlign: 'right' }}>Avg Age</th>
                <th style={{ textAlign: 'right' }}>Countries</th>
              </tr>
            </thead>
            <tbody>
              {data.slice(-6).map((d, i) => (
                <tr key={i}>
                  <td><span className="badge badge-blue">{d.quarter?.toUpperCase()}</span></td>
                  <td className="num-cell">{(d.total_cases || 0).toLocaleString()}</td>
                  <td className="num-cell" style={{ color: 'var(--color-death)' }}>{(d.deaths || 0).toLocaleString()}</td>
                  <td className="num-cell" style={{ color: 'var(--accent-amber)' }}>{(d.hospitalizations || 0).toLocaleString()}</td>
                  <td className="num-cell">{d.avg_age ? `${d.avg_age}y` : '—'}</td>
                  <td className="num-cell">{d.reporting_countries || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
