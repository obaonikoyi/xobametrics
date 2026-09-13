import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Activity } from "lucide-react";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const hash = window.location.hash || "";
    const match = hash.match(/session_id=([^&]+)/);
    const sessionId = match ? match[1] : null;
    window.history.replaceState(null, "", window.location.pathname);
    if (!sessionId) {
      navigate("/login");
      return;
    }
    (async () => {
      try {
        const { data } = await api.post("/auth/session", { session_id: sessionId });
        setSession(data);
        navigate("/dashboard");
      } catch {
        navigate("/login");
      }
    })();
  }, [navigate, setSession]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Activity className="h-8 w-8 animate-pulse text-primary" />
        <p className="text-sm">Signing you in…</p>
      </div>
    </div>
  );
}
