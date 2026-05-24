import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Cell
} from 'recharts'
import { TrendingUp, Building2, Ticket, Users, ArrowUpRight, ArrowDownRight, Clock, CheckCircle2, AlertCircle } from 'lucide-react'
import Layout from '../components/Layout'
import { useAuth } from '../context/AuthContext'

const revenueData = [
  { month: 'Jan', revenue: 18400, expenses: 3200 },
  { month: 'Feb', revenue: 19200, expenses: 2800 },
  { month: 'Mar', revenue: 21000, expenses: 4100 },
  { month: 'Apr', revenue: 20500, expenses: 3600 },
  { month: 'May', revenue: 22800, expenses: 3100 },
  { month: 'Jun', revenue: 24100, expenses: 5200 },
  { month: 'Jul', revenue: 23500, expenses: 2900 },
  { month: 'Aug', revenue: 25200, expenses: 3400 },
  { month: 'Sep', revenue: 24800, expenses: 4800 },
  { month: 'Oct', revenue: 26100, expenses: 3700 },
  { month: 'Nov', revenue: 25600, expenses: 3200 },
  { month: 'Dec', revenue: 27400, expenses: 4200 },
]

const propertyPerformance = [
  { name: 'Riverside Apts', revenue: 8400, occupancy: 100 },
  { name: 'Central Tower', revenue: 7200, occupancy: 92 },
  { name: 'Garden View', revenue: 5800, occupancy: 87 },
  { name: 'Old Town Lofts', revenue: 4100, occupancy: 95 },
  { name: 'Harbor Flats', revenue: 2800, occupancy: 80 },
]

const recentTickets = [
  { id: 'TK-0041', tenant: 'Maria V.', unit: '3A', issue: 'Bathroom pipe leaking', urgency: 'high', status: 'awaiting_landlord', age: '2h ago' },
  { id: 'TK-0040', tenant: 'Stefan B.', unit: '7C', issue: 'Heater not working', urgency: 'medium', status: 'dispatched', age: '5h ago' },
  { id: 'TK-0039', tenant: 'Ana P.', unit: '1B', issue: 'Door lock broken', urgency: 'high', status: 'triaged', age: '8h ago' },
  { id: 'TK-0038', tenant: 'Luka M.', unit: '5D', issue: 'Light fixture', urgency: 'low', status: 'completed', age: '1d ago' },
  { id: 'TK-0037', tenant: 'Nina K.', unit: '2A', issue: 'Window seal draft', urgency: 'low', status: 'completed', age: '2d ago' },
]

const statusConfig = {
  new: { label: 'New', color: 'text-blue-400 bg-blue-400/10 border-blue-400/25' },
  triaged: { label: 'Triaged', color: 'text-purple-400 bg-purple-400/10 border-purple-400/25' },
  awaiting_landlord: { label: 'Needs approval', color: 'text-gold-400 bg-gold-400/10 border-gold-400/25' },
  dispatched: { label: 'Dispatched', color: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/25' },
  completed: { label: 'Completed', color: 'text-green-400 bg-green-400/10 border-green-400/25' },
}

const urgencyDot = { high: 'bg-red-400', medium: 'bg-yellow-400', low: 'bg-green-400' }

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="card px-4 py-3 text-xs space-y-1.5 min-w-[140px]">
        <p className="text-ink-muted font-medium">{label}</p>
        <p className="text-gold-400 font-semibold">Revenue: €{payload[0]?.value?.toLocaleString()}</p>
        <p className="text-red-400/70">Expenses: €{payload[1]?.value?.toLocaleString()}</p>
      </div>
    )
  }
  return null
}

export default function Dashboard() {
  const { user } = useAuth()
  const currentRevenue = 27400
  const prevRevenue = 25600
  const growth = (((currentRevenue - prevRevenue) / prevRevenue) * 100).toFixed(1)

  return (
    <Layout title="Dashboard" subtitle={`Welcome back${user?.name ? ', ' + user.name.split(' ')[0] : ''}`}>
      <div className="space-y-6 max-w-[1400px]">

        {/* Stat cards */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          {[
            {
              label: 'Monthly Revenue',
              value: '€27,400',
              change: `+${growth}%`,
              positive: true,
              icon: TrendingUp,
              sub: 'vs last month',
            },
            {
              label: 'Active Properties',
              value: '12',
              change: '+1',
              positive: true,
              icon: Building2,
              sub: 'buildings',
            },
            {
              label: 'Open Tickets',
              value: '3',
              change: '-2',
              positive: true,
              icon: Ticket,
              sub: 'need attention',
            },
            {
              label: 'Total Tenants',
              value: '47',
              change: '100%',
              positive: true,
              icon: Users,
              sub: 'occupancy rate',
            },
          ].map(({ label, value, change, positive, icon: Icon, sub }) => (
            <div key={label} className="stat-card group hover:border-gold-400/20 transition-all duration-200">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-ink-muted uppercase tracking-wider">{label}</span>
                <div className="w-8 h-8 rounded-lg bg-gold-400/8 flex items-center justify-center
                                group-hover:bg-gold-400/15 transition-colors duration-200">
                  <Icon size={15} className="text-gold-400" />
                </div>
              </div>
              <div>
                <p className="text-3xl font-semibold text-ink-primary tracking-tight">{value}</p>
                <div className="flex items-center gap-1.5 mt-1.5">
                  {positive
                    ? <ArrowUpRight size={13} className="text-green-400" />
                    : <ArrowDownRight size={13} className="text-red-400" />}
                  <span className={`text-xs font-medium ${positive ? 'text-green-400' : 'text-red-400'}`}>{change}</span>
                  <span className="text-xs text-ink-muted">{sub}</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Revenue area chart */}
          <div className="card p-6 xl:col-span-2">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-sm font-semibold text-ink-primary">Revenue Overview</h3>
                <p className="text-xs text-ink-muted mt-0.5">12-month revenue vs expenses</p>
              </div>
              <div className="flex items-center gap-4 text-xs text-ink-muted">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-gold-400" />Revenue
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-400/60" />Expenses
                </span>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={revenueData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="goldGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#D4AF61" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#D4AF61" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="redGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#F87171" stopOpacity={0.12} />
                    <stop offset="95%" stopColor="#F87171" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#252540" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#5C5A70' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#5C5A70' }} axisLine={false} tickLine={false}
                  tickFormatter={v => `€${(v / 1000).toFixed(0)}k`} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="revenue" stroke="#D4AF61" strokeWidth={2}
                  fill="url(#goldGrad)" dot={false} activeDot={{ r: 4, fill: '#D4AF61', strokeWidth: 0 }} />
                <Area type="monotone" dataKey="expenses" stroke="#F87171" strokeWidth={1.5} strokeOpacity={0.6}
                  fill="url(#redGrad)" dot={false} activeDot={{ r: 3, fill: '#F87171', strokeWidth: 0 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Property performance bar */}
          <div className="card p-6">
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-ink-primary">Top Properties</h3>
              <p className="text-xs text-ink-muted mt-0.5">Monthly revenue</p>
            </div>
            <div className="space-y-4">
              {propertyPerformance.map(({ name, revenue, occupancy }) => (
                <div key={name}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs text-ink-secondary truncate max-w-[120px]">{name}</span>
                    <span className="text-xs font-semibold text-ink-primary">€{revenue.toLocaleString()}</span>
                  </div>
                  <div className="h-1.5 bg-elevated rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gold-gradient rounded-full transition-all duration-700"
                      style={{ width: `${(revenue / 8400) * 100}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-ink-muted mt-1">{occupancy}% occupied</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Recent tickets */}
        <div className="card">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
            <div>
              <h3 className="text-sm font-semibold text-ink-primary">Recent Tickets</h3>
              <p className="text-xs text-ink-muted mt-0.5">Maintenance requests requiring attention</p>
            </div>
            <button className="text-xs text-gold-400 hover:text-gold-300 font-medium transition-colors">
              View all →
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  {['Ticket', 'Tenant', 'Issue', 'Urgency', 'Status', 'Time'].map(h => (
                    <th key={h} className="px-6 py-3 text-left text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {recentTickets.map(({ id, tenant, unit, issue, urgency, status, age }) => {
                  const s = statusConfig[status]
                  return (
                    <tr key={id} className="hover:bg-elevated/50 transition-colors duration-150 cursor-pointer">
                      <td className="px-6 py-4 text-xs font-mono text-ink-muted">{id}</td>
                      <td className="px-6 py-4">
                        <p className="text-xs font-medium text-ink-primary">{tenant}</p>
                        <p className="text-[10px] text-ink-muted">Unit {unit}</p>
                      </td>
                      <td className="px-6 py-4 text-xs text-ink-secondary max-w-[200px] truncate">{issue}</td>
                      <td className="px-6 py-4">
                        <span className="flex items-center gap-1.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${urgencyDot[urgency]}`} />
                          <span className="text-xs text-ink-secondary capitalize">{urgency}</span>
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex px-2.5 py-1 rounded-md text-[10px] font-medium border ${s.color}`}>
                          {s.label}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-xs text-ink-muted flex items-center gap-1">
                        <Clock size={11} />
                        {age}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Layout>
  )
}
