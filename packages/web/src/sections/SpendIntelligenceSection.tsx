import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, DollarSign, PieChart } from 'lucide-react';
import { ApiError, getLatestRun, listBrandShares } from '../api/client';
import type { BrandShare, GrpRunSummary, Project } from '../api/contracts';
import { LimitedRows, LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

export function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value);
}

// A brand/station is flagged "high cost" when its own cost-per-GRP is more
// than 50% above the category's average for the run, at 5+ spots so a
// single expensive placement doesn't trigger it — the mirror image of
// ReportsSection's spot-efficiency "weak inventory" flag (that one catches
// GRP too low for the spend; this one catches spend too high for the GRP).
// Deliberately conservative for the same reason: a false "overpriced" flag
// on a real advertiser's real campaign has real reputational cost. Exported
// so OverviewSection's "Reading of the Period" narrative flags the exact
// same brand this screen's table would, rather than drifting out of sync
// with a second, subtly different threshold.
export const HIGH_COST_RATIO = 1.5;
export const HIGH_COST_MIN_SPOTS = 5;

// Same shape as OverviewSection's BrandShareRow, but the bar (and the
// number it's sized by) tracks spend instead of GRPs — a brand can lead
// SOV while trailing spend share, or vice versa, since spend counts every
// uploaded row regardless of match status. Exported for OverviewSection's
// "Share of Expenditure" panel, which renders the identical row shape.
export function BrandSpendRow({ share, maxSpend }: { share: BrandShare; maxSpend: number }) {
  const width = maxSpend ? `${Math.max((share.totalSpend / maxSpend) * 100, 3)}%` : '3%';
  const mediumsPresent = [share.tvSpend, share.cableTvSpend, share.radioSpend].filter((s) => s > 0).length;
  const isMixedMedia = mediumsPresent >= 2;
  const tvShare = share.totalSpend > 0 ? (share.tvSpend / share.totalSpend) * 100 : 100;
  const cableTvShare = share.totalSpend > 0 ? (share.cableTvSpend / share.totalSpend) * 100 : 0;
  const radioShare = share.totalSpend > 0 ? (share.radioSpend / share.totalSpend) * 100 : 0;
  const soloColor = share.cableTvSpend > 0 ? 'var(--violet)' : share.radioSpend > 0 ? 'var(--blue)' : undefined;
  return (
    <div className="brand-row">
      <div className="brand-line">
        <span>{share.brand}</span>
        <strong className="soe-value">{share.soe.toFixed(1)}% SOE</strong>
      </div>
      <div className="bar-track" aria-label={`${share.brand} spend contribution`}>
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
        {formatNumber(share.totalSpend)} spend
        {isMixedMedia
          ? ` (TV ${formatNumber(share.tvSpend)}${share.cableTvSpend > 0 ? ` · Cable TV ${formatNumber(share.cableTvSpend)}` : ''} · Radio ${formatNumber(share.radioSpend)})`
          : ''}
      </small>
    </div>
  );
}

export default function SpendIntelligenceSection({ project }: { project: Project | null }) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      setBrandShares(latestRun ? await listBrandShares(projectId, latestRun.runId) : []);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load spend intelligence.');
      setRun(null);
      setBrandShares([]);
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
    }
  }, [project, refresh]);

  const maxSpend = Math.max(1, ...brandShares.map((share) => share.totalSpend));
  const categorySpend = brandShares.reduce((sum, share) => sum + share.totalSpend, 0);
  const categoryGrps = brandShares.reduce((sum, share) => sum + share.totalGrps, 0);
  const categoryCostPerGrp = categoryGrps > 0 ? categorySpend / categoryGrps : null;
  const spendRanked = [...brandShares].sort((a, b) => b.totalSpend - a.totalSpend);
  // brandShares arrives sorted by totalGrps, not spend — the leading
  // spender is a different question from the leading brand on Overview.
  const leadingSpender = spendRanked[0] ?? null;
  const brandsWithSpend = brandShares.filter((share) => share.totalSpend > 0).length;

  const costEfficiency = brandShares
    .filter((share) => share.totalSpend > 0 && share.totalGrps > 0)
    .map((share) => ({
      share,
      costPerGrp: share.totalSpend / share.totalGrps,
      isHighCost:
        categoryCostPerGrp !== null
        && share.spots >= HIGH_COST_MIN_SPOTS
        && share.totalSpend / share.totalGrps > categoryCostPerGrp * HIGH_COST_RATIO,
    }))
    .sort((a, b) => b.costPerGrp - a.costPerGrp);
  const highCostCount = costEfficiency.filter((row) => row.isHighCost).length;
  const limitedCostEfficiency = useLimitedRows(costEfficiency);

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to see its media spend and Share of Expenditure.</p>
      </div>
    );
  }

  return (
    <>
      {loadError && <p className="inline-error">{loadError}</p>}

      {!loading && !run && !loadError && (
        <div className="panel placeholder-panel">
          <h2>No calculation yet</h2>
          <p>Go to Projects and click Calculate to generate this project's spend intelligence.</p>
        </div>
      )}

      {run && (
        <>
          <section className="metric-grid" aria-label="Spend summary">
            <div className="metric-panel">
              <span>Total Spend</span>
              <strong>{formatNumber(run.totalSpend)}</strong>
              <small>{run.totalSpend === 0 ? 'No cost/rate column mapped yet' : `Run generated ${run.generatedAt}`}</small>
            </div>
            <div className="metric-panel">
              <span>Cost per GRP</span>
              <strong>{categoryCostPerGrp !== null ? formatNumber(categoryCostPerGrp) : '—'}</strong>
              <small>category average</small>
            </div>
            <div className="metric-panel">
              <span>Leading Spender</span>
              <strong>{leadingSpender && leadingSpender.totalSpend > 0 ? leadingSpender.brand : '—'}</strong>
              <small>{leadingSpender && leadingSpender.totalSpend > 0 ? `${leadingSpender.soe.toFixed(1)}% SOE` : ' '}</small>
            </div>
            <div className="metric-panel">
              <span>Brands with Spend</span>
              <strong>{brandsWithSpend}</strong>
              <small>of {brandShares.length} total</small>
            </div>
          </section>

          <section className="content-grid">
            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Spend by Brand</h2>
                  <p>Share of Expenditure and TV/Cable TV/Radio spend split</p>
                </div>
                <PieChart size={20} aria-hidden />
              </div>
              {brandsWithSpend === 0 && (
                <p className="empty-state">
                  No spend data yet — upload a report with a Cost or Rate column, then recalculate.
                </p>
              )}
              {brandsWithSpend > 0 && (
                <div className="brand-list">
                  <LimitedRows rows={spendRanked} render={(share) => (
                    <BrandSpendRow share={share} maxSpend={maxSpend} key={share.brandId} />
                  )} />
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <div>
                  <h2>Cost per GRP</h2>
                  <p>
                    {highCostCount > 0
                      ? `${highCostCount} brand${highCostCount === 1 ? '' : 's'} flagged as overpriced GRPs`
                      : costEfficiency.length > 0
                        ? 'No brand flagged as overpriced this run'
                        : 'Needs both spend and matched GRPs to compare'}
                  </p>
                </div>
                <AlertTriangle size={20} aria-hidden />
              </div>
              {costEfficiency.length === 0 && <p className="empty-state">Nothing to compare yet.</p>}
              {costEfficiency.length > 0 && (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Brand</th>
                        <th className="num">Spend</th>
                        <th className="num">GRPs</th>
                        <th className="num">Cost / GRP</th>
                        <th>Flag</th>
                      </tr>
                    </thead>
                    <tbody>
                      {limitedCostEfficiency.visibleRows.map((row) => (
                        <tr key={row.share.brandId}>
                          <td>{row.share.brand}</td>
                          <td className="num">{formatNumber(row.share.totalSpend)}</td>
                          <td className="num">{row.share.totalGrps.toFixed(1)}</td>
                          <td className="num">{formatNumber(row.costPerGrp)}</td>
                          <td>
                            {row.isHighCost ? <span className="status status-review">Overpriced</span> : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <LimitedRowsControls {...limitedCostEfficiency} total={costEfficiency.length} />
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </>
  );
}
