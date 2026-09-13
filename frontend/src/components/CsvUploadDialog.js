import { useRef, useState } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { UploadCloud, FileSpreadsheet, ArrowRight } from "lucide-react";

const CANONICAL = ["date", "plays", "views", "likes", "comments", "shares", "followers"];
const PLATFORMS = [["soundcloud", "SoundCloud"], ["youtube", "YouTube"], ["tiktok", "TikTok"], ["instagram", "Instagram"], ["csv", "Other / Generic"]];

export default function CsvUploadDialog({ profileId, onImported, trigger }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [parsed, setParsed] = useState(null);
  const [mapping, setMapping] = useState({});
  const [meta, setMeta] = useState({ platform: "soundcloud", title: "", date: "", content_type: "track" });
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();

  const reset = () => { setStep(1); setParsed(null); setMapping({}); setMeta({ platform: "soundcloud", title: "", date: "", content_type: "track" }); };

  const handleFile = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("profile_id", profileId);
      const { data } = await api.post("/csv/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setParsed(data);
      setMapping(data.suggested_mapping || {});
      const firstDate = data.preview?.[0]?.date || "";
      setMeta((m) => ({ ...m, title: file.name.replace(/\.csv$/i, ""), date: firstDate }));
      setStep(2);
    } catch (e) {
      toast.error("Could not parse that CSV.");
    } finally { setBusy(false); }
  };

  const commit = async () => {
    if (!meta.title || !meta.date) { toast.error("Add a release title and Day-0 date."); return; }
    setBusy(true);
    try {
      await api.post("/csv/commit", {
        profile_id: profileId,
        platform: meta.platform,
        release_title: meta.title,
        release_date: meta.date,
        mapping,
        rows: parsed.rows,
        content_title: meta.title,
        content_type: meta.content_type,
      });
      toast.success("CSV imported — snapshots created.");
      setOpen(false); reset();
      onImported && onImported();
    } catch (e) {
      toast.error("Import failed. Check your mapping.");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset(); }}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-2xl" data-testid="csv-upload-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Import CSV {step === 2 && "— map & confirm"}</DialogTitle>
          <DialogDescription>Upload a platform export; we auto-detect columns and create a release with time-series snapshots.</DialogDescription>
        </DialogHeader>

        {step === 1 && (
          <div
            data-testid="csv-dropzone"
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); handleFile(e.dataTransfer.files?.[0]); }}
            className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-border py-12 text-center transition-colors hover:border-primary/50"
          >
            <UploadCloud className="h-10 w-10 text-primary" />
            <p className="mt-3 font-medium">{busy ? "Parsing…" : "Drop a CSV or click to browse"}</p>
            <p className="mt-1 text-xs text-muted-foreground">We auto-detect columns from any platform export.</p>
            <input ref={fileRef} type="file" accept=".csv" hidden data-testid="csv-file-input" onChange={(e) => handleFile(e.target.files?.[0])} />
          </div>
        )}

        {step === 2 && parsed && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>Release title</Label>
                <Input data-testid="csv-release-title" value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} className="mt-1.5" />
              </div>
              <div>
                <Label>Release date (Day 0)</Label>
                <Input data-testid="csv-release-date" type="date" value={meta.date} onChange={(e) => setMeta({ ...meta, date: e.target.value })} className="mt-1.5" />
              </div>
              <div>
                <Label>Platform</Label>
                <Select value={meta.platform} onValueChange={(v) => setMeta({ ...meta, platform: v })}>
                  <SelectTrigger className="mt-1.5" data-testid="csv-platform-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{PLATFORMS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Content type</Label>
                <Input value={meta.content_type} onChange={(e) => setMeta({ ...meta, content_type: e.target.value })} className="mt-1.5" />
              </div>
            </div>

            <div>
              <Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Column mapping</Label>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {CANONICAL.map((field) => (
                  <div key={field} className="flex items-center gap-2">
                    <span className="w-24 text-sm capitalize text-muted-foreground">{field}</span>
                    <Select value={mapping[field] || "__none__"} onValueChange={(v) => setMapping({ ...mapping, [field]: v === "__none__" ? undefined : v })}>
                      <SelectTrigger className="flex-1" data-testid={`csv-map-${field}`}><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">— none —</SelectItem>
                        {parsed.headers.map((h) => <SelectItem key={h} value={h}>{h}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border">
              <div className="border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">Preview ({parsed.row_count} rows)</div>
              <div className="max-h-40 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-secondary/60"><tr>{parsed.headers.slice(0, 6).map((h) => <th key={h} className="px-3 py-1.5 text-left font-medium">{h}</th>)}</tr></thead>
                  <tbody>{parsed.rows.slice(0, 8).map((r, i) => <tr key={i} className="border-t border-border">{parsed.headers.slice(0, 6).map((h) => <td key={h} className="px-3 py-1.5 font-mono-metric">{String(r[h] ?? "")}</td>)}</tr>)}</tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          {step === 2 && <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>}
          {step === 2 && <Button onClick={commit} disabled={busy} data-testid="csv-commit-button" className="gap-2">{busy ? "Importing…" : "Import"} <ArrowRight className="h-4 w-4" /></Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
