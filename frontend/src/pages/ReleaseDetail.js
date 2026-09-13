import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { useAi } from "@/context/AiContext";
import { PlatformBadge, Freshness, METRIC_OPTIONS } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { ArrowLeft, Sparkles, Disc3 } from "lucide-react";

export default function ReleaseDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { openWith } = useAi();
  const [data, setData] = useState(null);
  const [metric, setMetric] = useState("reach");
  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadRelease = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get(`/releases/${id}`); setData(data); }
    finally { setLoading(false); }
  }, [id]);

  const loadSeries = useCallback(async () => {
    const { data } = await api.get(`/analytics/release-timeseries/${id}?metric=${metric}`);
    setSeries(data.series);
  }, [id, metric]);

  useEffect(() => { loadRelease(); }, [loadRelease]);
  useEffect(() => { loadSeries(); }, [loadSeries]);

  if (loading || !data) return <div className="space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-72 rounded-xl" /></div>;

  const { release, rollup, content } = data;
  const t = rollup.totals;
  const stats = [["Reach", t.reach], ["Views", t.views], ["Plays", t.plays], ["Engagement", t.engagement]];

  return (
    <div className="space-y-6">
      <button onClick={() => navigate("/releases")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Releases</button>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl text-white" style={{ background: release.cover || "#3B82F6" }}><Disc3 className="h-7 w-7" /></div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{release.title}</h1>
            <p className="text-sm text-muted-foreground">Day 0 · {release.release_date} · {rollup.content_count} content items</p>
          </div>
        </div>
        <Button variant="outline" className="gap-2" data-testid="release-ask-ai" onClick={() => openWith(`How is "${release.title}" performing and what stands out?`)}>
          <Sparkles className="h-4 w-4 text-primary" /> Ask AI about this
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map(([label, val]) => (
          <div key={label} className="rounded-xl border border-border bg-card p-4">
            <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</div>
            <div className="mt-1.5 font-mono-metric text-2xl font-bold">{compactNumber(val)}</div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="font-display text-lg font-semibold">Campaign trajectory</h3><Freshness date={rollup.last_synced} className="mt-1" /></div>
          <Select value={metric} onValueChange={setMetric}>
            <SelectTrigger className="w-52" data-testid="detail-metric-select"><SelectValue /></SelectTrigger>
            <SelectContent>{METRIC_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="mt-4 h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ left: 4, right: 8 }}>
              <defs><linearGradient id="detailFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3B82F6" stopOpacity={0.4} /><stop offset="100%" stopColor="#3B82F6" stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={11} tickFormatter={(d) => String(d).slice(5)} minTickGap={30} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickFormatter={compactNumber} width={44} />
              <Tooltip formatter={(v) => fullNumber(v)} contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 12 }} />
              <Area type="monotone" dataKey="value" stroke="#3B82F6" strokeWidth={2.5} fill="url(#detailFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-5 py-3 font-display text-lg font-semibold">Content items</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="px-5 py-2.5 text-left font-semibold">Content</th>
              <th className="px-3 py-2.5 text-left font-semibold">Platform</th>
              <th className="px-3 py-2.5 text-right font-semibold">Reach</th>
              <th className="px-3 py-2.5 text-right font-semibold">Engagement</th>
              <th className="px-5 py-2.5 text-right font-semibold">Synced</th>
            </tr></thead>
            <tbody>
              {content.map((c) => (
                <tr key={c.id} data-testid={`content-row-${c.id}`} className="border-t border-border">
                  <td className="px-5 py-3 font-medium">{c.title}</td>
                  <td className="px-3 py-3"><PlatformBadge platform={c.platform} /></td>
                  <td className="px-3 py-3 text-right font-mono-metric">{fullNumber(c.metrics.reach)}</td>
                  <td className="px-3 py-3 text-right font-mono-metric">{fullNumber(c.metrics.engagement)}</td>
                  <td className="px-5 py-3 text-right text-xs text-muted-foreground">{c.last_synced || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
