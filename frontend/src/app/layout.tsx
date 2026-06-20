import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'FAERS Analytics | FDA Adverse Event Intelligence Platform',
  description: 'Query the FDA Adverse Event Reporting System with natural language. Pharmacovigilance analytics, safety signal detection (PRR/ROR), and drug adverse event insights.',
  keywords: ['FDA', 'FAERS', 'pharmacovigilance', 'adverse events', 'drug safety', 'PRR', 'signal detection'],
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  )
}
