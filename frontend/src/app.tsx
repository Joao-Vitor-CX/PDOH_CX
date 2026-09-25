import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/platform/app-shell';
import { AuthProvider, useAuth } from '@/src/auth/auth-provider';
import { LoginPage } from '@/src/pages/login-page';
import { PdohDashboardPage } from '@/src/pages/pdoh-dashboard-page';
import { AnalysisPage } from '@/src/pages/analysis-page';
import { ImpactPage, PreviousConsultationPage } from '@/src/pages/impact-page';
import { GovernancePage } from '@/src/pages/admin-pages';
import { SettingsPage } from '@/src/pages/settings-page';

function ProtectedApp() {
  const { user, loading, signOut } = useAuth();
  if (loading) return <div className="grid min-h-screen place-items-center bg-slate-950 text-sm text-blue-100">Carregando sessão…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <AppShell user={user} onSignOut={signOut}>
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<PdohDashboardPage />} />
      <Route path="/analise" element={<AnalysisPage />} />
      <Route path="/impactadores" element={<ImpactPage />} />
      <Route path="/configuracoes" element={<SettingsPage />} />
      <Route path="/governanca" element={<GovernancePage />} />
      {/* Rotas da consulta anterior continuam explicadas, sem quebrar links salvos. */}
      <Route path="/oportunidades" element={<Navigate to="/impactadores" replace />} />
      <Route path="/oportunidades/*" element={<PreviousConsultationPage />} />
      <Route path="/processamentos/*" element={<PreviousConsultationPage />} />
      <Route path="/operacoes" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  </AppShell>;
}

function ApplicationRoutes() {
  const { user } = useAuth();
  return <Routes>
    <Route path="/login" element={user ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
    <Route path="*" element={<ProtectedApp />} />
  </Routes>;
}

export function CxPdohApp() {
  const basePath = (import.meta.env.VITE_CX_PDOH_BASE_PATH as string | undefined) || '/';
  return <BrowserRouter basename={basePath}><AuthProvider><ApplicationRoutes /></AuthProvider></BrowserRouter>;
}
