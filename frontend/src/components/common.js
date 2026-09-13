import { compactNumber } from "@/lib/api";
import { cn } from "@/lib/utils";

export const PLATFORMS = {
  // Direct API (real OAuth)
  youtube: { label: "YouTube", color: "#FF0000", method: "api" },
  soundcloud: { label: "SoundCloud", color: "#FF5500", method: "api" },
  tiktok: { label: "TikTok", color: "#00BCD4", method: "api" },
  instagram: { label: "Instagram", color: "#E1306C", method: "api" },
  twitter: { label: "X / Twitter", color: "#1D9BF0", method: "api" },
  // Import via export / CSV
  spotify: { label: "Spotify", color: "#1DB954", method: "export" },
  apple_music: { label: "Apple Music", color: "#FA243C", method: "export" },
  youtube_music: { label: "YouTube Music", color: "#FF0000", method: "export" },
  amazon_music: { label: "Amazon Music", color: "#25D1DA", method: "export" },
  pandora: { label: "Pandora", color: "#3668FF", method: "export" },
  deezer: { label: "Deezer", color: "#A238FF", method: "export" },
  tidal: { label: "TIDAL", color: "#5B7A9A", method: "export" },
  iheartradio: { label: "iHeartRadio", color: "#C6002B", method: "export" },
  qobuz: { label: "Qobuz", color: "#0061FF", method: "export" },
  bandcamp: { label: "Bandcamp", color: "#629AA9", method: "export" },
  beatport: { label: "Beatport", color: "#00C46A", method: "export" },
  audiomack: { label: "Audiomack", color: "#FF8800", method: "export" },
  boomplay: { label: "Boomplay", color: "#E72C30", method: "export" },
  csv: { label: "CSV Import", color: "#3B82F6", method: "export" },
};

export const PLATFORM_DESC = {
  youtube: "Video & Shorts stats via Data API (batchGetStats).",
  soundcloud: "Track plays & engagement (OAuth 2.1 + PKCE).",
  tiktok: "Promo reach via TikTok API — pending app review.",
  instagram: "Reels & posts via Graph API — pending review.",
  twitter: "Post impressions & engagement.",
  spotify: "Spotify for Artists export (creator-owned CSV only — policy).",
  apple_music: "Apple Music for Artists export.",
  youtube_music: "YouTube Music / Studio export.",
  amazon_music: "Amazon Music for Artists export.",
  pandora: "Pandora AMP export.",
  deezer: "Deezer for Creators export.",
  tidal: "TIDAL artist export.",
  iheartradio: "iHeartRadio spins export.",
  qobuz: "Qobuz streams export.",
  bandcamp: "Bandcamp stats export.",
  beatport: "Beatport sales & plays export.",
  audiomack: "Audiomack for Creators export.",
  boomplay: "Boomplay for Artists export.",
  csv: "Universal fallback — upload any platform export.",
};

// platforms that support real OAuth connect vs. those ingested via CSV export
export const API_PLATFORMS = Object.keys(PLATFORMS).filter((k) => PLATFORMS[k].method === "api");
export const EXPORT_PLATFORMS = Object.keys(PLATFORMS).filter((k) => PLATFORMS[k].method === "export" && k !== "csv");

export function monogram(label) {
  const words = (label || "?").replace(/[^A-Za-z0-9 ]/g, "").split(" ").filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return (label || "?").slice(0, 2).toUpperCase();
}

export function PlatformTile({ platform, className }) {
  const p = PLATFORMS[platform] || { label: platform, color: "#3B82F6" };
  return (
    <span
      data-testid={`platform-tile-${platform}`}
      className={cn("flex items-center justify-center rounded-lg font-display text-sm font-bold text-white", className)}
      style={{ backgroundColor: p.color }}
    >
      {monogram(p.label)}
    </span>
  );
}

export function PlatformBadge({ platform, className }) {
  const p = PLATFORMS[platform] || { label: platform, color: "#3B82F6" };
  return (
    <span
      data-testid={`platform-badge-${platform}`}
      className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold", className)}
      style={{ backgroundColor: `${p.color}1f`, color: p.color, border: `1px solid ${p.color}40` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: p.color }} />
      {p.label}
    </span>
  );
}

export function StatCard({ label, value, sub, icon: Icon, accent = "#3B82F6", testId }) {
  return (
    <div
      data-testid={testId}
      className="group rounded-xl border border-border bg-card p-5 transition-all duration-200 hover:border-primary/40 hover:shadow-md"
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</span>
        {Icon && (
          <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ backgroundColor: `${accent}1f`, color: accent }}>
            <Icon className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-3 font-mono-metric text-3xl font-bold tracking-tight">{typeof value === "number" ? compactNumber(value) : value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function Freshness({ date, className }) {
  if (!date) return null;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground", className)} data-testid="freshness-indicator">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      Last synced {date}
    </span>
  );
}

export const METRIC_OPTIONS = [
  { value: "reach", label: "Reach (views + plays)" },
  { value: "views", label: "Views" },
  { value: "plays", label: "Plays / Streams" },
  { value: "engagement", label: "Engagement" },
  { value: "likes", label: "Likes" },
  { value: "followers", label: "Followers" },
];
