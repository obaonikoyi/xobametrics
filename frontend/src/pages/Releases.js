import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api, { compactNumber, formatApiErrorDetail } from "@/lib/api";
import { useWorkspace } from "@/context/WorkspaceContext";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { Freshness, PlatformBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Plus, Upload, Disc3, ArrowUpRight, GitMerge, Check, X, Sparkles, Link2Off } from "lucide-react";

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
  const [suggestions, setSuggestions] = useState([]);

  const load = useCallback(async () => {
    if (!activeProfile) return;
    setLoading(true);
    try {
      const [releaseResult, suggestionResult] = await Promise.all([
        api.get(`/releases?profile_id=${encodeURIComponent(activeProfile.id)}`),
        api.get(`/release-match-suggestions?profile_id=${encodeURIComponent(activeProfile.id)}`).catch(() => ({ data: { suggestions: [] } })),
      ]);
      setReleases(releaseResult.data.releases);
      setSuggestions(suggestionResult.data.suggestions || []);
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

  const reviewSuggestion = (suggestion) => {
    const ids = [suggestion.release_a.id, suggestion.release_b.id];
    setSelected(ids);
    const targetId = suggestion.suggested_target_id || ids[0];
    const target = releases.find((r) => r.id === targetId) || releases.find((r) => r.id === ids[0]);
    setMergeTarget(target?.id || ids[0]);
    setMergeForm({
      title: target?.title || suggestion.release_a.title,
      release_date: target?.release_date || suggestion.release_a.release_date,
      description: target?.description || "",
    });
    setMergeOpen(true);
  };

  const dismissSuggestion = async (suggestion) => {
    try {
      await api.post(
        `/release-match-suggestions/dismiss?profile_id=${encodeURIComponent(activeProfile.id)}&release_a=${encodeURIComponent(suggestion.release_a.id)}&release_b=${encodeURIComponent(suggestion.release_b.id)}`
      );
      setSuggestions((items) => items.filter((item) => item.match_key !== suggestion.match_key));
      toast.success("Match suggestion dismissed.");
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail || e?.message));
    }
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

      {!organizing && suggestions.length > 0 && (
        <section className="rounded-xl border border-primary/20 bg-card p-4" data-testid="release-match-suggestions">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-primary" /><h2 className="font-display font-semibold">Suggested campaign matches</h2></div>
              <p className="mt-1 text-xs text-muted-foreground">XobaMetrics found similarly named releases across platforms. Nothing is merged until you approve it.</p>
            </div>
            <span className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground">{suggestions.length}</span>
          </div>
          <div className="space-y-2">
            {suggestions.slice(0, 5).map((s) => (
              <div key={s.match_key} className="flex flex-col gap-3 rounded-lg border border-border p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    <span className="truncate">{s.release_a.title}</span>
                    <span className="text-muted-foreground">↔</span>
                    <span className="truncate">{s.release_b.title}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    {[...new Set([...(s.release_a.platforms || []), ...(s.release_b.platforms || [])])].map((p) => <PlatformBadge key={p} platform={p} />)}
                    <span className="text-[11px] text-muted-foreground">{s.confidence === "strong" ? "Strong match" : "Possible match"} · {s.date_gap_days} day{s.date_gap_days === 1 ? "" : "s"} apart</span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" className="gap-1.5" onClick={() => reviewSuggestion(s)}><GitMerge className="h-3.5 w-3.5" /> Review merge</Button>
                  <Button size="sm" variant="ghost" className="gap-1.5" onClick={() => dismissSuggestion(s)} title="Not the same campaign"><Link2Off className="h-3.5 w-3.5" /> Not a match</Button>
                </div>
              </div>
            ))}
          </div>
        </section>
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
