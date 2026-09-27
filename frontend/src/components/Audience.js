import { useEffect, useState } from "react";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Compass, Globe2 } from "lucide-react";

// One hue: these are magnitudes across categories, ranked, so the bar length
// carries the value and the label carries the identity.
const ACCENT = "#3B82F6";

const PERIODS = [{ label: "28 days", days: 28 }, { label: "90 days", days: 90 }, { label: "1 year", days: 365 }];

const STATUS_TEXT = {
  not_connected: "Connect YouTube on the Connections page to see this.",
  needs_permission: "Reconnect YouTube once on the Connections page to allow read-only Analytics.",
  no_videos: "This release has no YouTube videos.",
  too_new: "YouTube hasn't processed any days for this yet. Check back tomorrow.",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const shortDate = (d) => {
  const [y, m, day] = String(d).split("-");
  const thisYear = String(new Date().getFullYear()) === y;
  return `${Number(day)} ${MONTHS[Number(m) - 1]}${thisYear ? "" : ` ${y}`}`;
};

let regionNames;
export function countryName(code) {
  try {
    regionNames = regionNames || new Intl.DisplayNames(["en"], { type: "region" });
    return regionNames.of(code) || code;
  } catch {
    return code;
  }
}

export function flag(code) {
  if (!/^[A-Z]{2}$/.test(code || "")) return "";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

export function RankedBars({ rows, labelFor, iconFor, testId, unit = "views" }) {
  const max = Math.max(...rows.map((r) => r.views), 1);
  return (
    <ul className="mt-4 space-y-2.5" data-testid={testId}>
      {rows.map((r) => (
        <li key={labelFor(r)} title={`${labelFor(r)}: ${fullNumber(r.views)} ${unit}`}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">{iconFor && <span className="mr-1.5" aria-hidden="true">{iconFor(r)}</span>}{labelFor(r)}</span>
            <span className="shrink-0 font-mono-metric text-xs text-muted-foreground">
              <span className="font-semibold text-foreground">{(r.share * 100).toFixed(r.share < 0.1 ? 1 : 0)}%</span> · {compactNumber(r.views)}
            </span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-muted/60">
            <div className="h-2 rounded-full" style={{ width: `${Math.max((r.views / max) * 100, 1.5)}%`, background: ACCENT }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Card({ icon: Icon, title, subtitle, children, testId }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid={testId}>
      <h3 className="flex items-center gap-2 font-display text-lg font-semibold"><Icon className="h-5 w-5 text-primary" aria-hidden="true" />{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      {children}
    </div>
  );
}

function Note({ children }) {
  return <p className="mt-4 rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">{children}</p>;
}

/**
 * YouTube traffic sources and top countries, for the channel or one release.
 * A release always covers its whole life since Day 0 (up to a year).
 */
export default function Audience({ profileId, releaseId }) {
  const [days, setDays] = useState(releaseId ? 365 : 28);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!profileId) return;
    let live = true;
    setData(null);
    setError("");
    const release = releaseId ? `&release_id=${encodeURIComponent(releaseId)}` : "";
    api.get(`/youtube/audience?profile_id=${encodeURIComponent(profileId)}&days=${days}${release}`)
      .then(({ data }) => live && setData(data))
      .catch((e) => live && setError(e?.response?.data?.detail || "YouTube Analytics could not be reached. Try again later."));
    return () => { live = false; };
  }, [profileId, releaseId, days]);

  const period = data?.start ? `${shortDate(data.start)} to ${shortDate(data.end)}` : "";
  const message = error || (data && data.status !== "ok" ? STATUS_TEXT[data.status] : "");
  const loading = !data && !error;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-xl font-semibold">YouTube audience</h2>
        {!releaseId && (
          <div className="flex rounded-lg border border-border p-0.5" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.days} onClick={() => setDays(p.days)} aria-pressed={days === p.days}
                className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors",
                  days === p.days ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                {p.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card icon={Compass} title="Where views come from" testId="traffic-sources"
          subtitle={period ? `Share of YouTube views, ${period}.` : "Share of YouTube views by how people found the video."}>
          {loading && <Note>Loading from YouTube…</Note>}
          {message && <Note>{message}</Note>}
          {data?.status === "ok" && (data.traffic.length ? (
            <RankedBars rows={data.traffic} labelFor={(r) => r.source} testId="traffic-list" />
          ) : <Note>No YouTube views in this period.</Note>)}
        </Card>
        <Card icon={Globe2} title="Top countries" testId="top-countries"
          subtitle={period ? `YouTube views by country, ${period}. Top ${data?.countries?.length || ""} shown.` : "YouTube views by country."}>
          {loading && <Note>Loading from YouTube…</Note>}
          {message && <Note>{message}</Note>}
          {data?.status === "ok" && (data.countries.length ? (
            <RankedBars rows={data.countries.slice(0, 10)} labelFor={(r) => countryName(r.country)} iconFor={(r) => flag(r.country)} testId="country-list" />
          ) : <Note>No YouTube views in this period.</Note>)}
        </Card>
      </div>
    </div>
  );
}
