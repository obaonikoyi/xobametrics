import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api, { compactNumber } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Freshness } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Plus, Upload, Disc3, ArrowUpRight } from "lucide-react";

export default function Releases() {
  const { activeProfile } = useWorkspace();
  const navigate = useNavigate();
  const [releases, setReleases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", release_date: "", description: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/releases?profile_id=${activeProfile.id}`);
      setReleases(data.releases);
    } finally { setLoading(false); }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.title || !form.release_date) { toast.error("Title and release date are required."); return; }
    setBusy(true);
    try {
      await api.post("/releases", { profile_id: activeProfile.id, ...form });
      toast.success("Release created.");
      setOpen(false); setForm({ title: "", release_date: "", description: "" });
      load();
    } catch { toast.error("Could not create release."); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Releases</h1>
          <p className="mt-1 text-sm text-muted-foreground">Campaign rollups grouping content across platforms.</p>
        </div>
        <div className="flex gap-2">
          <CsvUploadDialog profileId={activeProfile?.id} onImported={load} trigger={<Button variant="outline" className="gap-2"><Upload className="h-4 w-4" /> Import CSV</Button>} />
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild><Button className="gap-2" data-testid="new-release-button"><Plus className="h-4 w-4" /> New release</Button></DialogTrigger>
            <DialogContent data-testid="new-release-dialog">
              <DialogHeader><DialogTitle className="font-display">Create release</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <div><Label>Title</Label><Input data-testid="release-title-input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Take It Easy" className="mt-1.5" /></div>
                <div><Label>Release date (Day 0)</Label><Input data-testid="release-date-input" type="date" value={form.release_date} onChange={(e) => setForm({ ...form, release_date: e.target.value })} className="mt-1.5" /></div>
                <div><Label>Description</Label><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-1.5" /></div>
              </div>
              <DialogFooter><Button onClick={create} disabled={busy} data-testid="release-create-submit">{busy ? "Creating…" : "Create"}</Button></DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-40 rounded-xl" />)}</div>
      ) : releases.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-16 text-center">
          <Disc3 className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">No releases yet. Import a CSV or create one.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {releases.map((r) => (
            <button key={r.id} data-testid={`release-card-${r.id}`} onClick={() => navigate(`/releases/${r.id}`)}
              className="group rounded-xl border border-border bg-card p-5 text-left transition-all hover:border-primary/40 hover:shadow-md">
              <div className="flex items-start justify-between">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg text-white" style={{ background: r.cover || "#3B82F6" }}><Disc3 className="h-5 w-5" /></div>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <h3 className="mt-3 font-display text-lg font-semibold">{r.title}</h3>
              <p className="text-xs text-muted-foreground">Day 0 · {r.release_date} · {r.content_count} items</p>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                <div><div className="text-[11px] uppercase tracking-wider text-muted-foreground">Reach</div><div className="font-mono-metric text-lg font-bold">{compactNumber(r.reach)}</div></div>
                <div className="text-right"><div className="text-[11px] uppercase tracking-wider text-muted-foreground">Engagement</div><div className="font-mono-metric text-lg font-bold">{compactNumber(r.engagement)}</div></div>
              </div>
              <div className="mt-3"><Freshness date={r.last_synced} /></div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
