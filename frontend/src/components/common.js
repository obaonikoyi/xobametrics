import { compactNumber } from "@/lib/api";
import { cn } from "@/lib/utils";

export const PLATFORMS = {
  youtube: { label: "YouTube", color: "#FF0000" },
  soundcloud: { label: "SoundCloud", color: "#FF5500" },
  tiktok: { label: "TikTok", color: "#00BCD4" },
  instagram: { label: "Instagram", color: "#E1306C" },
  twitter: { label: "X / Twitter", color: "#1D9BF0" },
  csv: { label: "CSV Import", color: "#3B82F6" },
};

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
