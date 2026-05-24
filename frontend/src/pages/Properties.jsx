import { useState } from 'react'
import { Building2, MapPin, Users, TrendingUp, Wrench, Plus, Search, Filter, MoreVertical, CheckCircle } from 'lucide-react'
import Layout from '../components/Layout'

const properties = [
  {
    id: 1,
    name: 'Riverside Apartments',
    address: 'Dunavska 12, Belgrade',
    city: 'Belgrade',
    units: 8,
    tenants: 8,
    monthlyRevenue: 8400,
    annualRevenue: 100800,
    occupancy: 100,
    openTickets: 1,
    type: 'Apartment Block',
    image: null,
    status: 'occupied',
  },
  {
    id: 2,
    name: 'Central Tower',
    address: 'Knez Mihailova 45, Belgrade',
    city: 'Belgrade',
    units: 12,
    tenants: 11,
    monthlyRevenue: 7200,
    annualRevenue: 86400,
    occupancy: 92,
    openTickets: 0,
    type: 'High-rise',
    image: null,
    status: 'occupied',
  },
  {
    id: 3,
    name: 'Garden View Residences',
    address: 'Vojvode Stepe 88, Novi Sad',
    city: 'Novi Sad',
    units: 6,
    tenants: 5,
    monthlyRevenue: 5800,
    annualRevenue: 69600,
    occupancy: 87,
    openTickets: 2,
    type: 'Villa',
    image: null,
    status: 'partial',
  },
  {
    id: 4,
    name: 'Old Town Lofts',
    address: 'Skadarska 7, Belgrade',
    city: 'Belgrade',
    units: 4,
    tenants: 4,
    monthlyRevenue: 4100,
    annualRevenue: 49200,
    occupancy: 100,
    openTickets: 0,
    type: 'Loft',
    image: null,
    status: 'occupied',
  },
  {
    id: 5,
    name: 'Harbor Flats',
    address: 'Primorska 3, Split',
    city: 'Split',
    units: 5,
    tenants: 4,
    monthlyRevenue: 2800,
    annualRevenue: 33600,
    occupancy: 80,
    openTickets: 0,
    type: 'Seaside',
    image: null,
    status: 'partial',
  },
  {
    id: 6,
    name: 'The Penthouse Collection',
    address: 'Terazije 1, Belgrade',
    city: 'Belgrade',
    units: 3,
    tenants: 3,
    monthlyRevenue: 9100,
    annualRevenue: 109200,
    occupancy: 100,
    openTickets: 0,
    type: 'Penthouse',
    image: null,
    status: 'occupied',
  },
]

const typeColors = {
  'Apartment Block': 'text-blue-400 bg-blue-400/10 border-blue-400/25',
  'High-rise': 'text-purple-400 bg-purple-400/10 border-purple-400/25',
  'Villa': 'text-green-400 bg-green-400/10 border-green-400/25',
  'Loft': 'text-cyan-400 bg-cyan-400/10 border-cyan-400/25',
  'Seaside': 'text-teal-400 bg-teal-400/10 border-teal-400/25',
  'Penthouse': 'text-gold-400 bg-gold-400/10 border-gold-400/25',
}

function PropertyCard({ property }) {
  const { name, address, city, units, tenants, monthlyRevenue, occupancy, openTickets, type } = property
  const initials = name.split(' ').slice(0, 2).map(w => w[0]).join('')

  return (
    <div className="card group hover:border-gold-400/25 hover:shadow-gold transition-all duration-300 overflow-hidden">
      {/* Card image / placeholder */}
      <div className="h-40 bg-elevated flex items-center justify-center relative border-b border-border overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-gold-400/5 via-transparent to-transparent" />
        <div className="w-16 h-16 rounded-2xl bg-card border border-border/60 flex items-center justify-center
                        group-hover:border-gold-400/30 transition-all duration-200">
          <span className="font-display text-2xl font-semibold gold-text">{initials}</span>
        </div>
        {/* Occupancy badge */}
        <div className="absolute top-3 right-3">
          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold border ${
            occupancy === 100 ? 'text-green-400 bg-green-400/10 border-green-400/25' : 'text-yellow-400 bg-yellow-400/10 border-yellow-400/25'
          }`}>
            {occupancy === 100 ? <CheckCircle size={10} /> : null}
            {occupancy}% full
          </span>
        </div>
        {/* Type badge */}
        <div className="absolute top-3 left-3">
          <span className={`inline-flex px-2.5 py-1 rounded-full text-[10px] font-medium border ${typeColors[type] || 'text-ink-muted bg-elevated border-border'}`}>
            {type}
          </span>
        </div>
      </div>

      <div className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-ink-primary group-hover:text-gold-300 transition-colors">{name}</h3>
            <div className="flex items-center gap-1 mt-1">
              <MapPin size={11} className="text-ink-muted flex-shrink-0" />
              <span className="text-[11px] text-ink-muted truncate">{address}</span>
            </div>
          </div>
          <button className="text-ink-muted hover:text-ink-primary transition-colors p-1">
            <MoreVertical size={15} />
          </button>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="text-center py-2.5 bg-elevated rounded-lg border border-border/50">
            <p className="text-base font-semibold text-ink-primary">{units}</p>
            <p className="text-[10px] text-ink-muted">Units</p>
          </div>
          <div className="text-center py-2.5 bg-elevated rounded-lg border border-border/50">
            <p className="text-base font-semibold text-ink-primary">{tenants}</p>
            <p className="text-[10px] text-ink-muted">Tenants</p>
          </div>
          <div className="text-center py-2.5 bg-elevated rounded-lg border border-border/50">
            <p className={`text-base font-semibold ${openTickets > 0 ? 'text-yellow-400' : 'text-green-400'}`}>
              {openTickets}
            </p>
            <p className="text-[10px] text-ink-muted">Tickets</p>
          </div>
        </div>

        {/* Revenue */}
        <div className="flex items-center justify-between pt-3 border-t border-border/50">
          <div>
            <p className="text-xs text-ink-muted">Monthly revenue</p>
            <p className="text-lg font-semibold gold-text mt-0.5">€{monthlyRevenue.toLocaleString()}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-ink-muted">Annual</p>
            <p className="text-sm font-medium text-ink-secondary mt-0.5">€{(monthlyRevenue * 12).toLocaleString()}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Properties() {
  const [search, setSearch] = useState('')
  const [cityFilter, setCityFilter] = useState('All')

  const cities = ['All', ...new Set(properties.map(p => p.city))]

  const filtered = properties.filter(p => {
    const matchSearch = p.name.toLowerCase().includes(search.toLowerCase()) ||
                        p.address.toLowerCase().includes(search.toLowerCase())
    const matchCity = cityFilter === 'All' || p.city === cityFilter
    return matchSearch && matchCity
  })

  const totalRevenue = properties.reduce((s, p) => s + p.monthlyRevenue, 0)
  const totalUnits = properties.reduce((s, p) => s + p.units, 0)
  const avgOccupancy = Math.round(properties.reduce((s, p) => s + p.occupancy, 0) / properties.length)

  return (
    <Layout title="Properties" subtitle="Manage your portfolio">
      <div className="space-y-6 max-w-[1400px]">

        {/* Summary strip */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total Portfolio Revenue', value: `€${totalRevenue.toLocaleString()}`, sub: 'per month', icon: TrendingUp },
            { label: 'Total Units', value: totalUnits, sub: `across ${properties.length} properties`, icon: Building2 },
            { label: 'Avg Occupancy', value: `${avgOccupancy}%`, sub: 'portfolio wide', icon: Users },
          ].map(({ label, value, sub, icon: Icon }) => (
            <div key={label} className="card p-5 flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-gold-400/10 border border-gold-400/20 flex items-center justify-center flex-shrink-0">
                <Icon size={18} className="text-gold-400" />
              </div>
              <div>
                <p className="text-xs text-ink-muted">{label}</p>
                <p className="text-xl font-semibold text-ink-primary mt-0.5">{value}</p>
                <p className="text-[11px] text-ink-muted">{sub}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Controls */}
        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
          <div className="flex gap-2 flex-wrap">
            {cities.map(c => (
              <button
                key={c}
                onClick={() => setCityFilter(c)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200 ${
                  cityFilter === c
                    ? 'bg-gold-400/15 border-gold-400/40 text-gold-300'
                    : 'border-border text-ink-muted hover:border-border hover:text-ink-secondary bg-card'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="flex gap-3">
            <div className="relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input
                type="text"
                placeholder="Search properties..."
                className="pl-8 pr-4 py-2 text-xs input-field w-52"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <button className="btn-gold text-xs px-4 py-2">
              <Plus size={14} />
              Add property
            </button>
          </div>
        </div>

        {/* Property grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {filtered.map(property => (
            <PropertyCard key={property.id} property={property} />
          ))}
          {filtered.length === 0 && (
            <div className="col-span-3 text-center py-20 text-ink-muted text-sm">
              No properties match your search.
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
