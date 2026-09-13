import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { PLATFORMS } from "@/components/common";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { PlugZap, RefreshCw, CheckCircle2, AlertTriangle, Upload, Youtube, Music2, Radio, Instagram, Twitter } from "lucide-react";

const CATALOG = [
  { platform: "youtube", icon: Youtube, desc: "Video & Shorts stats via Data API (batchGetStats)." },
  { platform: "soundcloud", icon: Music2, desc: "Track plays & engagement (OAuth 2.1 + PKCE)." },
  { platform: "tiktok", icon: Radio, desc: "Promo video reach — pending app review." },
  { platform: "instagram", icon: Instagram, desc: "Reels & posts via Graph API — pending review." },
  { platform: "twitter", icon: Twitter, desc: "Post impressions & engagement." },
  { platform: "csv", icon: Upload, desc: "Universal fallback — upload any platform export." },
];

const STATUS = {
  connected: { label: "Connected", cls: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20", icon: CheckCircle2 },
  needs_reconnect: { label: "Needs reconnect", cls: "bg-rose-500/10 text-rose-500 border-rose-500/20", icon: AlertTriangle },
  needs_auth: { label: "Not connected", cls: "bg-muted text-muted-foreground border-border", icon: PlugZap },
  syncing: { label: "Syncing", cls: "bg-amber-500/10 text-amber-500 border-amber-500/20", icon: RefreshCw },
};

export default function Connections() {
  const { activeProfile } = useWorkspace();
  const [conns, setConns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try { const { data } = await api.get(`/connections?profile_id=${activeProfile.id}`); setConns(data.connections); }
    finally { setLoading(false); }
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Platform connections</h1>
        <p className="mt-1 text-sm text-muted-foreground">Snapshots sync automatically every day at 04:00 UTC — we never live-call platform APIs on page load. Use “Refresh sync” to pull now.</p>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {CATALOG.map(({ platform, icon: Icon, desc }) => {
            const conn = byPlatform[platform];
            const status = conn?.status || "needs_auth";
            const meta = STATUS[status];
            const color = PLATFORMS[platform]?.color;
            return (
              <div key={platform} data-testid={`platform-card-${platform}`} className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
                <div className="flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-lg" style={{ backgroundColor: `${color}1f`, color }}><Icon className="h-5 w-5" /></span>
                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.cls}`}>
                    <meta.icon className="h-3 w-3" /> {meta.label}
                  </span>
                </div>
                <h3 className="mt-3 font-display text-lg font-semibold">{PLATFORMS[platform]?.label}</h3>
                <p className="mt-1 flex-1 text-xs text-muted-foreground">{desc}</p>
                {conn?.account_name && <p className="mt-2 text-xs font-medium">{conn.account_name}</p>}
                {conn?.status === "connected" && conn?.last_synced_at && (
                  <p className="mt-1 text-[11px] text-muted-foreground" data-testid={`last-synced-${platform}`}>Last synced {String(conn.last_synced_at).slice(0, 16).replace("T", " ")} UTC</p>
                )}

                <div className="mt-4">
                  {platform === "csv" ? (
                    <CsvUploadDialog profileId={activeProfile.id} onImported={load} trigger={<Button variant="outline" className="w-full gap-2"><Upload className="h-4 w-4" /> Upload CSV</Button>} />
                  ) : status === "connected" ? (
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
          })}
        </div>
      )}
    </div>
  );
}
