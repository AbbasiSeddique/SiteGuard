import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import { Navigation } from './components/Navigation';
import { HomePage } from './components/HomePage';
import { InspectPage } from './components/InspectPage';
import { DashboardPage } from './components/DashboardPage';
import { ReportsPage } from './components/ReportsPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/inspect" element={<InspectPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
