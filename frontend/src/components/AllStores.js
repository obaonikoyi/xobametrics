import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PLATFORMS } from "@/components/common";
import { RankedBars, countryName, flag } from "@/components/Audience";
import { Button } from "@/components/ui/button";
import { Globe2, Store, Upload } from "lucide-react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (d) => `${MONTHS[Number(String(d).slice(5, 7)) - 1]} ${String(d).slice(0, 4)}`;

function Card({ icon: Icon, title, subtitle, children, testId }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid={testId}>
      <h3 className="flex items-center gap-2 font-display text-lg font-semibold"><Icon className="h-5 w-5 text-primary" aria-hidden="true" />{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      {children}
    </div>
  );
}

/**
 * Streams by country and by store across every store, from uploaded
 * distributor reports. On the dashboard, with no report yet, it points to the
 * guide instead; on a release page it stays out of the way.
 */
export default function AllStores({ profileId, releaseId }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!profileId) return;
    let live = true;
    const release = releaseId ? `&release_id=${encodeURIComponent(releaseId)}` : "";
    api.get(`/imports/countries?profile_id=${encodeURIComponent(profileId)}&months=12${release}`)
      .then(({ data }) => live && setData(data))
      .catch(() => live && setData(null));
    return () => { live = false; };
  }, [profileId, releaseId]);

  if (!data) return null;
  if (data.status !== "ok") {
    if (releaseId) return null;
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-border p-5" data-testid="all-stores-empty">
        <div>
          <div className="font-semibold">See countries and stores beyond YouTube</div>
          <p className="mt-0.5 text-sm text-muted-foreground">Upload your distributor's report (DistroKid, TuneCore, CD Baby…) to add Spotify, Apple Music, Boomplay, Audiomack and more.</p>
        </div>
        <Button variant="outline" className="gap-2" onClick={() => navigate("/guide")}><Upload className="h-4 w-4" /> How to get it</Button>
      </div>
    );
  }

  const period = `${monthLabel(data.first_month)} to ${monthLabel(data.last_month)}`;
  const label = (p) => (p === "csv" ? "Other stores" : PLATFORMS[p]?.label || p);
  const units = (rows) => rows.map((r) => ({ ...r, views: r.units }));
  return (
    <div className="space-y-3">
      <h2 className="font-display text-xl font-semibold">All stores, from your distributor</h2>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card icon={Globe2} title="Streams by country" testId="all-stores-countries"
          subtitle={`Streams and sales in every store, ${period}. From your uploaded reports, so the latest months may be missing.`}>
          <RankedBars rows={units(data.countries.slice(0, 10))} labelFor={(r) => (r.country === "??" ? "Unknown" : countryName(r.country))}
            iconFor={(r) => flag(r.country)} testId="all-stores-country-list" unit="streams" />
        </Card>
        <Card icon={Store} title="Streams by store" testId="all-stores-stores" subtitle={`Same period, ${period}.`}>
          <RankedBars rows={units(data.stores)} labelFor={(r) => label(r.platform)} testId="all-stores-store-list" unit="streams" />
        </Card>
      </div>
    </div>
  );
}
