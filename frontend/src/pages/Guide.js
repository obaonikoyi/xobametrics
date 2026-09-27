import { useState } from "react";
import { useNavigate } from "react-router-dom";
import CsvUploadDialog from "@/components/CsvUploadDialog";
import { PlatformTile } from "@/components/common";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ChevronDown, Info, PlugZap, Upload, CircleSlash } from "lucide-react";

// How to get each app's numbers into XobaMetrics. Steps marked `check` were
// gathered from the apps' help pages but not confirmed by clicking through
// the live product, so the page says to look for a similarly named button.
const DISTRIBUTORS = [
  {
    key: "distrokid", name: "DistroKid", tile: "csv", format: ".tsv file",
    gives: "Every song, every store (Spotify, Apple Music, Boomplay, Audiomack, TikTok…) and every country, by month.",
    steps: [
      "Sign in at distrokid.com and open the Bank page (distrokid.com/bank).",
      "Scroll down and click SEE EXCRUCIATING DETAIL.",
      "Optionally filter by dates, stores or releases.",
      "Click Download (top right, next to Display). You get a .tsv file.",
      "Upload that file here as it is.",
    ],
    notes: ["These are earnings reports, so the newest month is usually 2–3 months behind.", "Files over 50,000 rows need a date filter first."],
  },
  {
    key: "tunecore", name: "TuneCore", tile: "csv", format: ".csv file",
    gives: "Every song by store and country of sale, by month.",
    steps: [
      "Sign in and go to Money & Analytics → Sales Reports.",
      "Click Download Monthly Sales Reports, choose By Reporting Period, and click the month's file. Or filter My Sales and click Download This Report.",
      "Upload the .csv here.",
    ],
    notes: ["Monthly files arrive about 2 months after the sales."],
  },
  {
    key: "cdbaby", name: "CD Baby", tile: "csv", format: "tab-separated .txt file",
    gives: "Songs by store and country, by month.",
    steps: [
      "Go to Sales & Reports → Sales & Accounting.",
      "At the bottom left choose Monthly, Yearly or Lifetime Sales Reports, then Digital Distribution.",
      "Click Download (or Request Report). You get a Digital Distribution Details .txt file.",
      "Upload the .txt here as it is.",
    ],
    check: true,
  },
  {
    key: "ditto", name: "Ditto", tile: "csv", format: ".csv file",
    gives: "Songs by store and country, by month.",
    steps: [
      "Go to Royalties in the top menu and scroll to the bottom.",
      "Click Export, choose stores, countries and dates.",
      "Small files download straight away; big ones are emailed to you. Upload the .csv here.",
    ],
    notes: ["Wait until a month has closed: royalties keep being added during the month."],
    check: true,
  },
  {
    key: "symphonic", name: "Symphonic", tile: "csv", format: ".csv file",
    gives: "Songs by store and territory.",
    steps: ["In SymphonicMS open Revenue → Royalty Summary.", "Click Earnings Report for one or more months. Upload the .csv here."],
    check: true,
  },
  {
    key: "awal", name: "AWAL", tile: "csv", format: ".csv inside a .zip",
    gives: "Songs by store and country, by statement period.",
    steps: ["In AWAL Workstation open Accounting → Statements Download.", "Unzip the download and upload each .csv inside it."],
    check: true,
  },
];

const PLATFORMS = [
  {
    key: "spotify", name: "Spotify for Artists", tile: "spotify", format: ".csv file (computer only)",
    gives: "Streams over time for one song, or listeners, streams and followers for you. Countries and \"where streams come from\" can't be downloaded — get countries from your distributor's file instead.",
    steps: [
      "On a computer, open artists.spotify.com.",
      "For one song: Music → Songs → pick the song, then click the download icon next to its streams chart.",
      "For you as an artist: open Audience and click the download icon on the timeline.",
      "Set the date range before downloading (up to the last 12 months or a custom range).",
      "Upload the .csv here and choose the song it belongs to.",
    ],
    notes: ["One song per file."],
  },
  {
    key: "amazon_music", name: "Amazon Music for Artists", tile: "amazon_music", format: ".csv file (web only)",
    gives: "Streams and listeners over time.",
    steps: ["Open artists.amazonmusic.com in a browser.", "Open any report page, choose the dates, and click the download icon.", "Upload the .csv here."],
    check: true,
  },
  {
    key: "tiktok", name: "TikTok Studio", tile: "tiktok", format: ".csv or .xlsx (computer only)",
    gives: "Views, likes, comments and shares for your own posts.",
    steps: ["On a computer open tiktok.com/tiktokstudio → Analytics.", "Choose the dates and click Download data, then CSV.", "Upload the .csv here."],
    notes: ["TikTok only keeps 60 days, so download it regularly."],
    check: true,
  },
  {
    key: "instagram", name: "Instagram & Facebook", tile: "instagram", format: ".csv file",
    gives: "Reach, views, likes, comments, saves and shares per post.",
    steps: ["On a computer open business.facebook.com → Insights → Content.", "Click Export data (next to the date picker), choose the account and dates, then CSV.", "Upload the .csv here."],
    notes: ["The Instagram app itself has no download; it has to be Meta Business Suite."],
    check: true,
  },
];

const CONNECT = [
  { key: "youtube", name: "YouTube", tile: "youtube", text: "Connect it once on the Connections page: daily views, history from each song's Day 0, where views come from and top countries arrive automatically." },
  { key: "soundcloud", name: "SoundCloud", tile: "soundcloud", text: "Connect it on the Connections page for plays, likes, reposts and comments. SoundCloud has no download for its countries or sources." },
];

const NO_EXPORT = [
  ["Apple Music for Artists & Shazam", "No download button. Your distributor's file covers Apple Music streams and countries."],
  ["Audiomack", "Only earnings statements download, not stats. Your distributor's file covers Audiomack."],
  ["Boomplay", "No download. Your distributor's file covers Boomplay, including countries."],
  ["TIDAL", "No download. Your distributor's file covers TIDAL."],
  ["UnitedMasters", "Statements are PDF only, which can't be read yet."],
];

function GuideCard({ item, open, onToggle }) {
  return (
    <div className="rounded-xl border border-border bg-card" data-testid={`guide-${item.key}`}>
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 p-4 text-left">
        {item.tile === "csv" ? (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary font-display text-sm font-bold" aria-hidden="true">
            {item.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
          </span>
        ) : <PlatformTile platform={item.tile} className="h-10 w-10 shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{item.name}</div>
          <div className="text-xs text-muted-foreground">{item.format}</div>
        </div>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      {open && (
        <div className="border-t border-border px-4 pb-4 pt-3 text-sm">
          <p className="text-muted-foreground"><span className="font-medium text-foreground">What you get: </span>{item.gives}</p>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5">
            {item.steps.map((s) => <li key={s}>{s}</li>)}
          </ol>
          {(item.notes || []).map((n) => <p key={n} className="mt-2 text-xs text-muted-foreground">• {n}</p>)}
          {item.check && (
            <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-muted/50 p-2.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Button names change from time to time. If you can't find one, look for a similarly named Export or Download option.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function Guide() {
  const { activeProfile } = useWorkspace();
  const navigate = useNavigate();
  const [open, setOpen] = useState("distrokid");
  const toggle = (key) => setOpen((k) => (k === key ? null : key));

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Get your data in</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Spotify, Apple Music and most stores don't let other apps read your numbers directly. The quickest way to see
          everything in one place is your <span className="font-medium text-foreground">distributor's report</span>: one
          file with every song, store and country. Download it, then upload it here.
        </p>
        {activeProfile && (
          <div className="mt-4 flex flex-wrap gap-2">
            <CsvUploadDialog profileId={activeProfile.id} onImported={() => navigate("/dashboard")}
              trigger={<Button className="gap-2" data-testid="guide-upload"><Upload className="h-4 w-4" /> Upload a file</Button>} />
            <Button variant="outline" className="gap-2" onClick={() => navigate("/connections")}><PlugZap className="h-4 w-4" /> Connections</Button>
          </div>
        )}
      </div>

      <section>
        <h2 className="font-display text-lg font-semibold">Start here: your distributor</h2>
        <p className="mt-1 text-xs text-muted-foreground">Covers every store at once, including Boomplay, Audiomack and TIDAL, with countries. Uploading the same months again replaces them, never doubles them.</p>
        <div className="mt-3 grid gap-3">
          {DISTRIBUTORS.map((d) => <GuideCard key={d.key} item={d} open={open === d.key} onToggle={() => toggle(d.key)} />)}
        </div>
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">Connect instead of downloading</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {CONNECT.map((c) => (
            <button key={c.key} onClick={() => navigate("/connections")} className="flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40">
              <PlatformTile platform={c.tile} className="h-10 w-10 shrink-0" />
              <div><div className="font-semibold">{c.name}</div><p className="mt-1 text-xs text-muted-foreground">{c.text}</p></div>
            </button>
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">Apps with their own download</h2>
        <p className="mt-1 text-xs text-muted-foreground">Useful for day-by-day numbers your distributor doesn't have.</p>
        <div className="mt-3 grid gap-3">
          {PLATFORMS.map((p) => <GuideCard key={p.key} item={p} open={open === p.key} onToggle={() => toggle(p.key)} />)}
        </div>
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">No download available</h2>
        <ul className="mt-3 divide-y divide-border rounded-xl border border-border bg-card">
          {NO_EXPORT.map(([name, text]) => (
            <li key={name} className="flex items-start gap-3 p-4 text-sm">
              <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div><span className="font-medium">{name}.</span> <span className="text-muted-foreground">{text}</span></div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
