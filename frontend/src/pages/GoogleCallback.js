import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { googleErrorMessage, takeGoogleBrowserKey } from "@/lib/googleSignIn";
import { Button } from "@/components/ui/button";
import { Activity } from "lucide-react";

export default function GoogleCallback() {
  const navigate = useNavigate();
  const { user, setSession, checkAuth } = useAuth();
  const [error, setError] = useState("");
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const params = new URLSearchParams(window.location.hash.slice(1));
    window.history.replaceState(null, "", window.location.pathname);
    const code = params.get("code");
    const browserKey = takeGoogleBrowserKey();
    if (!code) {
      setError(googleErrorMessage(params.get("error")));
      return;
    }
    if (!browserKey) {
      setError("This sign-in was started in a different browser tab. Please try again from this tab.");
      checkAuth();
      return;
    }
    (async () => {
      try {
        const { data } = await api.post("/auth/google/exchange", { code, browser_key: browserKey });
        setSession(data);
        if (data.mode === "link") toast.success("Google sign-in connected to your account.");
        navigate("/dashboard", { replace: true });
      } catch (err) {
        setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
        checkAuth();
      }
    })();
  }, [navigate, setSession, checkAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      {error ? (
        <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 text-center" data-testid="google-signin-error">
          <Activity className="mx-auto mb-4 h-8 w-8 text-primary" />
          <h1 className="font-display text-xl font-bold">Google sign-in didn't finish</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          <Button asChild className="mt-6 w-full">
            <Link to={user ? "/dashboard" : "/login"}>{user ? "Back to dashboard" : "Back to sign in"}</Link>
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <Activity className="h-8 w-8 animate-pulse text-primary" />
          <p className="text-sm">Signing you in…</p>
        </div>
      )}
    </div>
  );
}
