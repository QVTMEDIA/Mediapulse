import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, PieChart } from 'lucide-react';
import { ApiError, getLatestRun, listBrandShares, listSpotEfficiency } from '../api/client';
import type { BrandShare, GrpRunSummary, Project, SpotEfficiency } from '../api/contracts';
import { LimitedRows } from '../components/LimitedRows';
import { BrandSpendRow, formatNumber, HIGH_COST_MIN_SPOTS, HIGH_COST_RATIO } from './SpendIntelligenceSection';

// Moved from App.tsx's "Projects" tab, which used to double as the
// dashboard — PRODUCT_ROADMAP.md's Overview row always described this as
// its own screen ("Executive GRP/SOV dashboard"), separate from project
// list/management. Not duplicated: App.tsx's Projects tab no longer fetches
// or renders any of this. Only shows SOV now — SOE moved to its own
// "Share of Expenditure" panel (BrandSpendRow, imported) once this screen
// split GRP-weight and spend-weight into two side-by-side panels rather
// than one combined list. Exported so ProjectDetailSection's own SOV panel
// (a per-project drill-down, distinct from this executive dashboard) reuses
// the identical row instead of a third near-copy.
export function BrandShareRow({ share, maxGrp }: { share: BrandShare; maxGrp: number }) {
  const width = maxGrp ? `${Math.max((share.totalGrps / maxGrp) * 100, 3)}%` : '3%';
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
        <strong>{share.sov.toFixed(1)}% SOV</strong>
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
      </small>
    </div>
  );
}

// A short, plain-English synthesis of the numbers already on this screen —
// not new data, just the comparisons a human would draw by eyeballing the
// SOV/SOE panels and quietly doing the division themselves. Every sentence
// is derived straight from BrandShare fields already fetched; nothing here
// calls a new endpoint. Returns [] (and the panel doesn't render at all)
// when there isn't enough signal for a sentence to mean anything — e.g. a
// project with no spend data yet has nothing to say about efficiency.
function buildReadingOfThePeriod(brandShares: BrandShare[]): string[] {
  const insights: string[] = [];
  const withSpendAndGrp = brandShares.filter((share) => share.totalSpend > 0 && share.totalGrps > 0);

  // Efficiency leader: converts a smaller share of spend into a larger
  // share of voice than its spend alone would predict (sov > soe).
  const efficient = withSpendAndGrp
    .map((share) => ({ share, gap: share.sov - share.soe }))
    .filter((row) => row.gap > 0)
    .sort((a, b) => b.gap - a.gap);
  if (efficient.length > 0) {
    const leader = efficient[0];
    const qualifier = efficient.length === 1
      ? 'the only brand in the set buying above the category efficiency line'
      : `the strongest of ${efficient.length} brands buying above the category efficiency line`;
    insights.push(
      `${leader.share.brand} converts ${leader.share.soe.toFixed(0)}% of category spend into ${leader.share.sov.toFixed(0)}% of category voice, ${qualifier}.`,
    );
  }

  // Cost outlier: same threshold Spend Intelligence's "Overpriced" flag
  // uses, so this sentence always names a brand that screen would also
  // flag — never a second, quietly different bar.
  const categorySpend = brandShares.reduce((sum, share) => sum + share.totalSpend, 0);
  const categoryGrps = brandShares.reduce((sum, share) => sum + share.totalGrps, 0);
  const categoryCostPerGrp = categoryGrps > 0 ? categorySpend / categoryGrps : null;
  if (categoryCostPerGrp !== null) {
    const overpriced = withSpendAndGrp
      .filter((share) => share.spots >= HIGH_COST_MIN_SPOTS)
      .map((share) => ({ share, costPerGrp: share.totalSpend / share.totalGrps }))
      .filter((row) => row.costPerGrp > categoryCostPerGrp * HIGH_COST_RATIO)
      .sort((a, b) => b.costPerGrp - a.costPerGrp);
    if (overpriced.length > 0) {
      const worst = overpriced[0];
      const premiumPct = (worst.costPerGrp / categoryCostPerGrp - 1) * 100;
      // Which medium is driving the premium: whichever one takes a
      // meaningfully bigger slice of this brand's spend than of its GRPs.
      const mediums = [
        { name: 'TV', spend: worst.share.tvSpend, grp: worst.share.tvGrps },
        { name: 'Cable TV', spend: worst.share.cableTvSpend, grp: worst.share.cableTvGrps },
        { name: 'Radio', spend: worst.share.radioSpend, grp: worst.share.radioGrps },
      ];
      const driver = mediums
        .map((medium) => ({
          name: medium.name,
          gap: medium.spend / worst.share.totalSpend - medium.grp / worst.share.totalGrps,
        }))
        .sort((a, b) => b.gap - a.gap)[0];
      const driverClause = driver.gap > 0.15 ? `, driven by a ${driver.name.toLowerCase()}-heavy spend mix` : '';
      insights.push(
        `${worst.share.brand} pays ${premiumPct.toFixed(0)}% more per rating point than the category average${driverClause}.`,
      );
    }
  }

  // Medium mix: is Cable TV over- or under-delivering relative to its own
  // share of category spend?
  const cableSpend = brandShares.reduce((sum, share) => sum + share.cableTvSpend, 0);
  if (categorySpend > 0 && cableSpend > 0) {
    const cableSpendSharePct = (cableSpend / categorySpend) * 100;
    const cableGrps = brandShares.reduce((sum, share) => sum + share.cableTvGrps, 0);
    const cableGrpSharePct = categoryGrps > 0 ? (cableGrps / categoryGrps) * 100 : 0;
    const comparison = cableGrpSharePct > cableSpendSharePct + 1
      ? 'outperforming its spend weight'
      : cableGrpSharePct < cableSpendSharePct - 1
        ? 'underperforming its spend weight'
        : 'roughly matching its spend weight';
    insights.push(
      `Cable TV carries ${cableSpendSharePct.toFixed(0)}% of category spend and ${cableGrpSharePct.toFixed(0)}% of delivered GRPs, ${comparison}.`,
    );
  }

  return insights;
}

export default function OverviewSection({ project }: { project: Project | null }) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [spotEfficiency, setSpotEfficiency] = useState<SpotEfficiency[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [efficiencyError, setEfficiencyError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    setEfficiencyError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      if (latestRun) {
        const [shares, efficiency] = await Promise.allSettled([
          listBrandShares(projectId, latestRun.runId),
          listSpotEfficiency(projectId, latestRun.runId),
        ]);
        if (shares.status === 'fulfilled') {
          setBrandShares(shares.value);
        } else {
          throw shares.reason;
        }
        if (efficiency.status === 'fulfilled') {
          setSpotEfficiency(efficiency.value);
        } else {
          setSpotEfficiency([]);
          setEfficiencyError(efficiency.reason instanceof Error ? efficiency.reason.message : 'Could not load spot efficiency.');
        }
      } else {
        setBrandShares([]);
        setSpotEfficiency([]);
      }
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the overview.');
      setRun(null);
      setBrandShares([]);
      setSpotEfficiency([]);
      setEfficiencyError(null);
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
      setEfficiencyError(null);
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
  const maxSpend = Math.max(1, ...brandShares.map((share) => share.totalSpend));
  const matchedActivityPct = run && run.matchedRows + run.unmatchedRows > 0
    ? (run.matchedRows / (run.matchedRows + run.unmatchedRows)) * 100
    : null;
  const categoryCostPerGrp = run && run.totalGrps > 0 ? run.totalSpend / run.totalGrps : null;
  // brandShares arrives sorted by totalGrps descending (both repository
  // backends sort it that way), so the first entry is already the leader.
  const leadingBrand = brandShares[0] ?? null;
  const spendRanked = [...brandShares].sort((a, b) => b.totalSpend - a.totalSpend);
  const weakBuys = spotEfficiency.filter((row) => row.isWeak);
  const readingInsights = buildReadingOfThePeriod(brandShares);

  return (
    <>
      {loadError && <p className="inline-error">{loadError}</p>}
      {efficiencyError && <p className="inline-error">Spot efficiency: {efficiencyError}</p>}

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
              <span>Cost per GRP</span>
              <strong>{categoryCostPerGrp !== null ? formatNumber(categoryCostPerGrp) : '—'}</strong>
              <small>category average</small>
            </div>
            <div className="metric-panel">
              <span>Leading Brand</span>
              <strong>{leadingBrand ? leadingBrand.brand : '—'}</strong>
              <small>
                {leadingBrand
                  ? `${leadingBrand.sov.toFixed(1)}% SOV${leadingBrand.totalSpend > 0 ? ` · ${leadingBrand.soe.toFixed(1)}% SOE` : ''}`
                  : ' '}
              </small>
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
                  <h2>Share of Voice</h2>
                  <p>GRP-by-brand ranking and TV/Cable TV/Radio split</p>
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
                <LimitedRows rows={brandShares} render={(share) => (
                  <BrandShareRow share={share} maxGrp={maxGrp} key={share.brandId} />
                )} />
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Share of Expenditure</h2>
                  <p>Spend-by-brand ranking and TV/Cable TV/Radio split</p>
                </div>
                <PieChart size={20} aria-hidden />
              </div>
              <div className="brand-list">
                {brandShares.every((share) => share.totalSpend === 0) && (
                  <p className="empty-state">No spend data yet — upload a report with a Cost or Rate column.</p>
                )}
                <LimitedRows rows={spendRanked.filter((share) => share.totalSpend > 0)} render={(share) => (
                    <BrandSpendRow share={share} maxSpend={maxSpend} key={share.brandId} />
                  )} />
              </div>
            </div>
          </section>

          {readingInsights.length > 0 && (
            <div className="panel reading-panel">
              <span className="reading-eyebrow">Reading of the period</span>
              <LimitedRows rows={readingInsights} render={(sentence, index) => (
                <p key={index}>{sentence}</p>
              )} />
            </div>
          )}

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
              <LimitedRows rows={weakBuys} render={(row) => (
                <div className="brand-row" key={`${row.brandId}-${row.station}`}>
                  <div className="brand-line">
                    <span>{row.brand} · {row.station}</span>
                    <strong>{row.grpPerSpot.toFixed(2)} GRP/spot</strong>
                  </div>
                  <small>{row.spots} spots | {row.totalGrps.toFixed(1)} GRPs total</small>
                </div>
              )} />
            </div>
          </div>
        </>
      )}
    </>
  );
}
