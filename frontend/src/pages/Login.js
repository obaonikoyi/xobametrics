import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { googleSignInConfigured, startGoogleSignIn } from "@/lib/googleSignIn";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Activity, TrendingUp, Radio, Sparkles } from "lucide-react";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { setSession } = useAuth();
  const navigate = useNavigate();
  const [googleAvailable, setGoogleAvailable] = useState(false);

  useEffect(() => {
    googleSignInConfigured().then(setGoogleAvailable);
  }, []);

  const google = async () => {
    setBusy(true);
    setError("");
    try {
      await startGoogleSignIn("signin");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
      setBusy(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const body = mode === "login" ? { email, password } : { email, password, name };
      const { data } = await api.post(path, body);
      setSession(data);
      navigate("/dashboard");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="xoba-grid-bg flex min-h-screen w-full items-center justify-center bg-background p-4">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl lg:grid-cols-2">
        {/* Left brand panel */}
        <div className="relative hidden flex-col justify-between bg-gradient-to-br from-primary/90 to-blue-700 p-10 text-white lg:flex">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/15">
              <Activity className="h-5 w-5" />
            </div>
            <span className="font-display text-xl font-bold">XobaMetrics</span>
          </div>
          <div>
            <h1 className="font-display text-4xl font-extrabold leading-tight">Your numbers.<br />Your story.<br />Fairly compared.</h1>
            <p className="mt-4 max-w-sm text-sm text-white/80">
              Import your music &amp; content metrics, snapshot them over time, and race every release on a Day-0 timeline — then ask AI grounded in your real data.
            </p>
            <div className="mt-8 space-y-3">
              {[[TrendingUp, "Auto-charted cross-platform performance"], [Radio, "Release Race — Day-0 aligned"], [Sparkles, "AI that never invents numbers"]].map(([Icon, t], i) => (
                <div key={i} className="flex items-center gap-3 text-sm text-white/90">
                  <Icon className="h-4 w-4" /> {t}
                </div>
              ))}
            </div>
          </div>
          <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold">Private Beta</span>
        </div>

        {/* Right form */}
        <div className="p-8 sm:p-10">
          <div className="mb-6 flex items-center gap-2 lg:hidden">
            <Activity className="h-6 w-6 text-primary" />
            <span className="font-display text-lg font-bold">XobaMetrics</span>
          </div>
          <h2 className="font-display text-2xl font-bold">{mode === "login" ? "Welcome back" : "Create your account"}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{mode === "login" ? "Sign in to your creator dashboard." : "Join the private beta and start tracking."}</p>

          <motion.form key={mode} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} onSubmit={submit} className="mt-6 space-y-4">
            {mode === "register" && (
              <div>
                <Label htmlFor="name">Name</Label>
                <Input id="name" data-testid="auth-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Luna Eclipse" required className="mt-1.5" />
              </div>
            )}
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" data-testid="auth-email-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@studio.com" required className="mt-1.5" />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" data-testid="auth-password-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required className="mt-1.5" />
            </div>
            {error && <p data-testid="auth-error" className="text-sm text-destructive">{error}</p>}
            <Button type="submit" data-testid="auth-submit-button" disabled={busy} className="w-full">
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </motion.form>

          {googleAvailable && (
            <>
              <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
                <div className="h-px flex-1 bg-border" /> or <div className="h-px flex-1 bg-border" />
              </div>
              <Button variant="outline" data-testid="google-login-button" onClick={google} disabled={busy} className="w-full gap-2">
                <GoogleMark /> Continue with Google
              </Button>
            </>
          )}

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {mode === "login" ? "New to XobaMetrics?" : "Already have an account?"}{" "}
            <button data-testid="auth-toggle-mode" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }} className="font-semibold text-primary hover:underline">
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="h-4 w-4" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}
