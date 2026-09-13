import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from "react-router-dom";
import "@/App.css";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { AiProvider } from "@/context/AiContext";
import { Toaster } from "@/components/ui/sonner";
import AppShell from "@/components/AppShell";
import AiPanel from "@/components/AiPanel";
import Login from "@/pages/Login";
import AuthCallback from "@/pages/AuthCallback";
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
  const location = useLocation();
  if (location.hash?.includes("session_id=")) return <AuthCallback />;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
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
