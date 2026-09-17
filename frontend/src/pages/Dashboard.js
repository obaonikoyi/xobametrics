import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { useAi } from "@/context/AiContext";
import { StatCard, Freshness } from "@/components/common";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, Cell,
} from "recharts";
import {
  Eye, Heart, Users, Disc3, Sparkles, Zap, PlugZap, Upload, ArrowRight, ShieldCheck,
} from "lucide-react";

export default function Dashboard() {
  const { activeProfile } = useWorkspace();
  const { openWith } = useAi();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [insight, setInsight] = useState(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightError, setInsightError] = useState("");
  const [seeding, setSeeding] = useState(false);

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/analytics/overview?profile_id=${activeProfile.id}`);
      setData(data);
    } finally {
      setLoading(false);
    }
  }, [activeProfile]);

  const loadInsight = useCallback(async () => {
    if (!activeProfile) return;
    setInsightLoading(true);
    setInsightError("");
    try {
      const { data } = await api.post("/ai/insights", { profile_id: activeProfile.id });
      setInsight(data);
    } catch (e) {
      setInsight(null);
      setInsightError(e?.response?.data?.detail || "AI insights are temporarily unavailable. Your analytics are still available.");
    } finally {
      setInsightLoading(false);
    }
  }, [activeProfile]);

  useEffect(() => { load(); setInsight(null); setInsightError(""); }, [load]);
  useEffect(() => {
    if (data && data.release_count > 0 && !insight && !insightLoading && !insightError) loadInsight();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const seedDemo = async () => {
    setSeeding(true);
    try { await api.post("/demo/seed"); await load(); } finally { setSeeding(false); }
  };

  if (loading) {
    return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>;
  }

  if (!data || data.release_count === 0) {
    return <EmptyState onSeed={seedDemo} seeding={seeding} navigate={navigate} profileId={activeProfile?.id} onImported={load} />;
  }

  const t = data.totals;
  const breakdown = data.platform_breakdown.map((p) => ({ ...p, name: p.label }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{activeProfile?.name}</h1>
          <div className="mt-1"><Freshness date={data.last_synced} /></div>
        </div>
        <div className="flex gap-2">
          <CsvUploadDialog profileId={activeProfile.id} onImported={load} trigger={<Button variant="outline" className="gap-2"><Upload className="h-4 w-4" /> Upload CSV</Button>} />
          <Button className="gap-2" data-testid="dashboard-open-race" onClick={() => navigate("/race")}><Zap className="h-4 w-4" /> Release Race</Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard testId="stat-reach" label="Total Reach" value={t.reach} sub={`${data.release_count} releases`} icon={Eye} accent="#3B82F6" />
        <StatCard testId="stat-engagement" label="Engagement" value={t.engagement} sub="likes + comments + shares" icon={Heart} accent="#F43F5E" />
        <StatCard testId="stat-followers" label="Followers Gained" value={t.followers} sub="across content" icon={Users} accent="#34D399" />
        <StatCard testId="stat-releases" label="Releases" value={data.release_count} sub={data.top_release ? `Top: ${data.top_release.title}` : ""} icon={Disc3} accent="#A78BFA" />
      </div>

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} data-testid="ai-insight-card"
        className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/[0.06] to-transparent p-5">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
            <Sparkles className="h-5 w-5 text-primary" /> AI Performance Summary
          </h3>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-500">
            <ShieldCheck className="h-3.5 w-3.5" /> Grounded in your data
          </span>
        </div>
        {insightLoading && <div className="mt-3 space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div>}
        {insightError && !insightLoading && (
          <div className="mt-3 rounded-lg border border-border bg-card/60 p-3 text-sm text-muted-foreground" data-testid="ai-insight-unavailable">
            {insightError}
          </div>
        )}
        {insight && !insightLoading && (
          <>
            <p className="mt-3 text-sm leading-relaxed text-foreground/90">{insight.summary}</p>
            {insight.recommendations?.length > 0 && (
              <ul className="mt-4 grid gap-2 sm:grid-cols-3">
                {insight.recommendations.map((r, i) => (
                  <li key={i} className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
                    <span className="font-mono-metric mr-1.5 text-primary">{String(i + 1).padStart(2, "0")}</span>{r}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        <Button variant="ghost" size="sm" className="mt-3 gap-1.5 text-primary" onClick={() => openWith()} data-testid="ai-followup-button">
          Ask a follow-up <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </motion.div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-5 lg:col-span-2">
          <h3 className="font-display text-lg font-semibold">Reach by platform</h3>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={breakdown} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis type="number" tickFormatter={compactNumber} stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis type="category" dataKey="name" width={90} stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip formatter={(v) => fullNumber(v)} contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 12 }} cursor={{ fill: "hsl(var(--muted) / 0.4)" }} />
                <Bar dataKey="reach" radius={[0, 6, 6, 0]}>
                  {breakdown.map((e, i) => <Cell key={i} fill={e.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="font-display text-lg font-semibold">Top releases</h3>
          <div className="mt-4 space-y-2">
            {data.releases.slice(0, 5).map((r, i) => (
              <button key={r.id} data-testid={`dashboard-release-${r.id}`} onClick={() => navigate(`/releases/${r.id}`)}
                className="flex w-full items-center gap-3 rounded-lg border border-border p-2.5 text-left transition-colors hover:border-primary/40">
                <span className="flex h-9 w-9 items-center justify-center rounded-md font-mono-metric text-sm font-bold text-white" style={{ background: r.cover || "#3B82F6" }}>{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{r.title}</div>
                  <div className="text-xs text-muted-foreground">{r.content_count} items · {r.release_date}</div>
                </div>
                <span className="font-mono-metric text-sm font-semibold">{compactNumber(r.reach)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onSeed, seeding, navigate, profileId, onImported }) {
  return (
    <div className="animate-fade-up mx-auto max-w-2xl py-10 text-center">
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Disc3 className="h-8 w-8" />
      </div>
      <h1 className="mt-5 font-display text-2xl font-bold sm:text-3xl">Let's bring in your numbers</h1>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Upload a CSV, review planned integrations, or load demo data to see auto-charts, Release Race and grounded AI insights.
      </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        <button onClick={onSeed} disabled={seeding} data-testid="empty-load-demo" className="rounded-xl border border-primary/30 bg-primary/5 p-5 text-left transition-colors hover:border-primary/60">
          <Sparkles className="h-6 w-6 text-primary" />
          <div className="mt-3 font-semibold">{seeding ? "Loading…" : "Load demo data"}</div>
          <div className="mt-1 text-xs text-muted-foreground">Sample multi-platform releases</div>
        </button>
        <CsvUploadDialog profileId={profileId} onImported={onImported} trigger={
          <button data-testid="empty-upload-csv" className="w-full rounded-xl border border-border bg-card p-5 text-left transition-colors hover:border-primary/40">
            <Upload className="h-6 w-6 text-primary" />
            <div className="mt-3 font-semibold">Upload CSV</div>
            <div className="mt-1 text-xs text-muted-foreground">Any platform export</div>
          </button>} />
        <button onClick={() => navigate("/connections")} data-testid="empty-connect" className="rounded-xl border border-border bg-card p-5 text-left transition-colors hover:border-primary/40">
          <PlugZap className="h-6 w-6 text-primary" />
          <div className="mt-3 font-semibold">View integrations</div>
          <div className="mt-1 text-xs text-muted-foreground">YouTube, SoundCloud and more</div>
        </button>
      </div>
    </div>
  );
}
