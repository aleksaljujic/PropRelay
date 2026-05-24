import { useState } from 'react'
import { User, Building2, Phone, Mail, Globe, Shield, Bell, Save, Loader2, CheckCircle } from 'lucide-react'
import Layout from '../components/Layout'
import { useAuth } from '../context/AuthContext'

export default function Profile() {
  const { user, login } = useAuth()
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [form, setForm] = useState({
    name: user?.name || '',
    email: user?.email || '',
    phone: user?.phone || '',
    building: user?.building || '',
    language: 'en',
    notifications_whatsapp: true,
    notifications_email: true,
  })

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    await new Promise(r => setTimeout(r, 800))
    login({ ...user, name: form.name, email: form.email, phone: form.phone, building: form.building })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const initials = form.name
    ? form.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
    : 'LO'

  return (
    <Layout title="Profile" subtitle="Manage your account settings">
      <div className="max-w-3xl space-y-6">

        {/* Profile header card */}
        <div className="card p-8 flex flex-col sm:flex-row items-center sm:items-start gap-6">
          <div className="relative flex-shrink-0">
            <div className="w-20 h-20 rounded-2xl bg-gold-gradient flex items-center justify-center shadow-gold">
              <span className="font-display text-3xl font-semibold text-[#08080F]">{initials}</span>
            </div>
            <div className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-green-400 border-2 border-base" />
          </div>
          <div className="text-center sm:text-left">
            <h2 className="text-xl font-semibold text-ink-primary">{form.name || 'Your Name'}</h2>
            <p className="text-sm text-ink-secondary mt-1">{form.email}</p>
            <div className="flex flex-wrap justify-center sm:justify-start gap-2 mt-3">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
                               bg-gold-400/10 border border-gold-400/25 text-gold-300">
                <Shield size={11} /> Verified Landlord
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
                               bg-green-400/10 border border-green-400/25 text-green-400">
                <CheckCircle size={11} /> WhatsApp Active
              </span>
            </div>
          </div>
          <div className="sm:ml-auto grid grid-cols-3 gap-4 text-center">
            {[
              { label: 'Properties', value: '12' },
              { label: 'Tenants', value: '47' },
              { label: 'Revenue', value: '€27k' },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="text-lg font-semibold gold-text">{value}</p>
                <p className="text-[11px] text-ink-muted">{label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Personal info */}
        <form onSubmit={handleSave} className="space-y-5">
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-6 pb-4 border-b border-border">
              <User size={16} className="text-gold-400" />
              <h3 className="text-sm font-semibold text-ink-primary">Personal Information</h3>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">Full name</label>
                <input
                  type="text" className="input-field" placeholder="John Smith"
                  value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">Email address</label>
                <div className="relative">
                  <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                  <input
                    type="email" className="input-field pl-9" placeholder="you@example.com"
                    value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">WhatsApp / Phone</label>
                <div className="relative">
                  <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                  <input
                    type="text" className="input-field pl-9" placeholder="381603334933"
                    value={form.phone} onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-secondary mb-2">Language</label>
                <div className="relative">
                  <Globe size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                  <select
                    className="input-field pl-9 appearance-none cursor-pointer"
                    value={form.language}
                    onChange={e => setForm(p => ({ ...p, language: e.target.value }))}
                  >
                    <option value="en">English</option>
                    <option value="sr">Serbian</option>
                    <option value="de">German</option>
                    <option value="fr">French</option>
                    <option value="es">Spanish</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Building info */}
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-6 pb-4 border-b border-border">
              <Building2 size={16} className="text-gold-400" />
              <h3 className="text-sm font-semibold text-ink-primary">Primary Building</h3>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-2">Building name</label>
              <input
                type="text" className="input-field" placeholder="Riverside Apartments"
                value={form.building} onChange={e => setForm(p => ({ ...p, building: e.target.value }))}
              />
            </div>
          </div>

          {/* Notifications */}
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-6 pb-4 border-b border-border">
              <Bell size={16} className="text-gold-400" />
              <h3 className="text-sm font-semibold text-ink-primary">Notifications</h3>
            </div>
            <div className="space-y-4">
              {[
                { key: 'notifications_whatsapp', label: 'WhatsApp notifications', sub: 'Receive ticket updates and approvals via WhatsApp' },
                { key: 'notifications_email', label: 'Email notifications', sub: 'Weekly digest and important alerts via email' },
              ].map(({ key, label, sub }) => (
                <div key={key} className="flex items-center justify-between py-3 border-b border-border/50 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-ink-primary">{label}</p>
                    <p className="text-xs text-ink-muted mt-0.5">{sub}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setForm(p => ({ ...p, [key]: !p[key] }))}
                    className={`relative w-11 h-6 rounded-full border transition-all duration-200 flex-shrink-0 ${
                      form[key]
                        ? 'bg-gold-gradient border-gold-400/40'
                        : 'bg-elevated border-border'
                    }`}
                  >
                    <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all duration-200 ${
                      form[key] ? 'left-5' : 'left-0.5'
                    }`} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Save button */}
          <div className="flex items-center gap-3 justify-end">
            {saved && (
              <span className="flex items-center gap-1.5 text-sm text-green-400">
                <CheckCircle size={15} /> Changes saved
              </span>
            )}
            <button type="submit" disabled={saving} className="btn-gold px-8 py-3">
              {saving
                ? <><Loader2 size={15} className="animate-spin" /> Saving...</>
                : <><Save size={15} /> Save changes</>}
            </button>
          </div>
        </form>
      </div>
    </Layout>
  )
}
