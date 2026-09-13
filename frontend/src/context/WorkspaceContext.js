import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const WorkspaceContext = createContext(null);

export function WorkspaceProvider({ children }) {
  const { user } = useAuth();
  const [workspaces, setWorkspaces] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [activeProfile, setActiveProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/workspaces");
      const ws = data.workspaces || [];
      setWorkspaces(ws);
      const allProfiles = ws.flatMap((w) => (w.profiles || []).map((p) => ({ ...p, workspace_name: w.name, workspace_type: w.type })));
      setProfiles(allProfiles);
      const savedId = localStorage.getItem("xoba_active_profile");
      const found = allProfiles.find((p) => p.id === savedId) || allProfiles[0] || null;
      setActiveProfile(found);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const selectProfile = useCallback((profile) => {
    setActiveProfile(profile);
    if (profile) localStorage.setItem("xoba_active_profile", profile.id);
  }, []);

  return (
    <WorkspaceContext.Provider value={{ workspaces, profiles, activeProfile, selectProfile, loading, reload: load }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export const useWorkspace = () => useContext(WorkspaceContext);
