import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { useAi } from "@/context/AiContext";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sparkles, Send, ShieldCheck, Bot, User } from "lucide-react";

// Starter questions for someone who doesn't know what to ask yet. Each one
// is answerable from the facts the backend hands the AI.
const SUGGESTIONS = [
  "How is my latest release doing compared with my others?",
  "Which release had the strongest first week?",
  "Which platform brings me the most reach?",
  "Write my weekly report: key numbers, what changed, 3 actions.",
  "What should I focus on to grow next month?",
];

function SuggestionChip({ text, onClick, testId }) {
  return (
    <button type="button" data-testid={testId} onClick={onClick}
      className="rounded-full border border-border bg-secondary/50 px-3 py-1.5 text-left text-xs font-medium transition-colors hover:border-primary/40 hover:text-primary">
      {text}
    </button>
  );
}

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
      setMessages((m) => [...m, { role: "ai", text: data.answer, grounded: data.grounded, followUps: data.follow_ups || [] }]);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setMessages((m) => [...m, {
        role: "ai",
        text: typeof detail === "string" ? detail : "I couldn't compute that right now. Please try again.",
        grounded: false,
      }]);
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
                  <SuggestionChip key={s} text={s} onClick={() => ask(s)} testId="ai-suggestion-chip" />
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-2.5 ${m.role === "user" ? "flex-row-reverse" : ""}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${m.role === "user" ? "bg-secondary" : "bg-primary/15 text-primary"}`}>
                {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </span>
              <div className="max-w-[80%] space-y-2">
                <div className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm ${m.role === "user" ? "bg-primary text-primary-foreground" : "border border-border bg-card"}`}>
                  {m.text}
                </div>
                {i === messages.length - 1 && !busy && m.followUps?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.followUps.map((q) => (
                      <SuggestionChip key={q} text={q} onClick={() => ask(q)} testId="ai-follow-up-chip" />
                    ))}
                  </div>
                )}
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
