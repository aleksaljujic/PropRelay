import { Bell, Search } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function Header({ title, subtitle }) {
  const { user } = useAuth()

  const initials = user?.name
    ? user.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
    : 'LO'

  return (
    <header className="h-16 border-b border-border bg-surface/60 backdrop-blur-sm flex items-center justify-between px-6 flex-shrink-0">
      <div>
        <h1 className="text-base font-semibold text-ink-primary">{title}</h1>
        {subtitle && <p className="text-xs text-ink-muted mt-0.5">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3">
        {/* Search */}
        <div className="relative hidden md:block">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input
            type="text"
            placeholder="Search..."
            className="pl-9 pr-4 py-2 text-xs bg-card border border-border rounded-lg text-ink-primary
                       placeholder-ink-muted outline-none w-48 focus:border-gold-400 focus:w-56 transition-all duration-200"
          />
        </div>

        {/* Notifications */}
        <button className="relative w-9 h-9 rounded-lg bg-card border border-border flex items-center justify-center
                           text-ink-secondary hover:text-gold-400 hover:border-gold-400 transition-all duration-200">
          <Bell size={16} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-gold-400" />
        </button>

        {/* Avatar */}
        <div className="w-9 h-9 rounded-lg bg-gold-gradient flex items-center justify-center flex-shrink-0 cursor-pointer">
          <span className="text-[11px] font-bold text-[#08080F]">{initials}</span>
        </div>
      </div>
    </header>
  )
}
