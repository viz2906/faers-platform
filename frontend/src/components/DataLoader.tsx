'use client';
import { useState, useEffect, useRef } from 'react';

interface DataLoaderProps {
  apiBase: string;
}

const STAGE_STEPS = [
  { key: 'Initializing', label: 'Initialize', pct: 2 },
  { key: 'Downloading', label: 'Download',   pct: 20 },
  { key: 'Parsing',     label: 'Parse',      pct: 40 },
  { key: 'Loading',     label: 'Load to DB', pct: 80 },
  { key: 'Views',       label: 'Build Views', pct: 95 },
];

function StepIndicator({ stage, status }: { stage: string | null, status: string }) {
  return (
    <div style={{ display: 'flex', gap: 0, alignItems: 'center', marginBottom: 12 }}>
      {STAGE_STEPS.map((step, i) => {
        const stepIdx = STAGE_STEPS.findIndex(s => s.key === stage);
        const done = status === 'completed' || (stepIdx > i);
        const active = stepIdx === i && status === 'running';
        const error = (status === 'error' || status === 'stopped') && stepIdx === i;

        const color = error ? 'var(--color-death)' : done ? 'var(--accent-green)' : active ? 'var(--accent-blue)' : 'var(--border-color)';
        const textColor = error ? 'var(--color-death)' : done ? 'var(--accent-green)' : active ? 'var(--accent-blue)' : 'var(--text-secondary)';

        return (
          <div key={step.key} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, flex: 1 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                border: `2px solid ${color}`,
                backgroundColor: done || active ? color : 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700,
                color: done || active ? '#fff' : color,
                transition: 'all 0.3s',
                position: 'relative',
              }}>
                {active && !error && (
                  <div style={{
                    position: 'absolute', width: 36, height: 36, borderRadius: '50%',
                    border: '2px solid var(--accent-blue)', opacity: 0.4,
                    animation: 'pulse-ring 1.5s ease-out infinite',
                  }} />
                )}
                {done ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 10, color: textColor, fontWeight: active ? 600 : 400, whiteSpace: 'nowrap' }}>
                {step.label}
              </span>
            </div>
            {i < STAGE_STEPS.length - 1 && (
              <div style={{
                height: 2, flex: 1, marginBottom: 18,
                backgroundColor: done ? 'var(--accent-green)' : 'var(--border-color)',
                transition: 'background-color 0.3s',
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function DataLoader({ apiBase }: DataLoaderProps) {
  const [quarter, setQuarter] = useState('2025q4');
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${apiBase}/ingestion/status`);
      const data = await res.json();
      setStatus(data);
      setLoading(data.status === 'running');
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, [apiBase]);

  // Auto-scroll log to bottom
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [status?.log]);

  const handleLoad = async () => {
    try {
      setLoading(true);
      await fetch(`${apiBase}/ingestion/load/${quarter}`, { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error('Failed to start load', e);
      setLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${apiBase}/ingestion/stop`, { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error('Failed to stop load', e);
    }
  };

  const progress = status?.status === 'completed' ? 100 : (status?.progress || 0);
  const hasActivity = status && status.status !== 'idle';
  const statusColor =
    status?.status === 'error' || status?.status === 'stopped' ? 'var(--color-death)' :
    status?.status === 'completed' ? 'var(--accent-green)' :
    'var(--accent-blue)';

  const formatElapsed = () => {
    if (!status?.start_time) return '';
    const end = status.end_time || (Date.now() / 1000);
    const secs = Math.round(end - status.start_time);
    if (secs < 60) return `${secs}s`;
    return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Control Card */}
      <div className="card" style={{ border: '2px solid var(--accent-blue)' }}>
        <div className="card-header" style={{ marginBottom: 16 }}>
          <div>
            <div className="card-title">Data Management</div>
            <div className="card-subtitle">Download and ingest FAERS quarterly data into PostgreSQL</div>
          </div>
          {hasActivity && status.status !== 'running' && (
            <div style={{ fontSize: 12, color: statusColor, fontWeight: 600, textAlign: 'right' }}>
              {status.status.toUpperCase()}<br />
              <span style={{ fontWeight: 400, color: 'var(--text-secondary)' }}>{formatElapsed()}</span>
            </div>
          )}
        </div>

        {/* Controls Row */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: hasActivity ? 20 : 0 }}>
          <select
            className="select-input"
            value={quarter}
            onChange={e => setQuarter(e.target.value)}
            disabled={loading}
            style={{ width: 140 }}
          >
            {['2026q1','2025q4','2025q3','2025q2','2025q1','2024q4','2024q3','2024q2','2024q1'].map(q => (
              <option key={q} value={q}>{q.replace('q', ' Q').toUpperCase()}</option>
            ))}
          </select>

          <button className="btn btn-primary" onClick={handleLoad} disabled={loading}>
            {loading ? 'Processing...' : 'Load Data'}
          </button>

          {status?.status === 'running' && (
            <button
              className="btn btn-ghost"
              style={{ color: 'var(--color-death)', borderColor: 'var(--color-death)' }}
              onClick={handleStop}
            >
              Stop
            </button>
          )}

          {hasActivity && (
            <div style={{ marginLeft: 'auto', fontSize: 12, color: statusColor, fontWeight: 600 }}>
              {status.status === 'running'
                ? `${status.stage || 'Running'}... ${progress}%`
                : status.status.toUpperCase()}
              {status.quarter && ` · ${status.quarter.toUpperCase()}`}
            </div>
          )}
        </div>

        {/* Step Indicator + Progress Bar */}
        {hasActivity && (
          <>
            <StepIndicator stage={status.stage} status={status.status} />
            <div style={{ width: '100%', height: 6, backgroundColor: 'var(--bg-card-hover)', borderRadius: 3, overflow: 'hidden', marginBottom: 8 }}>
              <div style={{
                width: `${progress}%`, height: '100%',
                backgroundColor: statusColor,
                transition: 'width 0.6s ease-in-out, background-color 0.3s',
                backgroundImage: status.status === 'running'
                  ? 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.2) 50%, transparent 100%)'
                  : 'none',
                backgroundSize: '200% 100%',
                animation: status.status === 'running' ? 'shimmer 1.5s infinite' : 'none',
              }} />
            </div>
            {status.status === 'running' && status.detail && (
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>
                {status.detail}
              </div>
            )}
            {(status.status === 'error' || status.status === 'stopped') && status.error && (
              <div style={{ fontSize: 11, color: 'var(--color-death)', marginTop: 4 }}>
                {status.error}
              </div>
            )}
          </>
        )}
      </div>

      {/* Live Log Panel */}
      {hasActivity && status.log && status.log.length > 0 && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              Pipeline Log
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {status.status === 'running' && (
                <span style={{
                  display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
                  backgroundColor: 'var(--accent-green)',
                  boxShadow: '0 0 0 2px rgba(34,197,94,0.3)',
                  animation: 'pulse-dot 1s ease-in-out infinite',
                }} />
              )}
              <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {status.log.length} events · elapsed {formatElapsed()}
              </span>
            </div>
          </div>
          <div
            ref={logRef}
            style={{
              height: 220,
              overflowY: 'auto',
              backgroundColor: '#0f172a',
              borderRadius: 6,
              padding: '10px 14px',
              fontFamily: "'SF Mono', 'JetBrains Mono', 'Fira Code', monospace",
              fontSize: 11.5,
              lineHeight: 1.7,
              color: '#94a3b8',
            }}
          >
            {status.log.map((line: string, i: number) => {
              const isError = line.includes('ERROR') || line.includes('FAILED');
              const isSuccess = line.includes('complete') || line.includes('rows loaded') || line.includes('TOTAL');
              const isStage = line.includes('] [') || line.match(/\] \[.+\]/);
              return (
                <div key={i} style={{
                  color: isError ? '#f87171' : isSuccess ? '#4ade80' : isStage ? '#60a5fa' : '#94a3b8',
                  paddingBottom: 1,
                }}>
                  {line}
                </div>
              );
            })}
            {status.status === 'running' && (
              <div style={{ color: 'var(--accent-blue)', opacity: 0.7 }}>
                <span style={{ animation: 'blink 1s step-end infinite' }}>_</span>
              </div>
            )}
          </div>

          {/* Stats Summary (shown after completion) */}
          {status.status === 'completed' && status.stats && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
                Load Summary
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {Object.entries(status.stats as Record<string, number>).map(([table, rows]) => (
                  <div key={table} style={{
                    backgroundColor: 'var(--bg-card-hover)',
                    borderRadius: 6, padding: '6px 12px',
                    fontSize: 11,
                  }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{table.replace('faers_', '')}</span>
                    <span style={{ color: 'var(--accent-blue)', fontWeight: 700, marginLeft: 8 }}>
                      {(rows as number).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes pulse-ring {
          0% { transform: scale(1); opacity: 0.6; }
          100% { transform: scale(1.8); opacity: 0; }
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes blink {
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  );
}
