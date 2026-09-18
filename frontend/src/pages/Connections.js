import { useEffect, useState, useCallback } from "react";
import api, { compactNumber, formatApiErrorDetail } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { PLATFORMS, API_PLATFORMS, EXPORT_PLATFORMS, PlatformTile } from "@/components/common";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { CheckCircle2, Upload, Zap, FileUp, PlugZap, RefreshCw, AlertTriangle, Unplug } from "lucide-react";

export default function Connections() {
  const { activeProfile } = useWorkspace();
  const [dataByPlatform, setDataByPlatform] = useState({});
  const [youtube, setYoutube] = useState({ configured: false, connection: null });
  const [youtubeHistory, setYoutubeHistory] = useState({ scope_granted: false, backfilled_at: null, history_points_written: 0 });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    if (!activeProfile) { setLoading(false); return; }
    setLoading(true);
    setLoadError(false);
    try {
      const [overview, yt, history] = await Promise.all([
        api.get(`/analytics/overview?profile_id=${encodeURIComponent(activeProfile.id)}`),
        api.get(`/youtube/status?profile_id=${encodeURIComponent(activeProfile.id)}`),
        api.get(`/youtube/history-status?profile_id=${encodeURIComponent(activeProfile.id)}`),
      ]);
      const map = {};
      (overview.data.platform_breakdown || []).forEach((p) => { map[p.platform] = p.reach; });
      setDataByPlatform(map);
      setYoutube(yt.data);
      setYoutubeHistory(history.data);
    } catch {
      setDataByPlatform({});
      setLoadError(true);
    } finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const state = params.get("youtube");
    if (!state) return;
    if (state === "connected") {
      const imported = params.get("imported");
      const videos = params.get("videos");
      if (params.get("sync") === "failed") {
        toast.warning("YouTube connected, but the first metric import needs to be retried.");
      } else {
        toast.success(`YouTube connected${videos ? ` — ${videos} videos checked` : ""}${imported ? `, ${imported} new` : ""}.`);
      }
    } else {
      const reason = (params.get("reason") || "connection_failed").replaceAll("_", " ");
      toast.error(`YouTube connection failed: ${reason}`);
    }
    window.history.replaceState({}, "", window.location.pathname);
    load();
  }, [load]);

  const connectYoutube = async () => {
    if (!activeProfile) return;
    setBusy("youtube-connect");
    try {
      const { data } = await api.post(`/youtube/connect?profile_id=${encodeURIComponent(activeProfile.id)}`);
      window.location.assign(data.auth_url);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
      setBusy("");
    }
  };

  const syncYoutube = async () => {
    if (!activeProfile) return;
    setBusy("youtube-sync");
    try {
      const { data } = await api.post(`/youtube/sync?profile_id=${encodeURIComponent(activeProfile.id)}`);
      toast.success(`YouTube synced — ${data.videos_seen} videos checked, ${data.snapshots_created} new daily snapshots.`);
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    } finally { setBusy(""); }
  };

  const backfillYoutubeHistory = async () => {
    if (!activeProfile) return;
    setBusy("youtube-history");
    try {
      const { data } = await api.post(`/youtube/backfill-history?profile_id=${encodeURIComponent(activeProfile.id)}`);
      toast.success(`YouTube history imported — ${data.videos} videos, ${compactNumber(data.history_points_written)} historical points.`);
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    } finally { setBusy(""); }
  };

  const disconnectYoutube = async () => {
    if (!activeProfile || !window.confirm("Disconnect YouTube? Existing XobaMetrics history will be kept.")) return;
    setBusy("youtube-disconnect");
    try {
      await api.delete(`/youtube/disconnect?profile_id=${encodeURIComponent(activeProfile.id)}`);
      toast.success("YouTube disconnected. Stored analytics history was kept.");
      await load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    } finally { setBusy(""); }
  };

  const YoutubeCard = () => {
    const conn = youtube.connection;
    const connected = conn?.status === "connected";
    const needsReconnect = conn?.status === "needs_reconnect";
    const channelStats = conn?.channel_statistics;
    const total = dataByPlatform.youtube;
    const historyReady = youtubeHistory.scope_granted;
    return (
      <div data-testid="platform-card-youtube" className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
        <div className="flex items-start justify-between">
          <PlatformTile platform="youtube" className="h-11 w-11" />
          {connected ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-500"><CheckCircle2 className="h-3 w-3" /> Connected</span>
          ) : needsReconnect ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-500"><AlertTriangle className="h-3 w-3" /> Reconnect</span>
          ) : (
            <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">{youtube.configured ? "Ready to connect" : "Setup required"}</span>
          )}
        </div>
        <h3 className="mt-3 font-display text-lg font-semibold">YouTube</h3>
        <p className="mt-1 text-xs text-muted-foreground">Read-only OAuth. XobaMetrics imports your channel uploads and stores daily snapshots of views, likes and comments.</p>
        {conn?.account_name && <p className="mt-3 text-sm font-medium">{conn.account_name}</p>}
        {channelStats && connected && (
          <p className="mt-1 text-xs text-muted-foreground">{compactNumber(channelStats.subscriber_count)} subscribers · {compactNumber(channelStats.video_count)} videos</p>
        )}
        {total != null && <p className="mt-1 text-xs text-muted-foreground">{compactNumber(total)} stored YouTube views across imported content</p>}
        {conn?.last_synced_at && connected && <p className="mt-1 text-[11px] text-muted-foreground">Last synced {String(conn.last_synced_at).slice(0, 16).replace("T", " ")} UTC</p>}
        {connected && youtubeHistory.backfilled_at && (
          <p className="mt-1 text-[11px] text-muted-foreground">Historical Analytics imported through {youtubeHistory.history_end_date} · {compactNumber(youtubeHistory.history_points_written)} daily points</p>
        )}
        {connected && !historyReady && (
          <p className="mt-3 text-xs text-amber-500">Reconnect once to add read-only YouTube Analytics permission for historical Day-0/7/30/90 comparisons.</p>
        )}
        {!youtube.configured && <p className="mt-3 text-xs text-amber-500">Google OAuth credentials still need to be added to the backend.</p>}
        <div className="mt-4 flex gap-2">
          {connected ? (
            <>
              <Button className="flex-1 gap-2" onClick={syncYoutube} disabled={busy !== ""} data-testid="youtube-sync"><RefreshCw className={`h-4 w-4 ${busy === "youtube-sync" ? "animate-spin" : ""}`} /> Sync now</Button>
              <Button variant="outline" size="icon" onClick={disconnectYoutube} disabled={busy !== ""} title="Disconnect YouTube"><Unplug className="h-4 w-4" /></Button>
            </>
          ) : (
            <Button className="w-full gap-2" onClick={connectYoutube} disabled={!youtube.configured || busy !== ""} data-testid="youtube-connect"><PlugZap className="h-4 w-4" /> {needsReconnect ? "Reconnect YouTube" : "Connect YouTube"}</Button>
          )}
        </div>
        {connected && (
          <div className="mt-2">
            {historyReady ? (
              <Button variant="outline" className="w-full gap-2" onClick={backfillYoutubeHistory} disabled={busy !== ""} data-testid="youtube-history">
                <RefreshCw className={`h-4 w-4 ${busy === "youtube-history" ? "animate-spin" : ""}`} />
                {youtubeHistory.backfilled_at ? "Refresh historical analytics" : "Import historical analytics"}
              </Button>
            ) : (
              <Button variant="outline" className="w-full gap-2" onClick={connectYoutube} disabled={busy !== ""} data-testid="youtube-enable-history">
                <PlugZap className="h-4 w-4" /> Enable historical analytics
              </Button>
            )}
          </div>
        )}
      </div>
    );
  };

  const PlatformCard = ({ platform, planned = false }) => {
    const total = dataByPlatform[platform];
    return (
      <div data-testid={`platform-card-${platform}`} className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
        <div className="flex items-start justify-between">
          <PlatformTile platform={platform} className="h-11 w-11" />
          <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">{planned ? "API planned" : "CSV import"}</span>
        </div>
        <h3 className="mt-3 font-display text-lg font-semibold">{PLATFORMS[platform]?.label || platform}</h3>
        <p className="mt-1 flex-1 text-xs text-muted-foreground">{planned ? "Live OAuth is not available for this platform yet. Import a supported CSV export for now." : "Import a CSV you are authorised to use, then review the column mapping. Export formats and availability vary by platform."}</p>
        {total != null && <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground"><CheckCircle2 className="h-3 w-3" /> {compactNumber(total)} recorded in stored data</p>}
        <div className="mt-4">
          <CsvUploadDialog profileId={activeProfile.id} defaultPlatform={platform} onImported={load}
            trigger={<Button variant="outline" className="w-full gap-2" data-testid={`import-${platform}`}><FileUp className="h-4 w-4" /> Import CSV</Button>} />
        </div>
      </div>
    );
  };

  const plannedApiPlatforms = API_PLATFORMS.filter((p) => p !== "youtube");

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Platform connections</h1>
        <p className="mt-1 text-sm text-muted-foreground">YouTube is the first real OAuth integration. CSV imports remain available for other platforms.</p>
      </div>
      <div role="status" data-testid="integration-status-notice" className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
        YouTube uses read-only Google permission and stores snapshots in XobaMetrics. Other direct integrations remain disabled until their real OAuth adapters are implemented.
      </div>
      {loadError && <p role="alert" className="text-sm text-muted-foreground">Stored metrics could not be loaded. Check the backend connection and try again.</p>}
      {!activeProfile ? <p className="text-sm text-muted-foreground">Select a creator profile to import data.</p> : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
      ) : (
        <>
          <section>
            <div className="mb-3 flex items-center gap-2"><Zap className="h-4 w-4 text-primary" /><h2 className="font-display text-lg font-semibold">Direct integrations</h2></div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <YoutubeCard />
              {plannedApiPlatforms.map((p) => <PlatformCard key={p} platform={p} planned />)}
            </div>
          </section>
          <section>
            <div className="mb-3 flex items-center gap-2"><Upload className="h-4 w-4 text-primary" /><h2 className="font-display text-lg font-semibold">Import via CSV</h2></div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {EXPORT_PLATFORMS.map((p) => <PlatformCard key={p} platform={p} />)}
              <PlatformCard platform="csv" />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
