import { useState } from 'react';
import { Camera, Bell, TrendingDown, Shield, AlertTriangle, Activity, Eye, FileText, Sparkles, X, Send } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const trendData = [
  { day: 'Mon', violations: 12 },
  { day: 'Tue', violations: 8 },
  { day: 'Wed', violations: 15 },
  { day: 'Thu', violations: 6 },
  { day: 'Fri', violations: 10 },
  { day: 'Sat', violations: 14 },
  { day: 'Sun', violations: 10 },
];

const severityData = [
  { severity: 'Critical', count: 75, color: '#ef4444' },
  { severity: 'High', count: 37, color: '#f97316' },
  { severity: 'Medium', count: 30, color: '#eab308' },
  { severity: 'Low', count: 7, color: '#84cc16' },
];

export function DashboardPage() {
  const [activeTab, setActiveTab] = useState('overview');
  const [ariaOpen, setAriaOpen] = useState(false);
  const [ariaMessage, setAriaMessage] = useState('');

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 relative">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 mb-2">Safety Operations Centre</h1>
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span>Live · Real-time updates active</span>
            </div>
          </div>
          <button className="bg-gradient-to-r from-blue-600 to-indigo-600 text-white px-6 py-3 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200 flex items-center gap-2">
            <Activity className="w-4 h-4" />
            New Analysis
          </button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <StatCard
          icon={Camera}
          label="Active Cameras"
          value="0"
          trend={null}
          color="blue"
        />
        <StatCard
          icon={Bell}
          label="Open Alerts"
          value="0"
          trend={null}
          color="red"
        />
        <StatCard
          icon={AlertTriangle}
          label="Violations (30d)"
          value="75"
          trend={-12}
          color="orange"
        />
        <StatCard
          icon={Eye}
          label="Total Scans"
          value="0"
          trend={null}
          color="purple"
        />
        <StatCard
          icon={Shield}
          label="Compliance Score"
          value="0%"
          trend={null}
          color="green"
        />
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-6">
        <div className="border-b border-slate-200 px-6">
          <div className="flex gap-1 overflow-x-auto">
            <Tab
              active={activeTab === 'overview'}
              onClick={() => setActiveTab('overview')}
              icon={Shield}
              label="Overview"
            />
            <Tab
              active={activeTab === 'analytics'}
              onClick={() => setActiveTab('analytics')}
              icon={TrendingDown}
              label="Analytics"
            />
            <Tab
              active={activeTab === 'scans'}
              onClick={() => setActiveTab('scans')}
              icon={Eye}
              label="Scans"
            />
            <Tab
              active={activeTab === 'cameras'}
              onClick={() => setActiveTab('cameras')}
              icon={Camera}
              label="Cameras"
            />
            <Tab
              active={activeTab === 'alerts'}
              onClick={() => setActiveTab('alerts')}
              icon={Bell}
              label="Alerts"
            />
          </div>
        </div>

        <div className="p-6">
          {activeTab === 'overview' && <OverviewTab />}
          {activeTab === 'analytics' && <AnalyticsTab />}
          {activeTab === 'scans' && <ScansTab />}
          {activeTab === 'cameras' && <CamerasTab />}
          {activeTab === 'alerts' && <AlertsTab />}
        </div>
      </div>

      {/* Floating ARIA Button */}
      <button
        onClick={() => setAriaOpen(!ariaOpen)}
        className="fixed bottom-8 right-8 bg-gradient-to-br from-indigo-600 to-purple-600 text-white p-4 rounded-full shadow-2xl hover:shadow-indigo-500/50 transition-all duration-200 hover:scale-110 z-50"
      >
        <Sparkles className="w-6 h-6" />
      </button>

      {/* ARIA Chat Panel */}
      {ariaOpen && (
        <div className="fixed bottom-24 right-8 w-96 bg-white rounded-2xl shadow-2xl border border-slate-200 z-50 overflow-hidden">
          <div className="bg-gradient-to-r from-indigo-600 to-purple-600 p-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-white" />
              <span className="font-semibold text-white">ARIA Intelligence</span>
            </div>
            <button
              onClick={() => setAriaOpen(false)}
              className="text-white hover:bg-white/20 p-1 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="h-96 overflow-y-auto p-4 bg-slate-50">
            <div className="space-y-4">
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <p className="text-sm text-slate-700">
                  Hello! I'm ARIA, your safety intelligence assistant. Ask me about site safety, violations, or OSHA standards.
                </p>
              </div>
              <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg p-3 border border-blue-100">
                <p className="text-xs text-blue-900 mb-2 font-medium">Suggestions:</p>
                <div className="space-y-1">
                  <button className="text-xs text-blue-700 hover:text-blue-900 block">
                    → What are the most common violations this month?
                  </button>
                  <button className="text-xs text-blue-700 hover:text-blue-900 block">
                    → Explain OSHA 1926.100(a) requirements
                  </button>
                  <button className="text-xs text-blue-700 hover:text-blue-900 block">
                    → How can I improve compliance scores?
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="p-4 bg-white border-t border-slate-200">
            <div className="flex gap-2">
              <input
                type="text"
                value={ariaMessage}
                onChange={(e) => setAriaMessage(e.target.value)}
                placeholder="Ask ARIA about safety..."
                className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent text-sm"
              />
              <button className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white p-2 rounded-lg hover:shadow-lg transition-all duration-200">
                <Send className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, trend, color }: any) {
  const colorClasses = {
    blue: 'from-blue-500 to-blue-600',
    red: 'from-red-500 to-red-600',
    orange: 'from-orange-500 to-orange-600',
    purple: 'from-purple-500 to-purple-600',
    green: 'from-green-500 to-green-600',
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <div className={`bg-gradient-to-br ${colorClasses[color]} w-10 h-10 rounded-lg flex items-center justify-center mb-3`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <div className="text-2xl font-bold text-slate-900 mb-1">{value}</div>
      <div className="text-xs text-slate-600 mb-2">{label}</div>
      {trend !== null && (
        <div className={`text-xs ${trend < 0 ? 'text-green-600' : 'text-red-600'}`}>
          {trend < 0 ? '↓' : '↑'} {Math.abs(trend)}% vs last month
        </div>
      )}
    </div>
  );
}

function Tab({ active, onClick, icon: Icon, label }: any) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-3 border-b-2 transition-all duration-200 ${
        active
          ? 'border-blue-600 text-blue-600'
          : 'border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300'
      }`}
    >
      <Icon className="w-4 h-4" />
      <span className="text-sm whitespace-nowrap">{label}</span>
    </button>
  );
}

function OverviewTab() {
  return (
    <div className="grid lg:grid-cols-2 gap-6">
      {/* Violations by Severity */}
      <div>
        <h3 className="font-semibold text-slate-900 mb-4">Violations by Severity</h3>
        <div className="space-y-3">
          {severityData.map((item) => (
            <div key={item.severity} className="flex items-center gap-4">
              <div className="w-24 text-sm text-slate-600">{item.severity}</div>
              <div className="flex-1 bg-slate-100 rounded-full h-8 overflow-hidden">
                <div
                  className="h-full flex items-center justify-end px-3 text-white text-sm font-medium transition-all duration-500"
                  style={{
                    width: `${(item.count / 75) * 100}%`,
                    backgroundColor: item.color,
                  }}
                >
                  {item.count}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 30-Day Trend */}
      <div>
        <h3 className="font-semibold text-slate-900 mb-4">30-Day Violation Trend</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={trendData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="day" stroke="#64748b" style={{ fontSize: '12px' }} />
            <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
              }}
            />
            <Line
              type="monotone"
              dataKey="violations"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ fill: '#3b82f6', r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Recent Violations */}
      <div className="lg:col-span-2">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-slate-900">Recent Violations</h3>
          <button className="text-sm text-blue-600 hover:text-blue-700">+ New Analysis →</button>
        </div>
        <div className="bg-slate-50 rounded-lg p-8 text-center">
          <AlertTriangle className="w-12 h-12 text-slate-400 mx-auto mb-3" />
          <p className="text-slate-600">No violations recorded yet.</p>
          <p className="text-sm text-slate-500 mt-1">Upload a site video to start analysis</p>
        </div>
      </div>
    </div>
  );
}

function AnalyticsTab() {
  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg p-6 border border-blue-100">
        <div className="flex items-start gap-4">
          <div className="bg-blue-600 p-3 rounded-lg">
            <TrendingDown className="w-6 h-6 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 mb-2">Violation Trends</h3>
            <p className="text-sm text-slate-700">
              Violations decreased by 12% this month. Keep up the excellent safety protocols.
            </p>
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg border border-slate-200 p-6">
          <h4 className="font-semibold text-slate-900 mb-4">Most Common Violations</h4>
          <div className="space-y-3">
            <ViolationItem title="Missing PPE" count={28} percentage={37} />
            <ViolationItem title="Unsafe ladder use" count={19} percentage={25} />
            <ViolationItem title="Blocked exits" count={15} percentage={20} />
            <ViolationItem title="Improper storage" count={13} percentage={18} />
          </div>
        </div>

        <div className="bg-white rounded-lg border border-slate-200 p-6">
          <h4 className="font-semibold text-slate-900 mb-4">Risk Areas</h4>
          <div className="space-y-3">
            <RiskArea zone="Construction Zone A" risk="High" count={24} />
            <RiskArea zone="Warehouse B" risk="Medium" count={18} />
            <RiskArea zone="Loading Dock" risk="Medium" count={12} />
            <RiskArea zone="Office Area" risk="Low" count={3} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ScansTab() {
  return (
    <div className="text-center py-12">
      <div className="bg-slate-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
        <Eye className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="font-semibold text-slate-900 mb-2">No Scans Yet</h3>
      <p className="text-slate-600 mb-6">Start your first safety analysis to see scan history</p>
      <button className="bg-gradient-to-r from-blue-600 to-indigo-600 text-white px-6 py-3 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200">
        Start New Scan
      </button>
    </div>
  );
}

function CamerasTab() {
  return (
    <div className="text-center py-12">
      <div className="bg-slate-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
        <Camera className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="font-semibold text-slate-900 mb-2">No Cameras Connected</h3>
      <p className="text-slate-600 mb-6">Connect cameras to enable live monitoring</p>
      <button className="bg-gradient-to-r from-blue-600 to-indigo-600 text-white px-6 py-3 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200">
        Add Camera
      </button>
    </div>
  );
}

function AlertsTab() {
  return (
    <div className="text-center py-12">
      <div className="bg-green-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
        <Bell className="w-8 h-8 text-green-600" />
      </div>
      <h3 className="font-semibold text-slate-900 mb-2">No Active Alerts</h3>
      <p className="text-slate-600">All systems operating normally</p>
    </div>
  );
}


function ViolationItem({ title, count, percentage }: any) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-slate-700">{title}</span>
        <span className="text-sm font-medium text-slate-900">{count}</span>
      </div>
      <div className="bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className="bg-gradient-to-r from-blue-500 to-indigo-500 h-full transition-all duration-500"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function RiskArea({ zone, risk, count }: any) {
  const riskColors = {
    High: 'bg-red-100 text-red-700 border-red-200',
    Medium: 'bg-orange-100 text-orange-700 border-orange-200',
    Low: 'bg-green-100 text-green-700 border-green-200',
  };

  return (
    <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
      <div>
        <div className="font-medium text-slate-900">{zone}</div>
        <div className="text-sm text-slate-600">{count} violations</div>
      </div>
      <div className={`px-3 py-1 rounded-full border text-xs font-medium ${riskColors[risk]}`}>
        {risk} Risk
      </div>
    </div>
  );
}
