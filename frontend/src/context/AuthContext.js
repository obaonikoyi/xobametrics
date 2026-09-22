import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { isGoogleLanding } from "@/lib/googleSignIn";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    } finally {
      setLoading(false);
    }
  }, []);

  // Read during the first render: GoogleCallback's effect runs before this
  // provider's and clears the hash, so checking inside the effect is too late.
  const [googleLanding] = useState(isGoogleLanding);

  useEffect(() => {
    // Returning from Google with a login code: GoogleCallback sets the session,
    // and a concurrent /me could otherwise resolve after it and sign out.
    if (googleLanding) {
      setLoading(false);
      return;
    }
    checkAuth();
  }, [checkAuth, googleLanding]);

  const setSession = useCallback((data) => {
    if (data?.token) localStorage.setItem("xoba_token", data.token);
    setUser(data.user);
    setLoading(false);
  }, []);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch {}
    localStorage.removeItem("xoba_token");
    setUser(false);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, setSession, logout, checkAuth, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
