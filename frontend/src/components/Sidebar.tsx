'use client'

interface SidebarProps {
  activePage: string
  onNavigate: (page: string) => void
}

const navItems = [
  { id: 'dashboard', icon: '', label: 'Dashboard' },
  { id: 'query', icon: '', label: 'NL Query Engine' },
  { id: 'signals', icon: '', label: 'Signal Detection' },
  { id: 'drugs', icon: '', label: 'Drug Explorer' },
]

const dataItems = [
  { id: 'demographics', icon: '', label: 'Demographics' },
  { id: 'countries', icon: '', label: 'Geographic' },
  { id: 'trends', icon: '', label: 'Trends' },
]

export default function Sidebar({ activePage, onNavigate }: SidebarProps) {
  return (
    <nav className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-title">FAERS Analytics</div>
        <div className="logo-sub">FDA Pharmacovigilance</div>
      </div>

      <div className="sidebar-nav">
        <div className="nav-section-title">Analytics</div>
        {navItems.map(item => (
          <button
            key={item.id}
            className={`nav-item ${activePage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}

        <div className="nav-section-title">Explore</div>
        {dataItems.map(item => (
          <button
            key={item.id}
            className={`nav-item ${activePage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <div style={{
        padding: '16px 20px',
        borderTop: '1px solid var(--border)',
        fontSize: 11,
        color: 'var(--text-muted)',
        lineHeight: 1.6,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-secondary)' }}>Data Source</div>
        <div>FDA FAERS Public Data</div>
        <div>Latest: 2026 Q1</div>
        <div style={{ marginTop: 8 }}>
          <a
            href="https://fis.fda.gov/extensions/FPD-QDE-FAERS/FPD-QDE-FAERS.html"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--accent-blue)', textDecoration: 'none' }}
          >
            ↗ FDA Source
          </a>
        </div>
      </div>
    </nav>
  )
}
