'use client'

import { useState, useEffect, useCallback } from 'react'
import Sidebar from '@/components/Sidebar'
import StatCard from '@/components/StatCard'
import TopDrugsTable from '@/components/TopDrugsTable'
import OutcomesChart from '@/components/OutcomesChart'
import CountryMap from '@/components/CountryMap'
import QuarterlyTrends from '@/components/QuarterlyTrends'
import NLQueryBox from '@/components/NLQueryBox'
import DataLoader from '@/components/DataLoader'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1'

export default function DashboardPage() {
  const [summary, setSummary] = useState<any>(null)
  const [topDrugs, setTopDrugs] = useState<any[]>([])
  const [deaths, setDeaths] = useState<any[]>([])
  const [countries, setCountries] = useState<any[]>([])
  const [trends, setTrends] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedQuarter, setSelectedQuarter] = useState('2025q4')
  const [activePage, setActivePage] = useState('dashboard')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [summaryRes, drugsRes, deathsRes, countriesRes, trendsRes] = await Promise.all([
        fetch(`${API_BASE}/analytics/summary`),
        fetch(`${API_BASE}/analytics/top-drugs?quarter=${selectedQuarter}&limit=15`),
        fetch(`${API_BASE}/analytics/deaths/top-drugs?quarter=${selectedQuarter}&limit=10`),
        fetch(`${API_BASE}/analytics/countries?quarter=${selectedQuarter}&limit=30`),
        fetch(`${API_BASE}/analytics/trends`),
      ])
      const [s, d, de, c, t] = await Promise.all([
        summaryRes.json(), drugsRes.json(), deathsRes.json(),
        countriesRes.json(), trendsRes.json()
      ])
      setSummary(s)
      setTopDrugs(d.data || [])
      setDeaths(de.data || [])
      setCountries(c.data || [])
      setTrends(t.data || [])
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e)
    } finally {
      setLoading(false)
    }
  }, [selectedQuarter])

  useEffect(() => { fetchAll() }, [fetchAll])

  const formatNumber = (n: number) => {
    if (!n) return '—'
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return n.toLocaleString()
  }

  return (
    <div className="app-layout">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      <div className="main-content">

        {/* ── Header ── */}
        <div className="page-header">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}>
                {activePage === 'query' ? 'Natural Language Query' : 'FAERS Analytics Dashboard'}
              </h1>
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                FDA Adverse Event Monitoring System · Quarterly Data Extract
              </p>
            </div>
            {activePage === 'dashboard' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Quarter:</label>
                <select
                  className="select-input"
                  value={selectedQuarter}
                  onChange={e => setSelectedQuarter(e.target.value)}
                  style={{ width: 140 }}
                >
                  {['2026q1','2025q4','2025q3','2025q2','2025q1',
                    '2024q4','2024q3','2024q2','2024q1'].map(q => (
                    <option key={q} value={q}>{q.replace('q', ' Q').toUpperCase()}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        <div className="page-content">

          {activePage === 'query' ? (
            // ── NLP Query Page ──
            <NLQueryBox apiBase={API_BASE} />
          ) : (
            // ── Dashboard Page ──
            <>
              <DataLoader apiBase={API_BASE} />

              {/* Stat Cards */}
              {loading ? (
                <div className="grid-4 stagger-children" style={{ marginBottom: 24 }}>
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: 100 }} />
                  ))}
                </div>
              ) : summary && (
                <div className="grid-4 stagger-children animate-fade-in" style={{ marginBottom: 24 }}>
                  <StatCard
                    icon=""
                    label="Total Cases Loaded"
                    value={formatNumber(summary.total_cases)}
                    sub={summary.loaded_quarters || ''}
                    color="blue"
                  />
                  <StatCard
                    icon=""
                    label="Unique Drugs"
                    value={formatNumber(summary.unique_drugs)}
                    sub="Brand + generic names"
                    color="violet"
                  />
                  <StatCard
                    icon=""
                    label="Unique Reactions"
                    value={formatNumber(summary.unique_reactions)}
                    sub="MedDRA preferred terms"
                    color="cyan"
                  />
                  <StatCard
                    icon=""
                    label="Countries Reporting"
                    value={summary.total_countries}
                    sub="Worldwide surveillance"
                    color="emerald"
                  />
                </div>
              )}

              {/* Warning Banner */}
              <div className="warning-banner animate-fade-in" style={{ marginBottom: 24 }}>
                <span>
                  <strong>Data Interpretation Notice:</strong> FAERS data represents voluntary adverse event
                  reports, not clinical trial data. High report counts indicate surveillance attention, not
                  proven drug causation. Reports may be duplicate or incomplete.
                </span>
              </div>

              {/* Main Grid — Top Drugs + Deaths */}
              <div className="grid-2 animate-fade-in" style={{ marginBottom: 24, animationDelay: '100ms' }}>
                <div className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">Top Drugs by Reports</div>
                      <div className="card-subtitle">Primary Suspect only · {selectedQuarter.toUpperCase()}</div>
                    </div>
                  </div>
                  {loading ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {[...Array(8)].map((_, i) => <div key={i} className="skeleton" style={{ height: 36 }} />)}
                    </div>
                  ) : (
                    <TopDrugsTable data={topDrugs} />
                  )}
                </div>

                <div className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">Death-Associated Reports</div>
                      <div className="card-subtitle">Not proven causation · {selectedQuarter.toUpperCase()}</div>
                    </div>
                    <span className="badge badge-death">Critical</span>
                  </div>
                  {loading ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {[...Array(8)].map((_, i) => <div key={i} className="skeleton" style={{ height: 36 }} />)}
                    </div>
                  ) : (
                    <TopDrugsTable data={deaths.map(d => ({ ...d, drug: d.drug, total_reports: d.death_reports }))} isDeaths />
                  )}
                </div>
              </div>

              {/* Quarterly Trends */}
              <div className="card animate-fade-in" style={{ marginBottom: 24, animationDelay: '150ms' }}>
                <div className="card-header">
                  <div>
                    <div className="card-title">Quarterly Reporting Trends</div>
                    <div className="card-subtitle">Total cases, deaths, hospitalizations over time</div>
                  </div>
                </div>
                {loading ? (
                  <div className="skeleton" style={{ height: 220 }} />
                ) : (
                  <QuarterlyTrends data={trends} />
                )}
              </div>

              {/* Country Map + Outcomes */}
              <div className="grid-2 animate-fade-in" style={{ animationDelay: '200ms' }}>
                <div className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">Reports by Country</div>
                      <div className="card-subtitle">Top 15 reporting countries</div>
                    </div>
                  </div>
                  {loading ? (
                    <div className="skeleton" style={{ height: 280 }} />
                  ) : (
                    <CountryMap data={countries.slice(0, 15)} />
                  )}
                </div>

                <div className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">Outcome Distribution</div>
                      <div className="card-subtitle">Severity breakdown · {selectedQuarter.toUpperCase()}</div>
                    </div>
                  </div>
                  {loading ? (
                    <div className="skeleton" style={{ height: 280 }} />
                  ) : (
                    <OutcomesChart trendsData={trends} quarter={selectedQuarter} />
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
