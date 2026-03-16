import { useState } from 'react';
import { Upload, FileText, Download, Calendar, Building, CheckCircle2, AlertTriangle, User } from 'lucide-react';

export function ReportsPage() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [reportGenerated, setReportGenerated] = useState(false);

  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setVideoFile(file);
    }
  };

  const handleGenerateReport = () => {
    if (!videoFile) return;
    setIsGenerating(true);
    setTimeout(() => {
      setIsGenerating(false);
      setReportGenerated(true);
    }, 3000);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">HSE Compliance Reports</h1>
        <p className="text-slate-600">
          Generate evidence-backed OSHA & NEBOSH compliance reports from site recordings
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Upload Panel */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm mb-6">
            <h2 className="font-semibold text-slate-900 mb-6">Upload Site Recording</h2>

            {!videoFile ? (
              <label className="border-2 border-dashed border-slate-300 rounded-xl p-12 flex flex-col items-center justify-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/50 transition-all duration-200">
                <input
                  type="file"
                  accept="video/*"
                  onChange={handleVideoUpload}
                  className="hidden"
                />
                <div className="bg-gradient-to-br from-blue-500 to-indigo-600 w-16 h-16 rounded-full flex items-center justify-center mb-4">
                  <Upload className="w-8 h-8 text-white" />
                </div>
                <div className="text-slate-900 font-medium mb-2">Click or drag to select a site recording</div>
                <div className="text-sm text-slate-500">MP4 · MOV · AVI · up to 500 MB</div>
              </label>
            ) : (
              <div>
                <div className="bg-slate-50 rounded-lg p-6 mb-4">
                  <div className="flex items-start gap-4">
                    <div className="bg-blue-100 p-3 rounded-lg">
                      <FileText className="w-6 h-6 text-blue-600" />
                    </div>
                    <div className="flex-1">
                      <div className="font-medium text-slate-900 mb-1">{videoFile.name}</div>
                      <div className="text-sm text-slate-600">{(videoFile.size / 1024 / 1024).toFixed(2)} MB</div>
                    </div>
                    <button
                      onClick={() => {
                        setVideoFile(null);
                        setReportGenerated(false);
                      }}
                      className="text-sm text-slate-600 hover:text-slate-900"
                    >
                      Remove
                    </button>
                  </div>
                </div>

                {isGenerating ? (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="animate-spin rounded-full h-5 w-5 border-2 border-blue-600 border-t-transparent" />
                      <span className="font-medium text-blue-900">Generating Compliance Report...</span>
                    </div>
                    <div className="space-y-2 text-sm text-blue-800">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4" />
                        Analyzing video footage
                      </div>
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4" />
                        Detecting safety violations
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-600 border-t-transparent" />
                        Mapping to OSHA standards
                      </div>
                    </div>
                  </div>
                ) : !reportGenerated ? (
                  <button
                    onClick={handleGenerateReport}
                    className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 text-white py-4 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200 flex items-center justify-center gap-2"
                  >
                    <FileText className="w-5 h-5" />
                    Generate Compliance Report
                  </button>
                ) : (
                  <div className="space-y-4">
                    <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-center gap-3">
                      <CheckCircle2 className="w-5 h-5 text-green-600" />
                      <span className="text-green-900 font-medium">Report generated successfully!</span>
                    </div>
                    <button className="w-full bg-gradient-to-r from-green-600 to-emerald-600 text-white py-4 rounded-lg hover:shadow-lg hover:shadow-green-500/30 transition-all duration-200 flex items-center justify-center gap-2">
                      <Download className="w-5 h-5" />
                      Download PDF Report
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Report Preview */}
          {reportGenerated && (
            <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
              <h3 className="font-semibold text-slate-900 mb-6">Report Preview</h3>

              <div className="space-y-6">
                <ReportSection
                  title="Executive Summary"
                  content="Site inspection conducted on March 16, 2026. Analysis identified 3 safety violations requiring immediate attention. Overall compliance score: 87%."
                />

                <ReportSection
                  title="Critical Findings"
                  content={
                    <div className="space-y-3">
                      <Finding
                        severity="critical"
                        title="Missing Hard Hat - Zone A"
                        standard="OSHA 1926.100(a)"
                        timestamp="00:45"
                        description="Worker observed without required head protection in construction zone."
                      />
                      <Finding
                        severity="high"
                        title="Improper Ladder Placement"
                        standard="OSHA 1926.1053"
                        timestamp="01:23"
                        description="Ladder not secured at proper angle, creating fall hazard."
                      />
                      <Finding
                        severity="medium"
                        title="Blocked Emergency Exit"
                        standard="OSHA 1910.36"
                        timestamp="02:15"
                        description="Exit route obstructed by equipment storage."
                      />
                    </div>
                  }
                />

                <ReportSection
                  title="Recommendations"
                  content={
                    <ul className="list-disc list-inside space-y-2 text-sm text-slate-700">
                      <li>Implement mandatory PPE checks before zone entry</li>
                      <li>Conduct ladder safety training for all personnel</li>
                      <li>Establish clear exit route maintenance protocol</li>
                      <li>Schedule follow-up inspection within 14 days</li>
                    </ul>
                  }
                />
              </div>
            </div>
          )}
        </div>

        {/* Info Panel */}
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">Report Details</h3>
            <div className="space-y-3">
              <DetailItem icon={Calendar} label="Date" value="March 16, 2026" />
              <DetailItem icon={Building} label="Standard" value="OSHA & NEBOSH" />
              <DetailItem icon={FileText} label="Format" value="PDF Report" />
              <DetailItem icon={User} label="Inspector" value="Vision Analysis" />
            </div>
          </div>

          <div className="bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100 p-6">
            <h3 className="font-semibold text-slate-900 mb-3">What's Included</h3>
            <ul className="space-y-2 text-sm text-slate-700">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                <span>Complete violation analysis</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                <span>OSHA standard references</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                <span>Timestamped evidence</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                <span>Compliance recommendations</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
                <span>Action items & timeline</span>
              </li>
            </ul>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="font-medium text-amber-900 mb-1">Report Accuracy</h4>
                <p className="text-sm text-amber-800">
                  Auto-generated reports should be reviewed by a qualified safety professional before submission.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReportSection({ title, content }: any) {
  return (
    <div>
      <h4 className="font-semibold text-slate-900 mb-3">{title}</h4>
      <div className="text-sm text-slate-700">{content}</div>
    </div>
  );
}

function Finding({ severity, title, standard, timestamp, description }: any) {
  const severityColors = {
    critical: 'bg-red-100 text-red-700 border-red-200',
    high: 'bg-orange-100 text-orange-700 border-orange-200',
    medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  };

  return (
    <div className="bg-slate-50 rounded-lg p-4">
      <div className="flex items-start gap-3 mb-2">
        <div className={`px-2 py-1 rounded border text-xs font-medium uppercase ${severityColors[severity]}`}>
          {severity}
        </div>
        <div className="flex-1">
          <div className="font-medium text-slate-900">{title}</div>
          <div className="text-xs text-slate-600 mt-1">
            {standard} · Timestamp: {timestamp}
          </div>
        </div>
      </div>
      <p className="text-sm text-slate-700 ml-0">{description}</p>
    </div>
  );
}

function DetailItem({ icon: Icon, label, value }: any) {
  return (
    <div className="flex items-center gap-3">
      <div className="bg-slate-100 p-2 rounded-lg">
        <Icon className="w-4 h-4 text-slate-600" />
      </div>
      <div>
        <div className="text-xs text-slate-600">{label}</div>
        <div className="text-sm text-slate-900">{value}</div>
      </div>
    </div>
  );
}
