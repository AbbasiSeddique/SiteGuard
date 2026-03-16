import { NavLink } from 'react-router';
import { Shield, Home, ScanEye, LayoutDashboard, FileText } from 'lucide-react';

export function Navigation() {
  return (
    <nav className="bg-white/80 backdrop-blur-lg border-b border-slate-200/60 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="bg-gradient-to-br from-blue-600 to-indigo-600 p-2 rounded-xl shadow-lg shadow-blue-500/20">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="font-semibold text-slate-900">SiteGuard</div>
              <div className="text-xs text-slate-500">Workplace Safety Analyzer</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <NavItem to="/" icon={Home} label="Home" />
            <NavItem to="/inspect" icon={ScanEye} label="Inspect" />
            <NavItem to="/dashboard" icon={LayoutDashboard} label="Dashboard" />
            <NavItem to="/reports" icon={FileText} label="Reports" />
          </div>
        </div>
      </div>
    </nav>
  );
}

function NavItem({ to, icon: Icon, label }: { to: string; icon: any; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200 ${
          isActive
            ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow-lg shadow-blue-500/30'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
        }`
      }
    >
      <Icon className="w-4 h-4" />
      <span className="text-sm">{label}</span>
    </NavLink>
  );
}
