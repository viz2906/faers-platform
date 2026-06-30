'use client'

import { useState, useRef, useCallback } from 'react'

interface NLQueryBoxProps {
  apiBase: string
}



function highlight_sql(sql: string): string {
  return sql
    .replace(/\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|GROUP BY|ORDER BY|HAVING|LIMIT|WITH|AS|ON|AND|OR|NOT|IN|IS|NULL|COUNT|SUM|AVG|MAX|MIN|DISTINCT|CASE|WHEN|THEN|ELSE|END|COALESCE|ROUND|BY|DESC|ASC|NULLS LAST)\b/gi,
      '<span class="sql-keyword">$1</span>')
    .replace(/'([^']*)'/g, '<span class="sql-string">\'$1\'</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="sql-number">$1</span>')
    .replace(/(mv_\w+|faers_\w+)/gi, '<span class="sql-table">$1</span>')
    .replace(/--.*/g, '<span class="sql-comment">$&</span>')
}

function ResponseTimeTag({ ms }: { ms: number }) {
  const cls = ms < 500 ? 'fast' : ms < 2000 ? 'medium' : 'slow'
  return (
    <span className={`response-time ${cls}`}>
      {ms}ms {ms < 500 ? '(cached/view)' : ms < 2000 ? '(live)' : '(complex)'}
    </span>
  )
}

export default function NLQueryBox({ apiBase }: NLQueryBoxProps) {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [showSQL, setShowSQL] = useState(true)   // default open — always audit the generated SQL
  const [sqlCopied, setSqlCopied] = useState(false)
  const [history, setHistory] = useState<any[]>([])
  const [showHistoryPanel, setShowHistoryPanel] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)

  const fetchHistory = async () => {
    if (showHistoryPanel) {
      setShowHistoryPanel(false)
      return
    }
    setLoadingHistory(true)
    setShowHistoryPanel(true)
    try {
      const res = await fetch(`${apiBase}/nlp/history`)
      const data = await res.json()
      setHistory(data.queries || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingHistory(false)
    }
  }

  const copySQL = useCallback((sql: string) => {
    navigator.clipboard.writeText(sql).then(() => {
      setSqlCopied(true)
      setTimeout(() => setSqlCopied(false), 2000)
    })
  }, [])
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = async (q?: string) => {
    const query = q || question
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)
    setShowSQL(true)   // reset to open on each new query
    if (q) setQuestion(q)

    try {
      const res = await fetch(`${apiBase}/nlp/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query }),
      })
      const data = await res.json()

      if (!res.ok) {
        setError(data.detail || 'Query failed')
      } else if (data.error) {
        setError(data.error)
      } else {
        setResult(data)
      }
    } catch (e) {
      setError('Network error — is the API running? Start with: uvicorn api.main:app')
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>

      {/* Query Box */}
      <div className="query-box-container" style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>Ask anything about FDA drug adverse events</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>⌘+Enter to run</span>
        </div>

        <textarea
          ref={textareaRef}
          className="query-input"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your query here..."
          rows={3}
          disabled={loading}
        />

        <div className="query-actions" style={{ justifyContent: 'flex-end' }}>

          <button
            className="btn btn-ghost"
            onClick={fetchHistory}
            disabled={loadingHistory}
            style={{ flexShrink: 0, marginLeft: 'auto', fontSize: 13 }}
          >
            {showHistoryPanel ? 'Close History' : 'View History'}
          </button>

          <button
            className="btn btn-primary"
            onClick={() => submit()}
            disabled={loading || !question.trim()}
            style={{ flexShrink: 0, marginLeft: 12 }}
          >
            {loading ? (
              <>
                <div className="loading-spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                Thinking...
              </>
            ) : (
              <> Run Query </>
            )}
          </button>
        </div>
      </div>



      {/* Error */}
      {error && (
        <div style={{
          padding: '16px 20px',
          background: 'rgba(244,63,94,0.08)',
          border: '1px solid rgba(244,63,94,0.3)',
          borderRadius: 12,
          color: 'var(--color-death)',
          fontSize: 14,
          marginBottom: 20,
        }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* History Panel */}
      {showHistoryPanel && (
        <div className="animate-fade-in-up" style={{ marginBottom: 24, background: 'var(--bg-secondary)', padding: 20, borderRadius: 12, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 16 }}>Recent Queries & SQL Audit Log</div>
          {loadingHistory ? (
             <div className="skeleton" style={{ height: 100 }} />
          ) : history.length === 0 ? (
             <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No history found.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: 400, overflowY: 'auto', paddingRight: 8 }}>
              {history.map((h, i) => (
                <div key={i} style={{ padding: 12, background: 'var(--bg)', borderRadius: 8, border: '1px solid var(--border)' }}>
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Q: {h.question}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                    {h.timestamp ? new Date(h.timestamp).toLocaleString() : ''} · {h.response_time_ms}ms {h.error ? <span style={{color:'var(--color-death)'}}>Failed</span> : `· ${h.rows_returned} rows`}
                  </div>
                  {h.generated_sql && (
                    <div className="sql-block" style={{ margin: 0, padding: '8px 12px', fontSize: 11 }} dangerouslySetInnerHTML={{ __html: highlight_sql(h.generated_sql) }} />
                  )}
                  {h.error && (
                    <div style={{ color: 'var(--color-death)', fontSize: 11, marginTop: 8 }}>Error: {h.error}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="skeleton" style={{ height: 80, borderRadius: 12 }} />
          <div className="skeleton" style={{ height: 40, borderRadius: 8 }} />
          <div className="skeleton" style={{ height: 200, borderRadius: 12 }} />
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="animate-fade-in-up" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Meta bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <ResponseTimeTag ms={result.response_time_ms} />
            <span className={`badge ${result.from_cache ? 'badge-safe' : 'badge-blue'}`}>
              {result.from_cache ? 'Cached' : 'Live'}
            </span>
            <span className="badge badge-blue">
              {result.row_count} rows
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              via {result.query_type}
            </span>
            <button
              className="btn btn-ghost"
              style={{ padding: '4px 12px', fontSize: 12, marginLeft: 'auto', opacity: 0.7 }}
              onClick={() => setShowSQL(!showSQL)}
            >
              {showSQL ? '▲ Hide SQL' : '▼ Show SQL'}
            </button>
          </div>

          {/* SQL Block — always visible by default so analysts can audit AI-generated queries */}
          {showSQL && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  Generated SQL
                </span>
                <span style={{
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: '1px 6px',
                }} title="The exact SQL the AI generated from your question. Verify this matches what you intended.">
                  audit trail
                </span>
                <button
                  onClick={() => copySQL(result.sql)}
                  style={{
                    marginLeft: 'auto',
                    background: 'none',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11,
                    cursor: 'pointer',
                    color: sqlCopied ? 'var(--color-safe)' : 'var(--text-muted)',
                    transition: 'color 0.2s',
                  }}
                >
                  {sqlCopied ? '✓ Copied' : 'Copy SQL'}
                </button>
              </div>
              <div
                className="sql-block"
                dangerouslySetInnerHTML={{ __html: highlight_sql(result.sql) }}
              />
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, fontStyle: 'italic' }}>
                ⚠ If this SQL doesn't match your intent, rephrase your question or report a hallucination.
              </div>
            </div>
          )}

          {/* Warning */}
          {result.warning && (
            <div className="warning-banner">
              <span>{result.warning}</span>
            </div>
          )}

          {/* AI Explanation */}
          {result.explanation && (
            <div className="explanation-box" style={{ marginTop: 8 }}>
              {result.explanation}
            </div>
          )}

          {/* Results Table */}
          {result.columns?.length > 0 && result.data?.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '1px' }}>
                Results · {result.row_count.toLocaleString()} rows
              </div>
              <div className="data-table-wrapper">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 40, textAlign: 'center' }}>#</th>
                      {result.columns.map((col: string) => (
                        <th key={col}>{col.replace(/_/g, ' ')}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.slice(0, 50).map((row: any[], i: number) => (
                      <tr key={i}>
                        <td style={{ color: 'var(--text-muted)', textAlign: 'center', fontSize: 11 }}>{i + 1}</td>
                        {row.map((cell, j) => {
                          const col = result.columns[j]
                          const isNum = typeof cell === 'number' || (typeof cell === 'string' && /^\d+\.?\d*$/.test(cell))
                          const isPRR = col === 'prr' || col === 'ror'
                          const isSignal = col === 'is_signal'
                          const isDeath = col?.includes('death')

                          if (isSignal) return (
                            <td key={j}>
                              <span className={`badge ${cell ? 'badge-signal' : 'badge-safe'}`}>
                                {cell ? 'SIGNAL' : 'OK'}
                              </span>
                            </td>
                          )

                          if (isPRR && typeof cell === 'number') {
                            const isHigh = cell >= 2
                            return (
                              <td key={j}>
                                <div className="prr-bar-container">
                                  <div className="prr-bar-track">
                                    <div
                                      className={`prr-bar-fill ${isHigh ? 'signal' : 'no-signal'}`}
                                      style={{ width: `${Math.min((cell / 10) * 100, 100)}%` }}
                                    />
                                  </div>
                                  <span style={{
                                    fontFamily: 'JetBrains Mono, monospace',
                                    fontSize: 12,
                                    color: isHigh ? 'var(--color-signal)' : 'var(--accent-blue)',
                                    fontWeight: isHigh ? 700 : 400,
                                  }}>
                                    {cell.toFixed(2)}
                                  </span>
                                </div>
                              </td>
                            )
                          }

                          return (
                            <td key={j} className={isNum ? 'num-cell' : ''} style={isDeath && Number(cell) > 0 ? { color: 'var(--color-death)' } : {}}>
                              {cell === null || cell === undefined ? '—' :
                                typeof cell === 'number' ? cell.toLocaleString() :
                                typeof cell === 'boolean' ? (cell ? 'Yes' : 'No') :
                                String(cell)}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.row_count > 50 && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
                  Showing first 50 of {result.row_count.toLocaleString()} rows
                </div>
              )}
            </div>
          )}

          {/* Empty results */}
          {result.data?.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-title">No results found</div>
              <div className="empty-state-desc">
                Try a different drug name, broader search terms, or remove the quarter filter
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
