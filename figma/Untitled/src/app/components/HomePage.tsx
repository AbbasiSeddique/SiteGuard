import { Shield, ScanEye, BarChart3, FileCheck, ArrowRight } from 'lucide-react';
import { Link } from 'react-router';

export function HomePage() {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* Hero Section */}
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 bg-blue-100 text-blue-700 px-4 py-2 rounded-full mb-6">
          <Shield className="w-4 h-4" />
          <span className="text-sm">Workplace Safety Analysis</span>
        </div>

        <h1 className="text-5xl font-bold text-slate-900 mb-6 bg-gradient-to-r from-slate-900 via-blue-900 to-indigo-900 bg-clip-text text-transparent">
          Protect Your Workforce with
          <br />
          Intelligent Safety Analysis
        </h1>

        <p className="text-xl text-slate-600 max-w-3xl mx-auto mb-8">
          Real-time vision analysis to detect safety violations, ensure OSHA compliance,
          and generate comprehensive HSE reports automatically.
        </p>

        <div className="flex items-center justify-center gap-4">
          <Link
            to="/inspect"
            className="flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white px-6 py-3 rounded-xl hover:shadow-xl hover:shadow-blue-500/30 transition-all duration-200"
          >
            Start Analysis
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/dashboard"
            className="flex items-center gap-2 bg-white text-slate-700 px-6 py-3 rounded-xl border border-slate-200 hover:border-slate-300 hover:shadow-lg transition-all duration-200"
          >
            View Dashboard
          </Link>
        </div>
      </div>

      {/* Features Grid */}
      <div className="grid md:grid-cols-3 gap-6">
        <FeatureCard
          icon={ScanEye}
          title="Vision Analysis"
          description="Upload site videos for automated violation detection with timestamped evidence."
          color="blue"
        />
        <FeatureCard
          icon={BarChart3}
          title="Live Dashboard"
          description="Real-time compliance monitoring with violation trends and severity analytics."
          color="indigo"
        />
        <FeatureCard
          icon={FileCheck}
          title="HSE Reports"
          description="Automated OSHA & NEBOSH compliance reports with evidence-backed findings."
          color="purple"
        />
      </div>
    </div>
  );
}

function FeatureCard({ icon: Icon, title, description, color }: any) {
  const colorClasses = {
    blue: 'from-blue-500 to-blue-600 shadow-blue-500/20',
    indigo: 'from-indigo-500 to-indigo-600 shadow-indigo-500/20',
    purple: 'from-purple-500 to-purple-600 shadow-purple-500/20',
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6 hover:shadow-lg transition-all duration-200">
      <div className={`bg-gradient-to-br ${colorClasses[color]} w-9 h-9 rounded-xl flex items-center justify-center mb-4 shadow-lg`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
      <p className="text-sm text-slate-600">{description}</p>
    </div>
  );
}

