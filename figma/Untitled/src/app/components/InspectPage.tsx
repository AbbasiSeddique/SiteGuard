import { useState } from 'react';
import { Upload, Video, Send, Sparkles, Play, CheckCircle2 } from 'lucide-react';

export function InspectPage() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setVideoFile(file);
    }
  };

  const handleAnalyze = () => {
    if (!videoFile) return;
    setIsAnalyzing(true);
    setTimeout(() => {
      setIsAnalyzing(false);
      setChatMessages([
        {
          role: 'assistant',
          content: '✅ Analysis complete! I detected 3 safety violations:\n\n1. **Critical**: Missing hard hat in Zone A (00:45)\n2. **High**: Improper ladder placement (01:23)\n3. **Medium**: Blocked emergency exit (02:15)\n\nWould you like details on any specific violation?'
        }
      ]);
    }, 2000);
  };

  const handleSendMessage = () => {
    if (!inputMessage.trim()) return;

    setChatMessages([
      ...chatMessages,
      { role: 'user', content: inputMessage },
      {
        role: 'assistant',
        content: 'Based on OSHA standards 1926.100(a), all employees working in areas where there is a possible danger of head injury must wear protective helmets. The violation at 00:45 shows a worker in the construction zone without proper head protection.'
      }
    ]);
    setInputMessage('');
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Safety Inspection</h1>
        <p className="text-slate-600">Upload site videos for automated analysis and consult ARIA intelligence</p>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 h-[calc(100vh-16rem)]">
        {/* Vision Analysis Panel */}
        <div className="bg-white rounded-xl border border-slate-200 p-6 flex flex-col shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <div className="bg-gradient-to-br from-blue-500 to-blue-600 p-2 rounded-lg">
              <Video className="w-5 h-5 text-white" />
            </div>
            <h2 className="font-semibold text-slate-900">Vision Analysis</h2>
          </div>

          <div className="flex-1 flex flex-col">
            {!videoFile ? (
              <label className="flex-1 border-2 border-dashed border-slate-300 rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/50 transition-all duration-200">
                <input
                  type="file"
                  accept="video/*"
                  onChange={handleVideoUpload}
                  className="hidden"
                />
                <Upload className="w-12 h-12 text-slate-400 mb-4" />
                <div className="text-slate-900 font-medium mb-2">Upload Site Video</div>
                <div className="text-sm text-slate-500">MP4, MOV, AVI • Up to 500 MB</div>
              </label>
            ) : (
              <div className="flex-1 flex flex-col">
                <div className="bg-slate-900 rounded-lg flex-1 flex items-center justify-center mb-4 relative overflow-hidden">
                  <Play className="w-16 h-16 text-white/80" />
                  <div className="absolute bottom-4 left-4 bg-black/70 text-white px-3 py-1 rounded text-sm">
                    {videoFile.name}
                  </div>
                </div>

                {isAnalyzing ? (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
                    <div className="animate-spin rounded-full h-5 w-5 border-2 border-blue-600 border-t-transparent" />
                    <span className="text-blue-900">Analyzing video for safety violations...</span>
                  </div>
                ) : chatMessages.length === 0 ? (
                  <button
                    onClick={handleAnalyze}
                    className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 text-white py-3 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200 flex items-center justify-center gap-2"
                  >
                    <Sparkles className="w-4 h-4" />
                    Run Vision Analysis
                  </button>
                ) : (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-center gap-3">
                    <CheckCircle2 className="w-5 h-5 text-green-600" />
                    <span className="text-green-900">Analysis complete. View results in ARIA →</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ARIA Intelligence Panel */}
        <div className="bg-white rounded-xl border border-slate-200 p-6 flex flex-col shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <div className="bg-gradient-to-br from-indigo-500 to-purple-600 p-2 rounded-lg">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <h2 className="font-semibold text-slate-900">ARIA Intelligence</h2>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto mb-4 space-y-4">
              {chatMessages.length === 0 ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center max-w-md">
                    <div className="bg-gradient-to-br from-indigo-100 to-purple-100 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                      <Sparkles className="w-8 h-8 text-indigo-600" />
                    </div>
                    <h3 className="font-semibold text-slate-900 mb-2">ARIA Ready to Assist</h3>
                    <p className="text-sm text-slate-600">
                      Ask about site safety, violations, or OSHA standards.
                      <br />
                      Run Vision Analysis first for evidence-based insights.
                    </p>
                  </div>
                </div>
              ) : (
                chatMessages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg p-4 ${
                        msg.role === 'user'
                          ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white'
                          : 'bg-slate-100 text-slate-900'
                      }`}
                    >
                      <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="flex gap-2">
              <input
                type="text"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="Ask about safety violations, OSHA standards..."
                className="flex-1 px-4 py-3 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                onClick={handleSendMessage}
                disabled={!inputMessage.trim()}
                className="bg-gradient-to-r from-blue-600 to-indigo-600 text-white px-6 py-3 rounded-lg hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
