import { Link, useNavigate } from 'react-router-dom'
import { Zap, MessageSquare, Brain, CheckCircle2, TrendingUp, Shield, Clock, ArrowRight, Building2, Users } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

const DEMO_LANDLORD = {
  name: 'Aleksa Ljujic',
  email: 'aleksa@proprelay.io',
  phone: '381603334933',
  building: 'Riverside Apartments',
  landlord_id: 'demo-landlord-001',
}

const steps = [
  { num: '01', title: 'Tenant reports via WhatsApp', desc: 'No app needed. Tenant texts the issue and sends a photo.' },
  { num: '02', title: 'AI diagnoses & classifies', desc: 'Claude Vision analyzes the photo and assigns urgency, category, and estimated cost.' },
  { num: '03', title: 'Landlord approves in one tap', desc: 'You receive a neat summary — just reply YES or NO.' },
  { num: '04', title: 'Contractor dispatched', desc: 'The right specialist is automatically assigned and both parties are notified.' },
]

const features = [
  { icon: MessageSquare, title: 'WhatsApp-First', desc: 'Tenants report issues over WhatsApp. No app downloads, no portals.' },
  { icon: Brain, title: 'AI Triage', desc: 'Claude Vision diagnoses issues from photos, classifies urgency, and generates repair estimates.' },
  { icon: CheckCircle2, title: 'One-Tap Approval', desc: 'You get a structured summary and approve or reject with a single reply.' },
  { icon: TrendingUp, title: 'Revenue Tracking', desc: 'Track rent, maintenance costs, and returns per property in one place.' },
  { icon: Shield, title: 'Full Audit Trail', desc: 'Every message, photo, and decision is logged. Nothing gets lost.' },
  { icon: Clock, title: 'Auto-Dispatch', desc: 'The right contractor is selected by specialty and dispatched automatically.' },
]

export default function Landing() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleStartFree = (e) => {
    e.preventDefault()
    login(DEMO_LANDLORD)
    navigate('/dashboard')
  }

  return (
    <div className="min-h-screen font-sans" style={{ background: '#0A1625', color: '#EDE8DC' }}>

      {/* Navbar */}
      <nav style={{ background: 'rgba(10,22,37,0.92)', borderBottom: '1px solid #1A2E4A' }}
           className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
                 style={{ background: '#326448' }}>
              <Zap size={14} color="#EDE8DC" strokeWidth={2.5} />
            </div>
            <span className="font-display font-semibold text-lg tracking-wide" style={{ color: '#EDE8DC' }}>
              PropRelay
            </span>
          </div>

          <div className="hidden md:flex items-center gap-8">
            {['Features', 'How it works'].map(item => (
              <a key={item} href={`#${item.toLowerCase().replace(/ /g, '-')}`}
                 className="text-sm transition-colors"
                 style={{ color: '#9A9580' }}
                 onMouseEnter={e => e.target.style.color = '#EDE8DC'}
                 onMouseLeave={e => e.target.style.color = '#9A9580'}>
                {item}
              </a>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <Link to="/auth"
                  className="text-sm px-4 py-2 transition-colors"
                  style={{ color: '#9A9580' }}>
              Sign in
            </Link>
            <a href="/dashboard"
               onClick={handleStartFree}
               className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors cursor-pointer"
               style={{ background: '#326448', color: '#EDE8DC' }}>
              Get started
            </a>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-40 pb-20 px-6" style={{
        background: 'linear-gradient(160deg, #0A1625 0%, #111F35 60%, #0A1625 100%)'
      }}>
        <div className="max-w-3xl mx-auto">
          <p className="text-xs font-medium uppercase tracking-widest mb-5"
             style={{ color: '#4A8060', letterSpacing: '0.2em' }}>
            Property Management Platform
          </p>
          <h1 className="font-display text-5xl md:text-6xl font-semibold leading-[1.1] mb-6"
              style={{ color: '#EDE8DC' }}>
            Property management<br />without the chaos
          </h1>
          <p className="text-lg leading-relaxed mb-10 max-w-xl"
             style={{ color: '#9A9580' }}>
            Tenants report maintenance over WhatsApp. AI triages and diagnoses.
            You approve with one reply. The contractor handles the rest.
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <a href="/dashboard"
               onClick={handleStartFree}
               className="inline-flex items-center gap-2 px-7 py-3.5 rounded-lg font-semibold text-sm transition-all cursor-pointer"
               style={{ background: '#326448', color: '#EDE8DC' }}>
              Start for free <ArrowRight size={16} />
            </a>
            <Link to="/auth"
                  className="inline-flex items-center gap-2 px-7 py-3.5 rounded-lg text-sm font-medium transition-all"
                  style={{ border: '1px solid #1A2E4A', color: '#9A9580' }}>
              Sign in to dashboard
            </Link>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-24 px-6" style={{ background: '#0A1625' }}>
        <div className="max-w-3xl mx-auto">
          <h2 className="font-display text-3xl font-semibold mb-14" style={{ color: '#EDE8DC' }}>
            How it works
          </h2>
          <div className="space-y-12">
            {steps.map(({ num, title, desc }) => (
              <div key={num} className="flex gap-8 items-start">
                <span className="font-display text-5xl font-semibold flex-shrink-0 w-14 leading-none select-none"
                      style={{ color: '#1A2E4A' }}>
                  {num}
                </span>
                <div className="pt-1">
                  <h3 className="text-base font-semibold mb-1.5" style={{ color: '#EDE8DC' }}>{title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: '#7A7565' }}>{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Dashboard preview */}
      <section className="py-12 px-6" style={{ background: '#0A1625' }}>
        <div className="max-w-5xl mx-auto">
          <div className="rounded-2xl overflow-hidden"
               style={{ border: '1px solid #1A2E4A', background: '#111F35' }}>
            <div className="px-5 py-3 flex items-center gap-2"
                 style={{ borderBottom: '1px solid #1A2E4A', background: '#0D1A2D' }}>
              <div className="flex gap-1.5">
                {['#1A2E4A','#1A2E4A','#1A2E4A'].map((c,i) => (
                  <div key={i} className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />
                ))}
              </div>
              <span className="text-xs ml-2" style={{ color: '#5A5850' }}>PropRelay Dashboard</span>
            </div>
            <div className="p-6 grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Monthly Revenue', value: '€24,800', trend: '+8.2%', icon: TrendingUp },
                { label: 'Properties', value: '12', trend: 'Active', icon: Building2 },
                { label: 'Open Tickets', value: '3', trend: '2 resolved', icon: CheckCircle2 },
                { label: 'Tenants', value: '47', trend: '100% occupied', icon: Users },
              ].map(({ label, value, trend, icon: Icon }) => (
                <div key={label} className="rounded-xl p-4"
                     style={{ background: '#1A2E4A', border: '1px solid #243D61' }}>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs" style={{ color: '#5A5850' }}>{label}</span>
                    <Icon size={14} color="#326448" />
                  </div>
                  <p className="text-xl font-semibold" style={{ color: '#EDE8DC' }}>{value}</p>
                  <p className="text-xs mt-1" style={{ color: '#4A8060' }}>{trend}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-24 px-6" style={{ background: '#0D1A2D' }}>
        <div className="max-w-5xl mx-auto">
          <h2 className="font-display text-3xl font-semibold mb-12" style={{ color: '#EDE8DC' }}>
            What it does
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {features.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="rounded-xl p-6 transition-colors duration-200"
                   style={{ background: '#111F35', border: '1px solid #1A2E4A' }}>
                <Icon size={18} color="#4A8060" className="mb-4" />
                <h3 className="text-sm font-semibold mb-2" style={{ color: '#EDE8DC' }}>{title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: '#6A6555' }}>{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6" style={{ background: '#0A1625' }}>
        <div className="max-w-3xl mx-auto">
          <h2 className="font-display text-3xl font-semibold mb-4" style={{ color: '#EDE8DC' }}>
            Ready to get started?
          </h2>
          <p className="mb-8 text-base" style={{ color: '#7A7565' }}>
            Set up your account in minutes. Add your building, invite tenants, and let the platform handle the rest.
          </p>
          <a href="/dashboard"
             onClick={handleStartFree}
             className="inline-flex items-center gap-2 px-7 py-3.5 rounded-lg font-semibold text-sm transition-colors cursor-pointer"
             style={{ background: '#326448', color: '#EDE8DC' }}>
            Create your account <ArrowRight size={16} />
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-10 px-6" style={{ borderTop: '1px solid #1A2E4A' }}>
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md flex items-center justify-center"
                 style={{ background: '#326448' }}>
              <Zap size={12} color="#EDE8DC" strokeWidth={2.5} />
            </div>
            <span className="font-display text-sm" style={{ color: '#5A5850' }}>PropRelay</span>
          </div>
          <p className="text-xs" style={{ color: '#3A3830' }}>© {new Date().getFullYear()} PropRelay</p>
          <div className="flex gap-6">
            {['Privacy', 'Terms', 'Contact'].map(l => (
              <a key={l} href="#" className="text-xs transition-colors" style={{ color: '#4A4840' }}>
                {l}
              </a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  )
}
