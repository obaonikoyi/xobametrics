import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api, { compactNumber, fullNumber } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Sparkles, ShieldCheck } from "lucide-react";

export default function SharedReport() {
  const { shareId } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get(`/reports/shared/${shareId}`); setReport(data.report); }
      catch { setError(true); }
    })();
  }, [shareId]);

  if (error) return <div className="flex min-h-screen items-center justify-center text-muted-foreground">This shared report is unavailable.</div>;
  if (!report) return <div className="mx-auto max-w-3xl p-6"><Skeleton className="h-96 rounded-xl" /></div>;

  const t = report.totals || {};
  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Activity className="h-5 w-5 text-primary" /><span className="font-display font-semibold">XobaMetrics</span>
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-500"><ShieldCheck className="h-3.5 w-3.5" /> Verified numbers</span>
        </div>
        <h1 className="mt-6 font-display text-3xl font-extrabold tracking-tight">{report.title}</h1>
        <p className="text-sm text-muted-foreground">{(report.created_at || "").slice(0, 10)}</p>

        <div className="mt-6 grid grid-cols-3 gap-3">
          {[["Reach", t.reach], ["Engagement", t.engagement], ["Followers", t.followers]].map(([l, v]) => (
            <div key={l} className="rounded-xl border border-border bg-card p-4">
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{l}</div>
              <div className="mt-1 font-mono-metric text-2xl font-bold">{compactNumber(v)}</div>
            </div>
          ))}
        </div>

        {report.summary && (
          <div className="mt-5 rounded-xl border border-primary/20 bg-primary/[0.05] p-5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-primary"><Sparkles className="h-3.5 w-3.5" /> AI Summary</div>
            <p className="mt-2 text-sm leading-relaxed">{report.summary}</p>
          </div>
        )}

        <div className="mt-5 rounded-xl border border-border bg-card">
          <div className="border-b border-border px-5 py-3 font-display font-semibold">Releases</div>
          <table className="w-full text-sm">
            <tbody>
              {(report.releases || []).map((r) => (
                <tr key={r.id} className="border-t border-border first:border-0">
                  <td className="px-5 py-3">{r.title}</td>
                  <td className="px-5 py-3 text-right font-mono-metric">{fullNumber(r.reach)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
