import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api, { compactNumber, formatApiErrorDetail } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Freshness } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Plus, Upload, Disc3, ArrowUpRight, GitMerge, Check, X } from "lucide-react";

const coverIsImage = (cover) => typeof cover === "string" && /^https?:\/\//i.test(cover);

export default function Releases() {
  const { activeProfile } = useWorkspace();
  const navigate = useNavigate();
  const [releases, setReleases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", release_date: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  const [selected, setSelected] = useState([]);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");
  const [mergeForm, setMergeForm] = useState({ title: "", release_date: "", description: "" });

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/releases?profile_id=${encodeURIComponent(activeProfile.id)}`);
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
      setOpen(false);
      setForm({ title: "", release_date: "", description: "" });
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    } finally { setBusy(false); }
  };

  const toggleSelected = (id) => {
    setSelected((current) => current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  };

  const stopOrganizing = () => {
    setOrganizing(false);
    setSelected([]);
    setMergeOpen(false);
  };

  const beginMerge = () => {
    if (selected.length < 2) {
      toast.error("Select at least two releases to merge.");
      return;
    }
    const target = releases.find((r) => r.id === selected[0]);
    if (!target) return;
    setMergeTarget(target.id);
    setMergeForm({
      title: target.title || "",
      release_date: target.release_date || "",
      description: target.description || "",
    });
    setMergeOpen(true);
  };

  const chooseTarget = (id) => {
    const target = releases.find((r) => r.id === id);
    setMergeTarget(id);
    if (target) {
      setMergeForm({
        title: target.title || "",
        release_date: target.release_date || "",
        description: target.description || "",
      });
    }
  };

  const merge = async () => {
    if (!mergeTarget || selected.length < 2 || !mergeForm.title || !mergeForm.release_date) return;
    setBusy(true);
    try {
      const sources = selected.filter((id) => id !== mergeTarget);
      const { data } = await api.post(`/releases/${encodeURIComponent(mergeTarget)}/merge`, {
        source_release_ids: sources,
        title: mergeForm.title,
        release_date: mergeForm.release_date,
        description: mergeForm.description,
      });
      toast.success(`Merged ${sources.length + 1} releases into one campaign with ${data.content_count} content items.`);
      stopOrganizing();
      await load();
      navigate(`/releases/${mergeTarget}`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Releases</h1>
          <p className="mt-1 text-sm text-muted-foreground">Campaign rollups grouping content across platforms.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {organizing ? (
            <>
              <Button variant="outline" className="gap-2" onClick={stopOrganizing}><X className="h-4 w-4" /> Cancel</Button>
              <Button className="gap-2" onClick={beginMerge} disabled={selected.length < 2} data-testid="merge-selected-button">
                <GitMerge className="h-4 w-4" /> Merge selected ({selected.length})
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" className="gap-2" onClick={() => setOrganizing(true)} disabled={releases.length < 2} data-testid="organize-releases-button">
                <GitMerge className="h-4 w-4" /> Organize
              </Button>
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
            </>
          )}
        </div>
      </div>

      {organizing && (
        <div className="rounded-xl border border-primary/20 bg-primary/[0.05] p-4 text-sm text-muted-foreground">
          Select uploads that belong to the same song or campaign. The target release keeps its identity; all selected content and metric history move into it. Release Race will align the campaign to the target Day 0.
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-40 rounded-xl" />)}</div>
      ) : releases.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-16 text-center">
          <Disc3 className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">No releases yet. Import a CSV or create one.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {releases.map((r) => {
            const on = selected.includes(r.id);
            return (
              <button key={r.id} data-testid={`release-card-${r.id}`} onClick={() => organizing ? toggleSelected(r.id) : navigate(`/releases/${r.id}`)}
                className={`group relative overflow-hidden rounded-xl border bg-card p-5 text-left transition-all hover:shadow-md ${on ? "border-primary ring-1 ring-primary/40" : "border-border hover:border-primary/40"}`}>
                {organizing && (
                  <span className={`absolute right-4 top-4 flex h-6 w-6 items-center justify-center rounded-full border ${on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-transparent"}`}>
                    <Check className="h-3.5 w-3.5" />
                  </span>
                )}
                <div className="flex items-start justify-between pr-8">
                  {coverIsImage(r.cover) ? (
                    <img src={r.cover} alt="" className="h-11 w-11 rounded-lg object-cover" />
                  ) : (
                    <div className="flex h-11 w-11 items-center justify-center rounded-lg text-white" style={{ background: r.cover || "#3B82F6" }}><Disc3 className="h-5 w-5" /></div>
                  )}
                  {!organizing && <ArrowUpRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />}
                </div>
                <h3 className="mt-3 line-clamp-2 font-display text-lg font-semibold">{r.title}</h3>
                <p className="text-xs text-muted-foreground">Day 0 · {r.release_date} · {r.content_count} item{r.content_count === 1 ? "" : "s"}</p>
                <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                  <div><div className="text-[11px] uppercase tracking-wider text-muted-foreground">Reach</div><div className="font-mono-metric text-lg font-bold">{compactNumber(r.reach)}</div></div>
                  <div className="text-right"><div className="text-[11px] uppercase tracking-wider text-muted-foreground">Engagement</div><div className="font-mono-metric text-lg font-bold">{compactNumber(r.engagement)}</div></div>
                </div>
                <div className="mt-3"><Freshness date={r.last_synced} /></div>
              </button>
            );
          })}
        </div>
      )}

      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent data-testid="merge-releases-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">Merge into one campaign</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">Choose which selected release becomes the campaign. Other selected release records are removed, but their content and metric history are preserved.</p>
          <div className="space-y-3">
            <div>
              <Label>Keep as campaign</Label>
              <Select value={mergeTarget} onValueChange={chooseTarget}>
                <SelectTrigger className="mt-1.5"><SelectValue placeholder="Choose target release" /></SelectTrigger>
                <SelectContent>
                  {releases.filter((r) => selected.includes(r.id)).map((r) => (
                    <SelectItem key={r.id} value={r.id}>{r.title}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div><Label>Campaign title</Label><Input className="mt-1.5" value={mergeForm.title} onChange={(e) => setMergeForm({ ...mergeForm, title: e.target.value })} /></div>
            <div><Label>Day 0</Label><Input className="mt-1.5" type="date" value={mergeForm.release_date} onChange={(e) => setMergeForm({ ...mergeForm, release_date: e.target.value })} /></div>
            <div><Label>Description</Label><Textarea className="mt-1.5" value={mergeForm.description} onChange={(e) => setMergeForm({ ...mergeForm, description: e.target.value })} placeholder="Optional campaign note" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMergeOpen(false)}>Cancel</Button>
            <Button onClick={merge} disabled={busy || !mergeTarget || !mergeForm.title || !mergeForm.release_date} data-testid="merge-releases-submit">
              {busy ? "Merging…" : `Merge ${selected.length} releases`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
