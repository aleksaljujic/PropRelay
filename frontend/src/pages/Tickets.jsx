import { useState } from 'react'
import { Clock, CheckCircle2, AlertCircle, Wrench, Filter, Search } from 'lucide-react'
import Layout from '../components/Layout'

const tickets = [
  { id: 'TK-0041', tenant: 'Maria V.', unit: '3A', building: 'Riverside Apartments', issue: 'Bathroom pipe leaking', urgency: 'high', status: 'awaiting_landlord', age: '2h ago', category: 'plumbing', estimate: '€120–180' },
  { id: 'TK-0040', tenant: 'Stefan B.', unit: '7C', building: 'Central Tower', issue: 'Heater not working', urgency: 'medium', status: 'dispatched', age: '5h ago', category: 'hvac', estimate: '€80–120' },
  { id: 'TK-0039', tenant: 'Ana P.', unit: '1B', building: 'Garden View', issue: 'Door lock broken', urgency: 'high', status: 'triaged', age: '8h ago', category: 'locksmith', estimate: '€60–90' },
  { id: 'TK-0038', tenant: 'Luka M.', unit: '5D', building: 'Riverside Apartments', issue: 'Light fixture', urgency: 'low', status: 'completed', age: '1d ago', category: 'electrical', estimate: '€40–60' },
  { id: 'TK-0037', tenant: 'Nina K.', unit: '2A', building: 'Old Town Lofts', issue: 'Window seal draft', urgency: 'low', status: 'completed', age: '2d ago', category: 'general', estimate: '€30–50' },
  { id: 'TK-0036', tenant: 'Marko D.', unit: '4B', building: 'Central Tower', issue: 'Dishwasher leak', urgency: 'medium', status: 'completed', age: '3d ago', category: 'plumbing', estimate: '€90–140' },
  { id: 'TK-0035', tenant: 'Jelena S.', unit: '6A', building: 'Harbor Flats', issue: 'Mold in bathroom', urgency: 'high', status: 'completed', age: '4d ago', category: 'general', estimate: '€200–350' },
]

const statusConfig = {
  new: { label: 'New', color: 'text-blue-400 bg-blue-400/10 border-blue-400/25' },
  triaged: { label: 'Triaged', color: 'text-purple-400 bg-purple-400/10 border-purple-400/25' },
  awaiting_landlord: { label: 'Needs approval', color: 'text-gold-400 bg-gold-400/10 border-gold-400/25' },
  dispatched: { label: 'Dispatched', color: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/25' },
  completed: { label: 'Completed', color: 'text-green-400 bg-green-400/10 border-green-400/25' },
}

const urgencyConfig = {
  high: { dot: 'bg-red-400', label: 'High', textColor: 'text-red-400' },
  medium: { dot: 'bg-yellow-400', label: 'Medium', textColor: 'text-yellow-400' },
  low: { dot: 'bg-green-400', label: 'Low', textColor: 'text-green-400' },
}

export default function TicketsPage() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [search, setSearch] = useState('')

  const statuses = ['all', 'awaiting_landlord', 'triaged', 'dispatched', 'completed']
  const statusLabels = { all: 'All', awaiting_landlord: 'Needs Approval', triaged: 'Triaged', dispatched: 'Dispatched', completed: 'Completed' }

  const filtered = tickets.filter(t => {
    const matchStatus = statusFilter === 'all' || t.status === statusFilter
    const matchSearch = t.issue.toLowerCase().includes(search.toLowerCase()) ||
                        t.tenant.toLowerCase().includes(search.toLowerCase()) ||
                        t.building.toLowerCase().includes(search.toLowerCase())
    return matchStatus && matchSearch
  })

  const counts = {
    open: tickets.filter(t => t.status !== 'completed').length,
    needsApproval: tickets.filter(t => t.status === 'awaiting_landlord').length,
    completed: tickets.filter(t => t.status === 'completed').length,
  }

  return (
    <Layout title="Tickets" subtitle="Maintenance requests across your portfolio">
      <div className="space-y-6 max-w-[1400px]">

        {/* Summary */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Open Tickets', value: counts.open, icon: AlertCircle, color: 'text-yellow-400', bg: 'bg-yellow-400/10 border-yellow-400/20' },
            { label: 'Need Your Approval', value: counts.needsApproval, icon: Clock, color: 'text-gold-400', bg: 'bg-gold-400/10 border-gold-400/20' },
            { label: 'Resolved This Month', value: counts.completed, icon: CheckCircle2, color: 'text-green-400', bg: 'bg-green-400/10 border-green-400/20' },
          ].map(({ label, value, icon: Icon, color, bg }) => (
            <div key={label} className="card p-5 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 ${bg}`}>
                <Icon size={18} className={color} />
              </div>
              <div>
                <p className="text-xs text-ink-muted">{label}</p>
                <p className="text-2xl font-semibold text-ink-primary">{value}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
          <div className="flex gap-2 flex-wrap">
            {statuses.map(s => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200 ${
                  statusFilter === s
                    ? 'bg-gold-400/15 border-gold-400/40 text-gold-300'
                    : 'border-border text-ink-muted hover:text-ink-secondary bg-card'
                }`}
              >
                {statusLabels[s]}
              </button>
            ))}
          </div>
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input
              type="text"
              placeholder="Search tickets..."
              className="pl-8 pr-4 py-2 text-xs input-field w-52"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Tickets table */}
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  {['ID', 'Tenant / Unit', 'Building', 'Issue', 'Category', 'Urgency', 'Est. Cost', 'Status', 'Age'].map(h => (
                    <th key={h} className="px-5 py-3.5 text-left text-[10px] font-semibold uppercase tracking-widest text-ink-muted whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {filtered.map(({ id, tenant, unit, building, issue, urgency, status, age, category, estimate }) => {
                  const s = statusConfig[status]
                  const u = urgencyConfig[urgency]
                  return (
                    <tr key={id} className="hover:bg-elevated/50 transition-colors duration-150 cursor-pointer group">
                      <td className="px-5 py-4 text-xs font-mono text-ink-muted group-hover:text-gold-400 transition-colors">{id}</td>
                      <td className="px-5 py-4">
                        <p className="text-xs font-medium text-ink-primary">{tenant}</p>
                        <p className="text-[10px] text-ink-muted">Unit {unit}</p>
                      </td>
                      <td className="px-5 py-4 text-xs text-ink-secondary whitespace-nowrap">{building}</td>
                      <td className="px-5 py-4 text-xs text-ink-secondary max-w-[180px] truncate">{issue}</td>
                      <td className="px-5 py-4">
                        <span className="text-xs text-ink-muted capitalize">{category}</span>
                      </td>
                      <td className="px-5 py-4">
                        <span className={`flex items-center gap-1.5 text-xs ${u.textColor}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${u.dot}`} />
                          {u.label}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-xs font-medium text-ink-secondary whitespace-nowrap">{estimate}</td>
                      <td className="px-5 py-4">
                        <span className={`inline-flex px-2.5 py-1 rounded-md text-[10px] font-medium border whitespace-nowrap ${s.color}`}>
                          {s.label}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-xs text-ink-muted whitespace-nowrap">
                        <span className="flex items-center gap-1"><Clock size={11} />{age}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="text-center py-16 text-ink-muted text-sm">No tickets found.</div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  )
}
