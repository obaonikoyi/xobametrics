import { compactNumber, fullNumber } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { ArrowDownRight, ArrowUpRight, Flame, Trophy, Minus } from "lucide-react";

// One hue for the whole momentum view: the bars are the daily gain, the line
// is its 7-day average - two forms of the same measure on one axis.
const ACCENT = "#3B82F6";
const GRID = "hsl(var(--border))";
const AXIS = "hsl(var(--muted-foreground))";

const shortDate = (d) => {
  const [, m, day] = String(d).split("-");
  return `${Number(day)} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1]}`;
};

function Panel({ title, subtitle, children, className, testId }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)} data-testid={testId}>
      <h3 className="font-display text-lg font-semibold">{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      {children}
    </div>
  );
}

function Empty({ children }) {
  return <p className="mt-4 rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">{children}</p>;
}

function GainTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold">{shortDate(label)}</div>
      <div className="mt-1 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: ACCENT, opacity: 0.55 }} />
        <span className="text-muted-foreground">New that day</span>
        <span className="ml-auto font-mono-metric font-semibold">{point.value == null ? "No reading" : fullNumber(point.value)}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-2">
        <span className="h-0.5 w-2.5 rounded" style={{ background: ACCENT }} />
        <span className="text-muted-foreground">7-day average</span>
        <span className="ml-auto font-mono-metric font-semibold">{point.avg7 == null ? "—" : fullNumber(point.avg7)}</span>
      </div>
    </div>
  );
}

// Every calendar day from the first to the last reading, so a day without a
// reading shows as a gap instead of the neighbouring days closing up.
function everyDay(points) {
  if (points.length < 2) return points;
  const byDay = Object.fromEntries(points.map((p) => [p.date, p]));
  const out = [];
  const end = new Date(`${points[points.length - 1].date}T00:00:00Z`);
  for (let d = new Date(`${points[0].date}T00:00:00Z`); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    out.push(byDay[key] || { date: key, value: null, avg7: null });
  }
  return out;
}

export function DailyGainsChart({ daily, title = "New views & plays per day", testId = "daily-gains", className }) {
  const days = everyDay(daily);
  return (
    <Panel title={title} subtitle="Growth between days we have readings for. Days without a reading are left blank, not counted as zero." testId={testId} className={className}>
      {daily.length < 2 ? (
        <Empty>Not enough daily readings yet. This fills in as the daily sync runs.</Empty>
      ) : (
        <>
          <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground" aria-hidden="true">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: ACCENT, opacity: 0.55 }} />New that day</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 rounded" style={{ background: ACCENT }} />7-day average</span>
          </div>
          <div className="mt-2 h-64" role="img" aria-label={`${title}: bar chart of daily gains with a 7-day average line`}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={days} margin={{ left: 4, right: 8, top: 4 }} barCategoryGap={2}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="date" stroke={AXIS} fontSize={11} tickFormatter={shortDate} minTickGap={36} tickLine={false} />
                <YAxis stroke={AXIS} fontSize={11} tickFormatter={compactNumber} width={44} tickLine={false} axisLine={false} />
                <Tooltip content={<GainTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.4)" }} />
                <Bar dataKey="value" fill={ACCENT} fillOpacity={0.55} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                <Line dataKey="avg7" stroke={ACCENT} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--card))" }} connectNulls={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Panel>
  );
}

export function Delta({ change, label }) {
  if (change == null) return <span className="text-xs text-muted-foreground">{label}</span>;
  const pct = Math.round(change * 100);
  const Icon = pct > 0 ? ArrowUpRight : pct < 0 ? ArrowDownRight : Minus;
  const tone = pct > 0 ? "text-emerald-500" : pct < 0 ? "text-rose-500" : "text-muted-foreground";
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span className={cn("inline-flex items-center gap-0.5 font-semibold", tone)}>
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />{pct > 0 ? "+" : ""}{pct}%
      </span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}

export function WeekTile({ week }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="week-tile">
      <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">New views & plays this week</div>
      {week ? (
        <>
          <div className="mt-1.5 font-mono-metric text-3xl font-bold">{compactNumber(week.this_week)}</div>
          <div className="mt-1.5">
            <Delta change={week.change}
              label={week.change == null ? "Not enough readings to compare with last week" : `vs ${compactNumber(week.last_week)} last week`} />
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">7 days to {shortDate(week.through)}</div>
        </>
      ) : <div className="mt-2 text-sm text-muted-foreground">No daily readings yet.</div>}
    </div>
  );
}

export function TakingOff({ alerts, onOpen }) {
  return (
    <Panel title="Taking off" subtitle="Songs whose latest day beat their usual day at least twice over." testId="taking-off">
      {alerts.length === 0 ? (
        <Empty>Nothing unusual right now. Songs show here when a day is at least 2× their usual.</Empty>
      ) : (
        <ul className="mt-3 space-y-2">
          {alerts.map((a) => (
            <li key={a.release_id}>
              <button onClick={() => onOpen?.(a.release_id)} className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-primary/40">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-500"><Flame className="h-4 w-4" aria-hidden="true" /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{a.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {fullNumber(a.gained)} on {shortDate(a.date)} · usually about {fullNumber(a.usual)} a day
                  </div>
                </div>
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 font-mono-metric text-xs font-semibold text-emerald-600 dark:text-emerald-400">{a.ratio}×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function Milestones({ milestones, onOpen, title = "Milestones", subtitle = "Totals each song crossed in the last 60 days." }) {
  return (
    <Panel title={title} subtitle={subtitle} testId="milestones">
      {milestones.length === 0 ? (
        <Empty>No new milestones yet. They appear when a song passes 1K, 10K, 100K or 1M.</Empty>
      ) : (
        <ul className="mt-3 space-y-2">
          {milestones.map((m) => (
            <li key={`${m.release_id || ""}-${m.threshold}`}>
              <button onClick={() => m.release_id && onOpen?.(m.release_id)} className="flex w-full items-center gap-3 rounded-lg border border-border p-2.5 text-left transition-colors hover:border-primary/40">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-500/10 text-amber-500"><Trophy className="h-4 w-4" aria-hidden="true" /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{m.title ? `${m.title} passed ` : "Passed "}{compactNumber(m.threshold)}</div>
                  <div className="text-xs text-muted-foreground">Day {m.day} · {shortDate(m.date)}</div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function BenchmarkTile({ day, mark }) {
  const hasValue = mark?.value != null;
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">By Day {day}</div>
      <div className="mt-1.5 font-mono-metric text-2xl font-bold">{hasValue ? compactNumber(mark.value) : "—"}</div>
      <div className="mt-1.5 text-xs">
        {!hasValue && <span className="text-muted-foreground">No reading on Day {day} yet</span>}
        {hasValue && mark.index == null && <span className="text-muted-foreground">Needs 2 earlier releases read on Day {day} to compare</span>}
        {hasValue && mark.index != null && (
          <Delta change={mark.index - 1} label={`vs your usual ${compactNumber(mark.usual)} (${mark.compared_with} earlier releases)`} />
        )}
      </div>
    </div>
  );
}

export function Benchmarks({ benchmark }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="benchmarks">
      <BenchmarkTile day={7} mark={benchmark?.day7} />
      <BenchmarkTile day={28} mark={benchmark?.day28} />
    </div>
  );
}

const pct = (v) => `${(v * 100).toFixed(1)}%`;
const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// A fixed-width slot on every row, so the numbers stay lined up.
function AboveUsual({ on }) {
  return (
    <span className="ml-1 inline-flex w-4 justify-center align-middle">
      {on && <ArrowUpRight className="h-3.5 w-3.5 text-emerald-500" aria-label="above your usual" />}
    </span>
  );
}

export function FanQuality({ quality, onOpen }) {
  const rows = [...quality].sort((a, b) => b.engagement_rate - a.engagement_rate);
  const usualRate = median(quality.map((q) => q.engagement_rate));
  const usualFans = median(quality.map((q) => q.followers_per_1k));
  return (
    <Panel title="Engagement & fans won" subtitle="Per song. ↗ marks songs above your own middle value. Songs with fewer than 100 views & plays are left out." testId="fan-quality">
      {rows.length === 0 ? (
        <Empty>Not enough views & plays yet to compare songs.</Empty>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-2 pr-3 text-left font-semibold">Song</th>
              <th className="px-3 py-2 text-right font-semibold">Engagement rate</th>
              <th className="py-2 pl-3 text-right font-semibold">New followers per 1K</th>
            </tr></thead>
            <tbody>
              {rows.map((q) => (
                <tr key={q.release_id} className="cursor-pointer border-t border-border hover:bg-muted/40" onClick={() => onOpen?.(q.release_id)}>
                  <td className="max-w-[14rem] truncate py-2.5 pr-3 font-medium">{q.title}</td>
                  <td className="px-3 py-2.5 text-right font-mono-metric">
                    {pct(q.engagement_rate)}<AboveUsual on={q.engagement_rate > usualRate} />
                  </td>
                  <td className="py-2.5 pl-3 text-right font-mono-metric">
                    {q.followers_per_1k.toFixed(1)}<AboveUsual on={q.followers_per_1k > usualFans} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr className="border-t border-border text-xs text-muted-foreground">
              <td className="py-2 pr-3">Your usual (middle value)</td>
              <td className="px-3 py-2 text-right font-mono-metric">{pct(usualRate)}<AboveUsual on={false} /></td>
              <td className="py-2 pl-3 text-right font-mono-metric">{usualFans.toFixed(1)}<AboveUsual on={false} /></td>
            </tr></tfoot>
          </table>
        </div>
      )}
    </Panel>
  );
}
