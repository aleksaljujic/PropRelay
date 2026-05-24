import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Zap, Eye, EyeOff, ArrowRight, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function Auth() {
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState(searchParams.get('tab') === 'register' ? 'register' : 'login')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) navigate('/dashboard')
  }, [isAuthenticated, navigate])

  const [loginForm, setLoginForm] = useState({ email: '', password: '' })
  const [regForm, setRegForm] = useState({
    name: '', email: '', phone: '', building_name: '',
    building_address: '', city: '', whatsapp_number: '', password: '',
  })

  const handleLogin = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    await new Promise(r => setTimeout(r, 800))
    if (loginForm.email && loginForm.password) {
      login({
        name: loginForm.email.split('@')[0].replace(/[._]/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        email: loginForm.email,
        phone: '',
        building: 'My Portfolio',
      })
      navigate('/dashboard')
    } else {
      setError('Please enter your email and password.')
    }
    setLoading(false)
  }

  const handleRegister = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/v1/admin/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: regForm.name,
          email: regForm.email,
          phone: regForm.phone,
          building_name: regForm.building_name,
          building_address: regForm.building_address,
          city: regForm.city,
          whatsapp_number: regForm.whatsapp_number || regForm.phone,
          language: 'en',
        }),
      })
      if (res.ok) {
        const data = await res.json()
        login({
          name: regForm.name,
          email: regForm.email,
          phone: regForm.phone,
          building: regForm.building_name,
          landlord_id: data.landlord_id,
        })
        navigate('/dashboard')
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || 'Registration failed. Please try again.')
      }
    } catch {
      // Dev mode — no backend, still log in
      await new Promise(r => setTimeout(r, 600))
      login({
        name: regForm.name,
        email: regForm.email,
        phone: regForm.phone,
        building: regForm.building_name,
      })
      navigate('/dashboard')
    }
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-base flex">
      {/* Left panel */}
      <div className="hidden lg:flex flex-col flex-1 relative overflow-hidden">
        <div className="absolute inset-0 hero-gradient" />
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px]
                          rounded-full bg-gold-400/8 blur-[100px]" />
        </div>
        <div className="relative flex-1 flex flex-col justify-center px-16">
          <Link to="/" className="flex items-center gap-2.5 mb-16">
            <div className="w-9 h-9 rounded-xl bg-gold-gradient flex items-center justify-center">
              <Zap size={18} className="text-[#08080F]" strokeWidth={2.5} />
            </div>
            <span className="font-display font-semibold text-xl tracking-wide">PropRelay</span>
          </Link>
          <h2 className="font-display text-5xl font-semibold leading-tight mb-6">
            Your properties,<br />
            <span className="gold-text">intelligently managed.</span>
          </h2>
          <p className="text-ink-secondary text-lg leading-relaxed max-w-md">
            One platform to handle maintenance, tenants, and revenue — powered by AI that never sleeps.
          </p>
          <div className="mt-12 space-y-4">
            {[
              'AI triage in seconds, not days',
              'One-tap landlord approval flow',
              'Auto contractor dispatch',
              'Real-time revenue tracking',
            ].map(item => (
              <div key={item} className="flex items-center gap-3">
                <div className="w-5 h-5 rounded-full bg-gold-400/15 border border-gold-400/30 flex items-center justify-center flex-shrink-0">
                  <div className="w-1.5 h-1.5 rounded-full bg-gold-400" />
                </div>
                <span className="text-sm text-ink-secondary">{item}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 lg:max-w-[520px] flex flex-col justify-center px-8 md:px-16 py-12 bg-surface border-l border-border">
        <div className="lg:hidden mb-10">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gold-gradient flex items-center justify-center">
              <Zap size={15} className="text-[#08080F]" strokeWidth={2.5} />
            </div>
            <span className="font-display font-semibold text-lg">PropRelay</span>
          </Link>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-card rounded-xl p-1 border border-border mb-8">
          {['login', 'register'].map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setError('') }}
              className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 capitalize ${
                tab === t
                  ? 'bg-elevated text-ink-primary shadow-sm border border-border/60'
                  : 'text-ink-muted hover:text-ink-secondary'
              }`}
            >
              {t === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-5 px-4 py-3 rounded-lg border border-red-500/30 bg-red-500/10 text-sm text-red-400">
            {error}
          </div>
        )}

        {tab === 'login' ? (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-2">Email address</label>
              <input
                type="email"
                required
                className="input-field"
                placeholder="you@example.com"
                value={loginForm.email}
                onChange={e => setLoginForm(p => ({ ...p, email: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-2">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  className="input-field pr-10"
                  placeholder="••••••••"
                  value={loginForm.password}
                  onChange={e => setLoginForm(p => ({ ...p, password: e.target.value }))}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-secondary"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <button type="submit" disabled={loading} className="btn-gold w-full justify-center py-3.5 mt-2">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <>Sign in <ArrowRight size={16} /></>}
            </button>
            <p className="text-center text-xs text-ink-muted pt-2">
              Don't have an account?{' '}
              <button type="button" onClick={() => setTab('register')} className="text-gold-400 hover:text-gold-300 font-medium">
                Create one
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="space-y-4 overflow-y-auto max-h-[calc(100vh-240px)] pr-1">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="block text-xs font-medium text-ink-secondary mb-2">Full name</label>
                <input
                  type="text" required className="input-field" placeholder="John Smith"
                  value={regForm.name} onChange={e => setRegForm(p => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-ink-secondary mb-2">Email address</label>
                <input
                  type="email" required className="input-field" placeholder="you@example.com"
                  value={regForm.email} onChange={e => setRegForm(p => ({ ...p, email: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">Phone (WhatsApp)</label>
                <input
                  type="text" required className="input-field" placeholder="381603334933"
                  value={regForm.phone} onChange={e => setRegForm(p => ({ ...p, phone: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">WhatsApp number</label>
                <input
                  type="text" className="input-field" placeholder="15556402370"
                  value={regForm.whatsapp_number} onChange={e => setRegForm(p => ({ ...p, whatsapp_number: e.target.value }))}
                />
              </div>
            </div>

            <div className="section-divider pt-2">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted mb-4 pt-4">
                Your first building
              </p>
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-2">Building name</label>
                  <input
                    type="text" required className="input-field" placeholder="Riverside Apartments"
                    value={regForm.building_name} onChange={e => setRegForm(p => ({ ...p, building_name: e.target.value }))}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-ink-secondary mb-2">Address</label>
                    <input
                      type="text" required className="input-field" placeholder="Kralja Petra 5"
                      value={regForm.building_address} onChange={e => setRegForm(p => ({ ...p, building_address: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-ink-secondary mb-2">City</label>
                    <input
                      type="text" required className="input-field" placeholder="Belgrade"
                      value={regForm.city} onChange={e => setRegForm(p => ({ ...p, city: e.target.value }))}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-ink-secondary mb-2">Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'} required className="input-field pr-10" placeholder="••••••••"
                      value={regForm.password} onChange={e => setRegForm(p => ({ ...p, password: e.target.value }))}
                    />
                    <button type="button" onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-secondary">
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <button type="submit" disabled={loading} className="btn-gold w-full justify-center py-3.5">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <>Create account <ArrowRight size={16} /></>}
            </button>
            <p className="text-center text-xs text-ink-muted pt-1">
              Already have an account?{' '}
              <button type="button" onClick={() => setTab('login')} className="text-gold-400 hover:text-gold-300 font-medium">
                Sign in
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
