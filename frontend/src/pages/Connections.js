import { useEffect, useState, useCallback } from "react";
import api, { compactNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { PLATFORMS, PLATFORM_DESC, API_PLATFORMS, EXPORT_PLATFORMS, PlatformTile } from "@/components/common";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { PlugZap, RefreshCw, CheckCircle2, AlertTriangle, Upload, Zap, FileUp } from "lucide-react";

const STATUS = {
  connected: { label: "Connected", cls: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20", icon: CheckCircle2 },
  needs_reconnect: { label: "Needs reconnect", cls: "bg-rose-500/10 text-rose-500 border-rose-500/20", icon: AlertTriangle },
  needs_auth: { label: "Not connected", cls: "bg-muted text-muted-foreground border-border", icon: PlugZap },
  syncing: { label: "Syncing", cls: "bg-amber-500/10 text-amber-500 border-amber-500/20", icon: RefreshCw },
};

export default function Connections() {
  const { activeProfile } = useWorkspace();
  const [conns, setConns] = useState([]);
  const [dataByPlatform, setDataByPlatform] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const [c, o] = await Promise.all([
        api.get(`/connections?profile_id=${activeProfile.id}`),
        api.get(`/analytics/overview?profile_id=${activeProfile.id}`),
      ]);
      setConns(c.data.connections);
      const map = {};
      (o.data.platform_breakdown || []).forEach((p) => { map[p.platform] = p.reach; });
      setDataByPlatform(map);
    } finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load]);

  const connect = async (platform) => {
    setBusy(platform);
    try { await api.post("/connections", { profile_id: activeProfile.id, platform }); toast.success(`${PLATFORMS[platform]?.label} connected.`); load(); }
    catch { toast.error("Connection failed."); }
    finally { setBusy(""); }
  };
  const reconnect = async (id, platform) => {
    setBusy(platform);
    try { await api.post(`/connections/${id}/reconnect`); toast.success("Reconnected."); load(); }
    catch { toast.error("Reconnect failed."); }
    finally { setBusy(""); }
  };
  const sync = async (id, platform) => {
    setBusy(platform);
    try {
      const { data } = await api.post(`/connections/${id}/sync`);
      toast.success(data.snapshots_created > 0 ? `Synced — ${data.snapshots_created} new snapshots.` : "Up to date — already synced today.");
      load();
    } catch { toast.error("Sync failed."); }
    finally { setBusy(""); }
  };

  const byPlatform = Object.fromEntries(conns.map((c) => [c.platform, c]));

  const ApiCard = ({ platform }) => {
    const conn = byPlatform[platform];
    const status = conn?.status || "needs_auth";
    const meta = STATUS[status];
    return (
      <div data-testid={`platform-card-${platform}`} className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
        <div className="flex items-start justify-between">
          <PlatformTile platform={platform} className="h-11 w-11" />
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.cls}`}>
            <meta.icon className="h-3 w-3" /> {meta.label}
          </span>
        </div>
        <h3 className="mt-3 font-display text-lg font-semibold">{PLATFORMS[platform].label}</h3>
        <p className="mt-1 flex-1 text-xs text-muted-foreground">{PLATFORM_DESC[platform]}</p>
        {conn?.account_name && <p className="mt-2 text-xs font-medium">{conn.account_name}</p>}
        {status === "connected" && conn?.last_synced_at && (
          <p className="mt-1 text-[11px] text-muted-foreground" data-testid={`last-synced-${platform}`}>Last synced {String(conn.last_synced_at).slice(0, 16).replace("T", " ")} UTC</p>
        )}
        <div className="mt-4">
          {status === "connected" ? (
            <Button variant="outline" className="w-full gap-2" disabled={busy === platform} onClick={() => sync(conn.id, platform)} data-testid={`refresh-${platform}`}>
              <RefreshCw className={`h-4 w-4 ${busy === platform ? "animate-spin" : ""}`} /> Refresh sync
            </Button>
          ) : status === "needs_reconnect" ? (
            <Button className="w-full gap-2" disabled={busy === platform} onClick={() => reconnect(conn.id, platform)} data-testid={`reconnect-${platform}`}>
              <AlertTriangle className="h-4 w-4" /> Reconnect
            </Button>
          ) : (
            <Button className="w-full gap-2" disabled={busy === platform} onClick={() => connect(platform)} data-testid={`connect-${platform}`}>
              <PlugZap className="h-4 w-4" /> Connect
            </Button>
          )}
        </div>
      </div>
    );
  };

  const ExportCard = ({ platform }) => {
    const reach = dataByPlatform[platform];
    return (
      <div data-testid={`platform-card-${platform}`} className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
        <div className="flex items-start justify-between">
          <PlatformTile platform={platform} className="h-11 w-11" />
          {reach ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-500">
              <CheckCircle2 className="h-3 w-3" /> {compactNumber(reach)} tracked
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-0.5 text-[11px] font-semibold text-muted-foreground">Export-only</span>
          )}
        </div>
        <h3 className="mt-3 font-display text-lg font-semibold">{PLATFORMS[platform].label}</h3>
        <p className="mt-1 flex-1 text-xs text-muted-foreground">{PLATFORM_DESC[platform]}</p>
        <div className="mt-4">
          <CsvUploadDialog profileId={activeProfile.id} defaultPlatform={platform} onImported={load}
            trigger={<Button variant="outline" className="w-full gap-2" data-testid={`import-${platform}`}><FileUp className="h-4 w-4" /> Import export</Button>} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Platform connections</h1>
        <p className="mt-1 text-sm text-muted-foreground">Snapshots sync automatically every day at 04:00 UTC — we never live-call platform APIs on page load. Use “Refresh sync” to pull now.</p>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
      ) : (
        <>
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              <h2 className="font-display text-lg font-semibold">Direct API</h2>
              <span className="text-xs text-muted-foreground">OAuth connect · auto-sync</span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {API_PLATFORMS.map((p) => <ApiCard key={p} platform={p} />)}
            </div>
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <Upload className="h-4 w-4 text-primary" />
              <h2 className="font-display text-lg font-semibold">Import via export (CSV)</h2>
              <span className="text-xs text-muted-foreground">No open metrics API — upload each platform’s “for Artists” export</span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {EXPORT_PLATFORMS.map((p) => <ExportCard key={p} platform={p} />)}
              <div data-testid="platform-card-csv" className="flex flex-col rounded-xl border border-dashed border-border bg-card p-5">
                <PlatformTile platform="csv" className="h-11 w-11" />
                <h3 className="mt-3 font-display text-lg font-semibold">Other / Generic CSV</h3>
                <p className="mt-1 flex-1 text-xs text-muted-foreground">{PLATFORM_DESC.csv}</p>
                <div className="mt-4">
                  <CsvUploadDialog profileId={activeProfile.id} defaultPlatform="csv" onImported={load}
                    trigger={<Button variant="outline" className="w-full gap-2" data-testid="import-csv"><Upload className="h-4 w-4" /> Upload CSV</Button>} />
                </div>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
