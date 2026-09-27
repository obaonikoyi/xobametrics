import { useRef, useState } from "react";
import api, { compactNumber, formatApiErrorDetail } from "@/lib/api";
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
import { UploadCloud, ArrowRight, BookOpen } from "lucide-react";
import { Link } from "react-router-dom";
import { PLATFORMS as REGISTRY, PlatformBadge } from "@/components/common";

const CANONICAL = ["date", "plays", "views", "likes", "comments", "shares", "followers"];
// ordered platform options for the picker (API first, then DSP exports, then generic)
const PLATFORM_OPTS = [
  ...["soundcloud", "youtube", "tiktok", "instagram", "twitter"],
  ...["spotify", "apple_music", "youtube_music", "amazon_music", "pandora", "deezer", "tidal", "iheartradio", "qobuz", "bandcamp", "beatport", "audiomack", "boomplay"],
  "csv",
].map((k) => [k, k === "csv" ? "Other / Generic" : (REGISTRY[k]?.label || k)]);

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function monthSpan(first, last) {
  if (!first || !last) return "—";
  const name = (d) => MONTH_NAMES[Number(d.slice(5, 7)) - 1];
  const [fy, ly] = [first.slice(0, 4), last.slice(0, 4)];
  if (first.slice(0, 7) === last.slice(0, 7)) return `${name(first)} ${fy}`;
  return fy === ly ? `${name(first)}–${name(last)} ${ly}` : `${name(first)} ${fy}–${name(last)} ${ly}`;
}

export default function CsvUploadDialog({ profileId, onImported, trigger, defaultPlatform }) {
  const initialPlatform = defaultPlatform || "soundcloud";
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [parsed, setParsed] = useState(null);
  const [mapping, setMapping] = useState({});
  const [meta, setMeta] = useState({ platform: initialPlatform, title: "", date: "", content_type: "track" });
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [reportFile, setReportFile] = useState(null);
  const [artists, setArtists] = useState([]);
  const fileRef = useRef();

  const reset = () => {
    setStep(1); setParsed(null); setMapping({}); setReport(null); setReportFile(null); setArtists([]);
    setMeta({ platform: initialPlatform, title: "", date: "", content_type: "track" });
  };

  const form = (file, extra = {}) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("profile_id", profileId);
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
    return fd;
  };
  const multipart = { headers: { "Content-Type": "multipart/form-data" } };

  const handleFile = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      // First ask what the file is: a distributor report is imported whole;
      // anything else is one song's daily numbers, mapped column by column.
      const { data: detected } = await api.post("/imports/preview", form(file), multipart);
      if (detected.kind === "sales_report") {
        setReport(detected);
        setReportFile(file);
        setArtists(detected.artists.length > 1 ? [detected.artists[0]] : detected.artists);
        setStep("report");
        return;
      }
      if (!file.name.toLowerCase().endsWith(".csv")) {
        toast.error("That file isn't a distributor report. Day-by-day files need to be .csv.");
        return;
      }
      const { data } = await api.post("/csv/upload", form(file), multipart);
      setParsed(data);
      setMapping(data.suggested_mapping || {});
      const firstDate = data.preview?.[0]?.date || "";
      setMeta((m) => ({
        ...m, title: file.name.replace(/\.csv$/i, ""), date: firstDate,
        platform: detected.platform_hint || m.platform,
      }));
      setStep(2);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Could not read that file.");
    } finally { setBusy(false); }
  };

  const importReport = async () => {
    if (!artists.length) { toast.error("Choose at least one artist."); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/imports/commit", form(reportFile, { artists: JSON.stringify(artists) }), multipart);
      const added = data.new_releases.length;
      toast.success(`Imported ${data.songs} song${data.songs === 1 ? "" : "s"}${added ? `, ${added} new` : ""}.`);
      setOpen(false); reset();
      onImported && onImported();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Import failed.");
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
          <DialogTitle className="font-display">
            {step === "report" ? "Distributor report" : `Upload a file${step === 2 ? " — map & confirm" : ""}`}
          </DialogTitle>
          <DialogDescription>
            {step === "report"
              ? "Every song, store and country in this file. Uploading the same months again replaces them."
              : "A distributor report (DistroKid, TuneCore, CD Baby…) or one song's export from Spotify for Artists and others."}
          </DialogDescription>
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
            <p className="mt-3 font-medium">{busy ? "Reading…" : "Drop a file or click to browse"}</p>
            <p className="mt-1 text-xs text-muted-foreground">.csv, .tsv or .txt — we recognise the format automatically.</p>
            <input ref={fileRef} type="file" accept=".csv,.tsv,.txt" hidden data-testid="csv-file-input" onChange={(e) => handleFile(e.target.files?.[0])} />
          </div>
        )}
        {step === 1 && (
          <Link to="/guide" onClick={() => setOpen(false)} className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline">
            <BookOpen className="h-3.5 w-3.5" /> Where do I get this file?
          </Link>
        )}

        {step === "report" && report && (
          <div className="space-y-4" data-testid="report-preview">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[["Songs", report.songs.length], ["Streams & sales", compactNumber(report.units)], ["Countries", report.countries],
                ["Months", monthSpan(report.first_month, report.last_month)]].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-border p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</div>
                  <div className="mt-1 font-mono-metric text-sm font-semibold">{value}</div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {report.stores.filter((p) => p !== "csv").map((p) => <PlatformBadge key={p} platform={p} />)}
              {report.stores.includes("csv") && <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-semibold text-muted-foreground">Other stores</span>}
            </div>
            {report.artists.length > 1 && (
              <div>
                <Label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Artists to import</Label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {report.artists.map((a) => (
                    <label key={a} className="flex cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm">
                      <input type="checkbox" checked={artists.includes(a)}
                        onChange={(e) => setArtists((cur) => e.target.checked ? [...cur, a] : cur.filter((x) => x !== a))} />
                      {a || "(no artist name)"}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="rounded-lg border border-border">
              <div className="border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">Songs in this file</div>
              <ul className="max-h-48 divide-y divide-border overflow-auto text-sm">
                {report.songs.filter((s) => artists.includes(s.artist)).slice(0, 50).map((s) => (
                  <li key={`${s.artist}-${s.title}`} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span className="min-w-0 truncate">{s.title}</span>
                    <span className="shrink-0 font-mono-metric text-xs text-muted-foreground">{compactNumber(s.units)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <p className="text-xs text-muted-foreground">
              Songs already in XobaMetrics are matched by title. New ones start with the first month that has sales as
              their Day 0 — set the real release date on each release page.
              {Object.values(report.skipped || {}).some(Boolean) &&
                ` ${Object.values(report.skipped).reduce((a, b) => a + b, 0)} row(s) couldn't be read and will be skipped.`}
            </p>
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
                  <SelectContent>{PLATFORM_OPTS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
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
          {step === "report" && <Button variant="ghost" onClick={reset}>Back</Button>}
          {step === "report" && <Button onClick={importReport} disabled={busy} data-testid="report-import-button" className="gap-2">{busy ? "Importing…" : "Import"} <ArrowRight className="h-4 w-4" /></Button>}
          {step === 2 && <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>}
          {step === 2 && <Button onClick={commit} disabled={busy} data-testid="csv-commit-button" className="gap-2">{busy ? "Importing…" : "Import"} <ArrowRight className="h-4 w-4" /></Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
