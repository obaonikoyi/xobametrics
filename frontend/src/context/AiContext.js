import { createContext, useContext, useState, useCallback } from "react";

const AiContext = createContext(null);

export function AiProvider({ children }) {
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("");

  const openWith = useCallback((question = "") => {
    setPreset(question);
    setOpen(true);
  }, []);

  return (
    <AiContext.Provider value={{ open, setOpen, preset, setPreset, openWith }}>
      {children}
    </AiContext.Provider>
  );
}

export const useAi = () => useContext(AiContext);
