import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import "@/App.css";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { AiProvider } from "@/context/AiContext";
import { Toaster } from "@/components/ui/sonner";
import { BACKEND_CONFIG_ERROR } from "@/lib/api";
import AppShell from "@/components/AppShell";
import AiPanel from "@/components/AiPanel";
import Login from "@/pages/Login";
import GoogleCallback from "@/pages/GoogleCallback";
import Dashboard from "@/pages/Dashboard";
import Releases from "@/pages/Releases";
import ReleaseDetail from "@/pages/ReleaseDetail";
import ReleaseRace from "@/pages/ReleaseRace";
import Connections from "@/pages/Connections";
import Reports from "@/pages/Reports";
import SharedReport from "@/pages/SharedReport";
import { Activity } from "lucide-react";

function Protected() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Activity className="h-8 w-8 animate-pulse text-primary" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return (
    <WorkspaceProvider>
      <AiProvider>
        <AppShell><Outlet /></AppShell>
        <AiPanel />
      </AiProvider>
    </WorkspaceProvider>
  );
}

function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/auth/google" element={<GoogleCallback />} />
      <Route path="/share/:shareId" element={<SharedReport />} />
      <Route element={<Protected />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/releases" element={<Releases />} />
        <Route path="/releases/:id" element={<ReleaseDetail />} />
        <Route path="/race" element={<ReleaseRace />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/reports" element={<Reports />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  if (BACKEND_CONFIG_ERROR) {
    return (
      <ThemeProvider>
        <main className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground" data-testid="backend-setup-required">
          <section className="w-full max-w-xl rounded-2xl border border-border bg-card p-8">
            <Activity className="mb-4 h-8 w-8 text-primary" aria-hidden="true" />
            <h1 className="mb-3 text-2xl font-semibold">XobaMetrics</h1>
            <h2 className="mb-3 text-lg font-medium">Backend setup required</h2>
            <p className="mb-4 text-muted-foreground">{BACKEND_CONFIG_ERROR} Sign-in and analytics are unavailable until setup is complete.</p>
            <p className="text-sm text-muted-foreground">Site owner: set <code>REACT_APP_BACKEND_URL</code> to the deployed API origin in Vercel Environment Variables, then redeploy. Do not enter database passwords or API keys in frontend variables.</p>
          </section>
        </main>
      </ThemeProvider>
    );
  }
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRouter />
          <Toaster position="top-right" richColors />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
