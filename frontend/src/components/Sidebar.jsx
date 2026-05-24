import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Building2,
  Ticket,
  User,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Zap,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/properties', icon: Building2, label: 'Properties' },
  { to: '/tickets', icon: Ticket, label: 'Tickets' },
  { to: '/profile', icon: User, label: 'Profile' },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/')
  }

  return (
    <aside
      className={`relative flex flex-col bg-surface border-r border-border transition-all duration-300 ease-in-out ${
        collapsed ? 'w-[72px]' : 'w-[240px]'
      }`}
      style={{ minHeight: '100vh' }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 h-16 border-b border-border flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-gold-gradient flex items-center justify-center flex-shrink-0">
          <Zap size={16} className="text-[#08080F]" strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <span className="font-display font-semibold text-lg text-ink-primary tracking-wide whitespace-nowrap">
            PropRelay
          </span>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-[72px] w-6 h-6 rounded-full bg-card border border-border
                   flex items-center justify-center text-ink-muted hover:text-gold-400 hover:border-gold-400
                   transition-all duration-200 z-10"
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-6 space-y-1 overflow-hidden">
        {!collapsed && (
          <p className="px-4 mb-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
            Main Menu
          </p>
        )}
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''} ${collapsed ? 'justify-center px-0' : ''}`
            }
            title={collapsed ? label : undefined}
          >
            <Icon size={18} className="flex-shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* User section */}
      <div className="px-3 pb-6 border-t border-border pt-4 space-y-1">
        {!collapsed && user && (
          <div className="px-4 py-3 mb-2">
            <p className="text-xs font-medium text-ink-primary truncate">{user.name}</p>
            <p className="text-[11px] text-ink-muted truncate mt-0.5">{user.email}</p>
          </div>
        )}
        <button
          onClick={handleLogout}
          className={`nav-item w-full text-left hover:text-red-400 ${collapsed ? 'justify-center px-0' : ''}`}
          title={collapsed ? 'Logout' : undefined}
        >
          <LogOut size={18} className="flex-shrink-0" />
          {!collapsed && <span>Logout</span>}
        </button>
      </div>
    </aside>
  )
}
