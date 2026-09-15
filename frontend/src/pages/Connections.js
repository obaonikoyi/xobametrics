import { useEffect, useState, useCallback } from "react";
import api, { compactNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { PLATFORMS, API_PLATFORMS, EXPORT_PLATFORMS, PlatformTile } from "@/components/common";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle2, Upload, Zap, FileUp } from "lucide-react";

export default function Connections() {
  const { activeProfile } = useWorkspace();
  const [dataByPlatform, setDataByPlatform] = useState({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    if (!activeProfile) { setLoading(false); return; }
    setLoading(true);
    setLoadError(false);
    try {
      const { data } = await api.get(`/analytics/overview?profile_id=${encodeURIComponent(activeProfile.id)}`);
      const map = {};
      (data.platform_breakdown || []).forEach((p) => { map[p.platform] = p.reach; });
      setDataByPlatform(map);
    } catch {
      setDataByPlatform({});
      setLoadError(true);
    } finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load]);

  const PlatformCard = ({ platform, planned = false }) => {
    const total = dataByPlatform[platform];
    return (
      <div data-testid={`platform-card-${platform}`} className="flex flex-col rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/40">
        <div className="flex items-start justify-between">
          <PlatformTile platform={platform} className="h-11 w-11" />
          <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
            {planned ? "API planned" : "CSV import"}
          </span>
        </div>
        <h3 className="mt-3 font-display text-lg font-semibold">{PLATFORMS[platform]?.label || platform}</h3>
        <p className="mt-1 flex-1 text-xs text-muted-foreground">
          {planned ? "Live connection and automatic sync are not available yet. Import a supported CSV export for now." : "Import a CSV you are authorised to use, then review the column mapping. Export formats and availability vary by platform."}
        </p>
        {total != null && <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted-foreground"><CheckCircle2 className="h-3 w-3" /> {compactNumber(total)} recorded in stored data (not a live sync)</p>}
        <div className="mt-4">
          <CsvUploadDialog profileId={activeProfile.id} defaultPlatform={platform} onImported={load}
            trigger={<Button variant="outline" className="w-full gap-2" data-testid={`import-${platform}`}><FileUp className="h-4 w-4" /> Import CSV</Button>} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Platform connections</h1>
        <p className="mt-1 text-sm text-muted-foreground">CSV imports are available. Live OAuth connections and scheduled platform sync are still under development.</p>
      </div>
      <div role="status" data-testid="integration-status-notice" className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
        No Connect button currently retrieves real platform metrics. This version does not simulate new growth or mark an unverified connection as synced. Demo data, when loaded, is illustrative only.
      </div>
      {loadError && <p role="alert" className="text-sm text-muted-foreground">Stored metrics could not be loaded. Check the backend connection and try again.</p>}
      {!activeProfile ? <p className="text-sm text-muted-foreground">Select a creator profile to import data.</p> : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
      ) : (
        <>
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              <h2 className="font-display text-lg font-semibold">Planned direct integrations</h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{API_PLATFORMS.map((p) => <PlatformCard key={p} platform={p} planned />)}</div>
          </section>
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Upload className="h-4 w-4 text-primary" />
              <h2 className="font-display text-lg font-semibold">Import via CSV</h2>
            </div>
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
