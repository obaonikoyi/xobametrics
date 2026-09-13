import { useEffect, useState, useCallback } from "react";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { METRIC_OPTIONS } from "@/components/common";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Zap, Flag } from "lucide-react";
import { cn } from "@/lib/utils";

const RANGES = [{ l: "Day 7", v: 7 }, { l: "Day 14", v: 14 }, { l: "Day 30", v: 30 }, { l: "Day 90", v: 90 }, { l: "All", v: 400 }];

export default function ReleaseRace() {
  const { activeProfile } = useWorkspace();
  const [releases, setReleases] = useState([]);
  const [selected, setSelected] = useState([]);
  const [metric, setMetric] = useState("reach");
  const [maxDay, setMaxDay] = useState(30);
  const [race, setRace] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeProfile) return;
    (async () => {
      const { data } = await api.get(`/releases?profile_id=${activeProfile.id}`);
      setReleases(data.releases);
      setSelected(data.releases.slice(0, 4).map((r) => r.id));
    })();
  }, [activeProfile]);

  const loadRace = useCallback(async () => {
    if (!activeProfile || selected.length === 0) { setRace({ releases: [] }); setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await api.get(`/analytics/release-race?profile_id=${activeProfile.id}&release_ids=${selected.join(",")}&metric=${metric}&max_day=${maxDay}`);
      setRace(data);
    } finally { setLoading(false); }
  }, [activeProfile, selected, metric, maxDay]);

  useEffect(() => { loadRace(); }, [loadRace]);

  const toggle = (id) => setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);

  // merge series by day-offset
  const merged = [];
  if (race?.releases?.length) {
    const dayMap = {};
    race.releases.forEach((r) => r.series.forEach((pt) => {
      dayMap[pt.day] = dayMap[pt.day] || { day: pt.day };
      dayMap[pt.day][r.release_id] = pt.value;
    }));
    Object.values(dayMap).sort((a, b) => a.day - b.day).forEach((d) => merged.push(d));
  }
  const colorFor = (id) => race?.releases?.find((r) => r.release_id === id)?.color || "#3B82F6";
  const titleFor = (id) => race?.releases?.find((r) => r.release_id === id)?.title || id;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary"><Zap className="h-5 w-5" /></span>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Release Race</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Every release aligned to its own <span className="font-semibold text-foreground">Day 0</span> (actual publish date) — so yesterday's drop is compared fairly against last year's hit.
        </p>
      </div>

      {/* controls */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <Select value={metric} onValueChange={setMetric}>
          <SelectTrigger className="w-56" data-testid="race-metric-select"><SelectValue /></SelectTrigger>
          <SelectContent>{METRIC_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
        </Select>
        <div className="flex gap-1 rounded-lg border border-border p-1">
          {RANGES.map((r) => (
            <button key={r.v} data-testid={`race-range-${r.v}`} onClick={() => setMaxDay(r.v)}
              className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors", maxDay === r.v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
              {r.l}
            </button>
          ))}
        </div>
      </div>

      {/* release selector */}
      <div className="flex flex-wrap gap-2">
        {releases.map((r) => {
          const on = selected.includes(r.id);
          return (
            <button key={r.id} data-testid={`race-toggle-${r.id}`} onClick={() => toggle(r.id)}
              className={cn("flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-all", on ? "border-transparent text-white" : "border-border text-muted-foreground hover:text-foreground")}
              style={on ? { background: colorFor(r.id) } : {}}>
              <span className="h-2 w-2 rounded-full" style={{ background: on ? "#fff" : r.cover }} />
              {r.title}
            </button>
          );
        })}
      </div>

      {/* chart */}
      <div className="rounded-xl border border-border bg-card p-5" data-testid="release-race-chart">
        {loading ? <Skeleton className="h-96 rounded-lg" /> : merged.length === 0 ? (
          <div className="flex h-96 flex-col items-center justify-center text-muted-foreground">
            <Flag className="h-8 w-8" /><p className="mt-2 text-sm">Select at least one release to start the race.</p>
          </div>
        ) : (
          <div className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged} margin={{ left: 6, right: 12, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis dataKey="day" type="number" stroke="hsl(var(--muted-foreground))" fontSize={11}
                  label={{ value: "Days since release (Day 0)", position: "insideBottom", offset: -4, fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickFormatter={compactNumber} width={46} />
                <Tooltip formatter={(v, n) => [fullNumber(v), titleFor(n)]} labelFormatter={(d) => `Day ${d}`}
                  contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 12 }} />
                <Legend formatter={(v) => titleFor(v)} wrapperStyle={{ fontSize: 12 }} />
                {selected.map((id) => (
                  <Line key={id} type="monotone" dataKey={id} name={id} stroke={colorFor(id)} strokeWidth={2.5} dot={false} connectNulls activeDot={{ r: 4 }} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
