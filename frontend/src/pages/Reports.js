import { useEffect, useState, useCallback } from "react";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { FileBarChart, Plus, Link2, Sparkles, Eye } from "lucide-react";

export default function Reports() {
  const { activeProfile } = useWorkspace();
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState(null);

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try { const { data } = await api.get(`/reports?profile_id=${activeProfile.id}`); setReports(data.reports); }
    finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/reports", { profile_id: activeProfile.id, title: title || `${activeProfile.name} — Performance Report` });
      toast.success("Report generated.");
      setOpen(false); setTitle(""); load(); setViewing(data.report);
    } catch { toast.error("Could not generate report."); }
    finally { setBusy(false); }
  };

  const copyShare = (shareId) => {
    const url = `${window.location.origin}/share/${shareId}`;
    navigator.clipboard.writeText(url);
    toast.success("Share link copied to clipboard.");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Reports</h1>
          <p className="mt-1 text-sm text-muted-foreground">Shareable, AI-summarized snapshots for managers &amp; clients.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><Button className="gap-2" data-testid="new-report-button"><Plus className="h-4 w-4" /> Generate report</Button></DialogTrigger>
          <DialogContent data-testid="new-report-dialog">
            <DialogHeader><DialogTitle className="font-display">Generate report</DialogTitle></DialogHeader>
            <div><Label>Title</Label><Input data-testid="report-title-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${activeProfile?.name} — Performance Report`} className="mt-1.5" /></div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Sparkles className="h-3.5 w-3.5 text-primary" /> Includes an AI summary grounded in your computed totals.</p>
            <DialogFooter><Button onClick={generate} disabled={busy} data-testid="report-generate-submit">{busy ? "Generating…" : "Generate"}</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2">{[...Array(2)].map((_, i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
      ) : reports.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-16 text-center">
          <FileBarChart className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">No reports yet. Generate one to share performance.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {reports.map((r) => (
            <div key={r.id} data-testid={`report-card-${r.id}`} className="rounded-xl border border-border bg-card p-5">
              <FileBarChart className="h-6 w-6 text-primary" />
              <h3 className="mt-3 font-display text-lg font-semibold">{r.title}</h3>
              <p className="text-xs text-muted-foreground">{(r.created_at || "").slice(0, 10)} · {fullNumber(r.totals?.reach)} reach</p>
              <div className="mt-4 flex gap-2">
                <Button variant="outline" size="sm" className="flex-1 gap-1.5" onClick={() => setViewing(r)} data-testid={`view-report-${r.id}`}><Eye className="h-3.5 w-3.5" /> View</Button>
                <Button variant="outline" size="sm" className="gap-1.5" onClick={() => copyShare(r.share_id)} data-testid={`share-report-${r.id}`}><Link2 className="h-3.5 w-3.5" /> Share</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
        <DialogContent className="max-w-2xl" data-testid="report-view-dialog">
          {viewing && <ReportBody report={viewing} onShare={() => copyShare(viewing.share_id)} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function ReportBody({ report, onShare }) {
  const t = report.totals || {};
  return (
    <div>
      <DialogHeader><DialogTitle className="font-display text-xl">{report.title}</DialogTitle></DialogHeader>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[["Reach", t.reach], ["Engagement", t.engagement], ["Followers", t.followers]].map(([l, v]) => (
          <div key={l} className="rounded-lg border border-border p-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{l}</div>
            <div className="mt-1 font-mono-metric text-xl font-bold">{compactNumber(v)}</div>
          </div>
        ))}
      </div>
      {report.summary && (
        <div className="mt-4 rounded-lg border border-primary/20 bg-primary/[0.05] p-4">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-primary"><Sparkles className="h-3.5 w-3.5" /> AI Summary</div>
          <p className="mt-2 text-sm leading-relaxed">{report.summary}</p>
        </div>
      )}
      {report.recommendations?.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {report.recommendations.map((r, i) => <li key={i} className="flex gap-2 text-sm"><span className="font-mono-metric text-primary">{i + 1}.</span>{r}</li>)}
        </ul>
      )}
      <div className="mt-4 rounded-lg border border-border">
        <div className="border-b border-border px-4 py-2 text-xs font-semibold text-muted-foreground">Releases</div>
        <table className="w-full text-sm">
          <tbody>
            {(report.releases || []).map((r) => (
              <tr key={r.id} className="border-t border-border first:border-0"><td className="px-4 py-2">{r.title}</td><td className="px-4 py-2 text-right font-mono-metric">{fullNumber(r.reach)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {onShare && <div className="mt-4 flex justify-end"><Button variant="outline" size="sm" className="gap-1.5" onClick={onShare}><Link2 className="h-3.5 w-3.5" /> Copy share link</Button></div>}
    </div>
  );
}
