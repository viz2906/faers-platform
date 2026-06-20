'use client'

interface StatCardProps {
  icon: string
  label: string
  value: string | number
  sub?: string
  color?: 'blue' | 'violet' | 'cyan' | 'emerald' | 'rose'
}

const gradients = {
  blue:    'linear-gradient(135deg, #3b82f6 0%, #6366f1 100%)',
  violet:  'linear-gradient(135deg, #7c3aed 0%, #a855f7 100%)',
  cyan:    'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
  emerald: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
  rose:    'linear-gradient(135deg, #f43f5e 0%, #f97316 100%)',
}

export default function StatCard({ icon, label, value, sub, color = 'blue' }: StatCardProps) {
  const gradient = gradients[color]

  return (
    <div className="stat-card animate-fade-in-up" style={{ ['--accent-gradient' as any]: gradient }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: gradient, borderRadius: '16px 16px 0 0' }} />
      <div className="stat-icon">{icon}</div>
      <div className="stat-value" style={{ background: gradient, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
        {value}
      </div>
      <div className="stat-label">{label}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}
