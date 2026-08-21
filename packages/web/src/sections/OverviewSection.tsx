import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, Gauge } from 'lucide-react';
import { ApiError, getLatestRun, listBrandShares, listSpotEfficiency } from '../api/client';
import type { BrandShare, GrpRunSummary, Project, SpotEfficiency } from '../api/contracts';

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value);
}

// Moved from App.tsx's "Projects" tab, which used to double as the
// dashboard — PRODUCT_ROADMAP.md's Overview row always described this as
// its own screen ("Executive GRP/SOV dashboard"), separate from project
// list/management. Not duplicated: App.tsx's Projects tab no longer fetches
// or renders any of this.
function BrandShareRow({ share, maxGrp }: { share: BrandShare; maxGrp: number }) {
  const width = maxGrp ? `${Math.max((share.totalGrps / maxGrp) * 100, 3)}%` : '3%';
  // Split the bar itself by TV/Cable TV/Radio GRP share, not just report the
  // numbers in the caption — tvGrps/cableTvGrps/radioGrps summed to
  // totalGrps, this is the first place any of them gets rendered anywhere.
  const mediumsPresent = [share.tvGrps, share.cableTvGrps, share.radioGrps].filter((g) => g > 0).length;
  const isMixedMedia = mediumsPresent >= 2;
  const tvShare = share.totalGrps > 0 ? (share.tvGrps / share.totalGrps) * 100 : 100;
  const cableTvShare = share.totalGrps > 0 ? (share.cableTvGrps / share.totalGrps) * 100 : 0;
  const radioShare = share.totalGrps > 0 ? (share.radioGrps / share.totalGrps) * 100 : 0;
  // Solid-bar case: pick whichever single medium actually has GRPs, rather
  // than assuming TV — a Radio-only or Cable-TV-only brand shouldn't render
  // in the default TV green.
  const soloColor = share.cableTvGrps > 0 ? 'var(--violet)' : share.radioGrps > 0 ? 'var(--blue)' : undefined;
  return (
    <div className="brand-row">
      <div className="brand-line">
        <span>{share.brand}</span>
        <span className="brand-share-metrics">
          <strong>{share.sov.toFixed(1)}% SOV</strong>
          {/* SOE tracks spend, not GRPs — a brand can lead SOV while trailing
              SOE (or vice versa) since spend counts every uploaded row,
              matched or not. Only shown once spend data exists for this
              category, so an all-null-cost project doesn't render a
              meaningless "0.0% SOE" on every brand. */}
          {share.totalSpend > 0 ? <strong className="soe-value">{share.soe.toFixed(1)}% SOE</strong> : null}
        </span>
      </div>
      <div className="bar-track" aria-label={`${share.brand} GRP contribution`}>
        {isMixedMedia ? (
          <div className="bar-fill split" style={{ width }}>
            <div className="bar-fill-tv" style={{ width: `${tvShare}%` }} />
            <div className="bar-fill-cable-tv" style={{ width: `${cableTvShare}%` }} />
            <div className="bar-fill-radio" style={{ width: `${radioShare}%` }} />
          </div>
        ) : (
          <div className="bar-fill" style={{ width, background: soloColor }} />
        )}
      </div>
      <small>
        {share.spots} spots | {share.totalGrps.toFixed(1)} GRPs
        {isMixedMedia
          ? ` (TV ${share.tvGrps.toFixed(1)}${share.cableTvGrps > 0 ? ` · Cable TV ${share.cableTvGrps.toFixed(1)}` : ''} · Radio ${share.radioGrps.toFixed(1)})`
          : ''}
        {share.avgRating !== null ? ` | avg rating ${share.avgRating.toFixed(2)}` : ''}
        {share.totalSpend > 0 ? ` | spend ${formatNumber(share.totalSpend)}` : ''}
      </small>
    </div>
  );
}

export default function OverviewSection({ project }: { project: Project | null }) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [spotEfficiency, setSpotEfficiency] = useState<SpotEfficiency[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      if (latestRun) {
        const [shares, efficiency] = await Promise.all([
          listBrandShares(projectId, latestRun.runId),
          listSpotEfficiency(projectId, latestRun.runId),
        ]);
        setBrandShares(shares);
        setSpotEfficiency(efficiency);
      } else {
        setBrandShares([]);
        setSpotEfficiency([]);
      }
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the overview.');
      setRun(null);
      setBrandShares([]);
      setSpotEfficiency([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setRun(null);
      setBrandShares([]);
      setSpotEfficiency([]);
    }
  }, [project, refresh]);

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to see its executive dashboard.</p>
      </div>
    );
  }

  const maxGrp = Math.max(1, ...brandShares.map((share) => share.totalGrps));
  const matchedActivityPct = run && run.matchedRows + run.unmatchedRows > 0
    ? (run.matchedRows / (run.matchedRows + run.unmatchedRows)) * 100
    : null;
  // brandShares arrives sorted by totalGrps descending (both repository
  // backends sort it that way), so the first entry is already the leader.
  const leadingBrand = brandShares[0] ?? null;
  const weakBuys = spotEfficiency.filter((row) => row.isWeak);

  return (
    <>
      {loadError && <p className="inline-error">{loadError}</p>}

      {!loading && !run && !loadError && (
        <div className="panel placeholder-panel">
          <h2>No calculation yet</h2>
          <p>Go to Projects and click Calculate to generate this project's executive dashboard.</p>
        </div>
      )}

      {run && (
        <>
          <section className="metric-grid" aria-label="Executive summary">
            <div className="metric-panel">
              <span>Total GRPs</span>
              <strong>{formatNumber(run.totalGrps)}</strong>
              <small>Run generated {run.generatedAt}</small>
            </div>
            <div className="metric-panel">
              <span>Total Spots</span>
              <strong>{formatNumber(run.totalSpots)}</strong>
              <small>{run.totalBrands} brand{run.totalBrands === 1 ? '' : 's'}</small>
            </div>
            <div className="metric-panel">
              <span>Matched Activity</span>
              <strong>{matchedActivityPct !== null ? `${matchedActivityPct.toFixed(0)}%` : '—'}</strong>
              <small>{run.matchedRows} matched, {run.unmatchedRows} unmatched</small>
            </div>
            <div className="metric-panel">
              <span>Leading Brand</span>
              <strong>{leadingBrand ? leadingBrand.brand : '—'}</strong>
              <small>{leadingBrand ? `${leadingBrand.sov.toFixed(1)}% SOV` : ' '}</small>
            </div>
            <div className="metric-panel">
              <span>Total Spend</span>
              <strong>{formatNumber(run.totalSpend)}</strong>
              <small>{run.totalSpend === 0 ? 'No cost/rate column mapped yet' : ' '}</small>
            </div>
          </section>

          <section className="content-grid">
            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Brand SOV</h2>
                  <p>GRP-by-brand ranking, Share of Voice, and TV/Cable TV/Radio split</p>
                </div>
                <BarChart3 size={20} aria-hidden />
              </div>
              {brandShares.some(
                (share) => [share.tvGrps, share.cableTvGrps, share.radioGrps].filter((g) => g > 0).length >= 2,
              ) && (
                <div className="medium-split-legend">
                  <span><i className="tv" /> TV</span>
                  {brandShares.some((share) => share.cableTvGrps > 0) && (
                    <span><i className="cable-tv" /> Cable TV</span>
                  )}
                  <span><i className="radio" /> Radio</span>
                </div>
              )}
              <div className="brand-list">
                {brandShares.length === 0 && <p className="empty-state">No matched spots yet.</p>}
                {brandShares.map((share) => (
                  <BrandShareRow share={share} maxGrp={maxGrp} key={share.brandId} />
                ))}
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Weak Inventory</h2>
                  <p>
                    {weakBuys.length > 0
                      ? `${weakBuys.length} brand/station buy${weakBuys.length === 1 ? '' : 's'} flagged`
                      : 'No weak-inventory buys flagged for this run'}
                  </p>
                </div>
                <AlertTriangle size={20} aria-hidden />
              </div>
              <div className="brand-list">
                {weakBuys.length === 0 && <p className="empty-state">Nothing flagged.</p>}
                {weakBuys.slice(0, 5).map((row) => (
                  <div className="brand-row" key={`${row.brandId}-${row.station}`}>
                    <div className="brand-line">
                      <span>{row.brand} · {row.station}</span>
                      <strong>{row.grpPerSpot.toFixed(2)} GRP/spot</strong>
                    </div>
                    <small>{row.spots} spots | {row.totalGrps.toFixed(1)} GRPs total</small>
                  </div>
                ))}
                {weakBuys.length > 5 && (
                  <p className="field-hint">
                    <Gauge size={14} aria-hidden /> {weakBuys.length - 5} more on the Reports screen's Spot Efficiency panel.
                  </p>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}
