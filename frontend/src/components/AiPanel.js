import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { useAi } from "@/context/AiContext";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sparkles, Send, ShieldCheck, Bot, User } from "lucide-react";

const SUGGESTIONS = [
  "Which release had the strongest first week?",
  "Compare reach across my platforms.",
  "What should I focus on to grow next month?",
  "How is Neon Rain trending so far?",
];

export default function AiPanel() {
  const { open, setOpen, preset, setPreset } = useAi();
  const { activeProfile } = useWorkspace();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (open && preset) {
      setInput(preset);
      setPreset("");
    }
  }, [open, preset, setPreset]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, busy]);

  const ask = async (question) => {
    if (!question.trim() || !activeProfile || busy) return;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    setBusy(true);
    try {
      const { data } = await api.post("/ai/ask", { profile_id: activeProfile.id, question });
      setMessages((m) => [...m, { role: "ai", text: data.answer, grounded: data.grounded }]);
    } catch {
      setMessages((m) => [...m, { role: "ai", text: "I couldn't compute that right now. Please try again.", grounded: false }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md" data-testid="ai-panel">
        <SheetHeader className="border-b border-border p-5">
          <SheetTitle className="flex items-center gap-2 font-display">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 text-primary"><Sparkles className="h-4 w-4" /></span>
            Ask Xoba AI
          </SheetTitle>
          <SheetDescription className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" /> Grounded in your computed numbers — never invented.
          </SheetDescription>
        </SheetHeader>

        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
          {messages.length === 0 && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Ask anything about {activeProfile?.name || "your"} data:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} data-testid="ai-suggestion-chip" onClick={() => ask(s)}
                    className="rounded-full border border-border bg-secondary/50 px-3 py-1.5 text-xs font-medium transition-colors hover:border-primary/40 hover:text-primary">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-2.5 ${m.role === "user" ? "flex-row-reverse" : ""}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${m.role === "user" ? "bg-secondary" : "bg-primary/15 text-primary"}`}>
                {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </span>
              <div className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm ${m.role === "user" ? "bg-primary text-primary-foreground" : "border border-border bg-card"}`}>
                {m.text}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Bot className="h-4 w-4 animate-pulse text-primary" /> Computing from your data…
            </div>
          )}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="flex items-center gap-2 border-t border-border p-4">
          <Input data-testid="ai-chat-input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your metrics…" />
          <Button type="submit" size="icon" data-testid="ai-send-button" disabled={busy}><Send className="h-4 w-4" /></Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}
