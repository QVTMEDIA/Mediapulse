import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, Clock, GitCompare, LineChart, Radio } from 'lucide-react';
import {
  ApiError,
  getLatestRun,
  listBrandShares,
  listDaypartShares,
  listProgrammeShares,
  listSpotEfficiency,
  listStationShares,
  listTrend,
} from '../api/client';
import type {
  BrandShare,
  DaypartShare,
  GrpRunSummary,
  ProgrammeShare,
  Project,
  SpotEfficiency,
  StationShare,
  TrendPoint,
} from '../api/contracts';

interface RankedRow {
  key: string;
  totalGrps: number;
  spots: number;
}

function rankBy<T>(rows: T[], keyOf: (row: T) => string, grpOf: (row: T) => number, spotsOf: (row: T) => number): RankedRow[] {
  const totals = new Map<string, RankedRow>();
  for (const row of rows) {
    const key = keyOf(row);
    const existing = totals.get(key);
    if (existing) {
      existing.totalGrps += grpOf(row);
      existing.spots += spotsOf(row);
    } else {
      totals.set(key, { key, totalGrps: grpOf(row), spots: spotsOf(row) });
    }
  }
  return [...totals.values()].sort((a, b) => b.totalGrps - a.totalGrps);
}

function RankedBarRow({ row, maxGrp }: { row: RankedRow; maxGrp: number }) {
  const width = maxGrp ? `${Math.max((row.totalGrps / maxGrp) * 100, 3)}%` : '3%';
  return (
    <div className="brand-row">
      <div className="brand-line">
        <span>{row.key}</span>
        <strong>{row.totalGrps.toFixed(1)} GRPs</strong>
      </div>
      <div className="bar-track" aria-label={`${row.key} GRP contribution`}>
        <div className="bar-fill" style={{ width }} />
      </div>
      <small>{row.spots} spots</small>
    </div>
  );
}

export default function ReportsSection({ project }: { project: Project | null }) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [stationShares, setStationShares] = useState<StationShare[]>([]);
  const [programmeShares, setProgrammeShares] = useState<ProgrammeShare[]>([]);
  const [daypartShares, setDaypartShares] = useState<DaypartShare[]>([]);
  const [spotEfficiency, setSpotEfficiency] = useState<SpotEfficiency[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [compareBrandA, setCompareBrandA] = useState('');
  const [compareBrandB, setCompareBrandB] = useState('');
  // '' = all brands combined (the original behavior). Scopes Station,
  // Programme, and Weekly Trend to one brand's own numbers — the "Brand
  // detail" drill-down PRODUCT_ROADMAP.md's Brands screen calls for, reusing
  // data these panels already fetch rather than a new endpoint.
  const [drillBrandId, setDrillBrandId] = useState('');

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      if (latestRun) {
        const [shares, stations, programmes, dayparts, efficiency, trendPoints] = await Promise.all([
          listBrandShares(projectId, latestRun.runId),
          listStationShares(projectId, latestRun.runId),
          listProgrammeShares(projectId, latestRun.runId),
          listDaypartShares(projectId, latestRun.runId),
          listSpotEfficiency(projectId, latestRun.runId),
          listTrend(projectId, latestRun.runId),
        ]);
        setBrandShares(shares);
        setStationShares(stations);
        setProgrammeShares(programmes);
        setDaypartShares(dayparts);
        setSpotEfficiency(efficiency);
        setTrend(trendPoints);
      } else {
        setBrandShares([]);
        setStationShares([]);
        setProgrammeShares([]);
        setDaypartShares([]);
        setSpotEfficiency([]);
        setTrend([]);
      }
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load reports.');
      setRun(null);
      setBrandShares([]);
      setStationShares([]);
      setProgrammeShares([]);
      setDaypartShares([]);
      setSpotEfficiency([]);
      setTrend([]);
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
      setStationShares([]);
      setProgrammeShares([]);
      setDaypartShares([]);
      setSpotEfficiency([]);
      setTrend([]);
    }
  }, [project, refresh]);

  useEffect(() => {
    setCompareBrandA((current) => (brandShares.some((share) => share.brandId === current) ? current : (brandShares[0]?.brandId ?? '')));
    setCompareBrandB((current) =>
      brandShares.some((share) => share.brandId === current) ? current : (brandShares[1]?.brandId ?? brandShares[0]?.brandId ?? ''),
    );
    setDrillBrandId((current) => (current && !brandShares.some((share) => share.brandId === current) ? '' : current));
  }, [brandShares]);

  const stationSharesInScope = useMemo(
    () => (drillBrandId ? stationShares.filter((row) => row.brandId === drillBrandId) : stationShares),
    [stationShares, drillBrandId],
  );
  const programmeSharesInScope = useMemo(
    () => (drillBrandId ? programmeShares.filter((row) => row.brandId === drillBrandId) : programmeShares),
    [programmeShares, drillBrandId],
  );
  const daypartSharesInScope = useMemo(
    () => (drillBrandId ? daypartShares.filter((row) => row.brandId === drillBrandId) : daypartShares),
    [daypartShares, drillBrandId],
  );
  const spotEfficiencyInScope = useMemo(
    () => (drillBrandId ? spotEfficiency.filter((row) => row.brandId === drillBrandId) : spotEfficiency),
    [spotEfficiency, drillBrandId],
  );
  const trendInScope = useMemo(
    () => (drillBrandId ? trend.filter((point) => point.brandId === drillBrandId) : trend),
    [trend, drillBrandId],
  );

  const stationRanking = useMemo(
    () => rankBy(stationSharesInScope, (row) => row.station, (row) => row.totalGrps, (row) => row.spots),
    [stationSharesInScope],
  );
  const programmeRanking = useMemo(
    () => rankBy(programmeSharesInScope, (row) => row.programme, (row) => row.totalGrps, (row) => row.spots),
    [programmeSharesInScope],
  );
  const daypartRanking = useMemo(
    () => rankBy(daypartSharesInScope, (row) => row.timeBand || 'No daypart mapped', (row) => row.totalGrps, (row) => row.spots),
    [daypartSharesInScope],
  );
  const maxStationGrp = Math.max(1, ...stationRanking.map((row) => row.totalGrps));
  const maxProgrammeGrp = Math.max(1, ...programmeRanking.map((row) => row.totalGrps));
  const maxDaypartGrp = Math.max(1, ...daypartRanking.map((row) => row.totalGrps));
  const weakSpotCount = spotEfficiencyInScope.filter((row) => row.isWeak).length;

  const trendWeeks = useMemo(() => [...new Set(trendInScope.map((point) => point.weekStart))].sort(), [trendInScope]);
  const trendBrandOrder = useMemo(() => [...new Set(trendInScope.map((point) => point.brand))].sort(), [trendInScope]);
  const maxTrendGrp = Math.max(1, ...trendInScope.map((point) => point.totalGrps));

  const brandA = brandShares.find((share) => share.brandId === compareBrandA) ?? null;
  const brandB = brandShares.find((share) => share.brandId === compareBrandB) ?? null;
  const drillBrand = brandShares.find((share) => share.brandId === drillBrandId) ?? null;

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to see its station, programme, and trend reports.</p>
      </div>
    );
  }

  return (
    <>
      {loadError && <p className="inline-error">{loadError}</p>}

      {!loading && !run && !loadError && (
        <div className="panel placeholder-panel">
          <h2>No calculation yet</h2>
          <p>Go to Projects and click Calculate to generate station, programme, trend, and comparison reports.</p>
        </div>
      )}

      {run && (
        <section className="content-grid">
          {brandShares.length > 1 && (
            <div className="panel brand-drill-panel">
              <div className="upload-form">
                <label>
                  Brand detail
                  <select value={drillBrandId} onChange={(event) => setDrillBrandId(event.target.value)}>
                    <option value="">All brands (combined)</option>
                    {brandShares.map((share) => (
                      <option value={share.brandId} key={share.brandId}>
                        {share.brand}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="field-hint">
                  Scopes Station Contribution, Programme Contribution, Daypart Contribution, Spot Efficiency, and
                  Weekly Trend below to one brand's own numbers. Brand Comparison always shows two brands side by
                  side regardless of this selection.
                </p>
              </div>
            </div>
          )}

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Station Contribution{drillBrandId ? ` — ${drillBrand?.brand ?? ''}` : ''}</h2>
                <p>{loading ? 'Loading…' : `GRP ranking across ${stationRanking.length} station${stationRanking.length === 1 ? '' : 's'}`}</p>
              </div>
              <Radio size={20} aria-hidden />
            </div>
            <div className="brand-list">
              {!loading && stationRanking.length === 0 && <p className="empty-state">No matched spots yet.</p>}
              {stationRanking.map((row) => (
                <RankedBarRow row={row} maxGrp={maxStationGrp} key={row.key} />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Programme Contribution{drillBrandId ? ` — ${drillBrand?.brand ?? ''}` : ''}</h2>
                <p>
                  {loading ? 'Loading…' : `GRP ranking across ${programmeRanking.length} programme${programmeRanking.length === 1 ? '' : 's'}`}
                </p>
              </div>
              <BarChart3 size={20} aria-hidden />
            </div>
            <div className="brand-list">
              {!loading && programmeRanking.length === 0 && <p className="empty-state">No matched spots yet.</p>}
              {programmeRanking.map((row) => (
                <RankedBarRow row={row} maxGrp={maxProgrammeGrp} key={row.key} />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Daypart Contribution{drillBrandId ? ` — ${drillBrand?.brand ?? ''}` : ''}</h2>
                <p>
                  {loading
                    ? 'Loading…'
                    : `GRP ranking across ${daypartRanking.length} daypart label${daypartRanking.length === 1 ? '' : 's'}, as reported by the source file`}
                </p>
              </div>
              <Clock size={20} aria-hidden />
            </div>
            <div className="brand-list">
              {!loading && daypartRanking.length === 0 && <p className="empty-state">No matched spots yet.</p>}
              {daypartRanking.map((row) => (
                <RankedBarRow row={row} maxGrp={maxDaypartGrp} key={row.key} />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Spot Efficiency{drillBrandId ? ` — ${drillBrand?.brand ?? ''}` : ''}</h2>
                <p>
                  {loading
                    ? 'Loading…'
                    : weakSpotCount > 0
                      ? `${weakSpotCount} brand/station buy${weakSpotCount === 1 ? '' : 's'} flagged as weak inventory at volume`
                      : 'No weak-inventory buys flagged for this run'}
                </p>
              </div>
              <AlertTriangle size={20} aria-hidden />
            </div>
            {!loading && spotEfficiencyInScope.length === 0 && <p className="empty-state">No matched spots yet.</p>}
            {spotEfficiencyInScope.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Brand</th>
                      <th>Station</th>
                      <th className="num">Spots</th>
                      <th className="num">GRP</th>
                      <th className="num">GRP / Spot</th>
                      <th>Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {spotEfficiencyInScope.map((row) => (
                      <tr key={`${row.brandId}-${row.station}`}>
                        <td>{row.brand}</td>
                        <td>{row.station}</td>
                        <td className="num">{row.spots}</td>
                        <td className="num">{row.totalGrps.toFixed(1)}</td>
                        <td className="num">{row.grpPerSpot.toFixed(2)}</td>
                        <td>
                          {row.isWeak ? (
                            <span className="status status-review">Weak inventory</span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Weekly Trend{drillBrandId ? ` — ${drillBrand?.brand ?? ''}` : ''}</h2>
                <p>{loading ? 'Loading…' : `${trendWeeks.length} week${trendWeeks.length === 1 ? '' : 's'} with dated activity`}</p>
              </div>
              <LineChart size={20} aria-hidden />
            </div>
            {!loading && trendInScope.length === 0 && (
              <p className="empty-state">
                {drillBrandId ? 'No dated activity for this brand yet.' : 'No dated activity yet — trend needs a Date column on uploaded rows.'}
              </p>
            )}
            {trendInScope.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Week of</th>
                      <th>Brand</th>
                      <th className="num">Spots</th>
                      <th className="num">GRP</th>
                      <th>Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trendWeeks.flatMap((week) =>
                      trendBrandOrder
                        .map((brand) => trendInScope.find((point) => point.weekStart === week && point.brand === brand))
                        .filter((point): point is TrendPoint => Boolean(point))
                        .map((point) => (
                          <tr key={`${point.weekStart}-${point.brandId}`}>
                            <td>{point.weekStart}</td>
                            <td>{point.brand}</td>
                            <td className="num">{point.spots}</td>
                            <td className="num">{point.totalGrps.toFixed(1)}</td>
                            <td>
                              <div className="bar-track" aria-label={`${point.brand} week of ${point.weekStart} GRP`}>
                                <div
                                  className="bar-fill"
                                  style={{ width: `${Math.max((point.totalGrps / maxTrendGrp) * 100, 3)}%` }}
                                />
                              </div>
                            </td>
                          </tr>
                        )),
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Brand Comparison</h2>
                <p>{loading ? 'Loading…' : 'Side-by-side GRP, SOV, spend, SOE, spots, and medium split'}</p>
              </div>
              <GitCompare size={20} aria-hidden />
            </div>
            {!loading && brandShares.length < 2 && (
              <p className="empty-state">Need at least two brands with matched spots to compare.</p>
            )}
            {brandShares.length >= 2 && (
              <>
                <div className="upload-form-row">
                  <label>
                    Brand A
                    <select value={compareBrandA} onChange={(event) => setCompareBrandA(event.target.value)}>
                      {brandShares.map((share) => (
                        <option value={share.brandId} key={share.brandId}>
                          {share.brand}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Brand B
                    <select value={compareBrandB} onChange={(event) => setCompareBrandB(event.target.value)}>
                      {brandShares.map((share) => (
                        <option value={share.brandId} key={share.brandId}>
                          {share.brand}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {brandA && brandB && (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Metric</th>
                          <th className="num">{brandA.brand}</th>
                          <th className="num">{brandB.brand}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Total GRPs</td>
                          <td className="num">{brandA.totalGrps.toFixed(1)}</td>
                          <td className="num">{brandB.totalGrps.toFixed(1)}</td>
                        </tr>
                        <tr>
                          <td>Share of Voice</td>
                          <td className="num">{brandA.sov.toFixed(1)}%</td>
                          <td className="num">{brandB.sov.toFixed(1)}%</td>
                        </tr>
                        <tr>
                          <td>Spend</td>
                          <td className="num">{brandA.totalSpend > 0 ? brandA.totalSpend.toLocaleString() : '—'}</td>
                          <td className="num">{brandB.totalSpend > 0 ? brandB.totalSpend.toLocaleString() : '—'}</td>
                        </tr>
                        <tr>
                          <td>Share of Expenditure</td>
                          <td className="num">{brandA.totalSpend > 0 ? `${brandA.soe.toFixed(1)}%` : '—'}</td>
                          <td className="num">{brandB.totalSpend > 0 ? `${brandB.soe.toFixed(1)}%` : '—'}</td>
                        </tr>
                        <tr>
                          <td>Spots</td>
                          <td className="num">{brandA.spots}</td>
                          <td className="num">{brandB.spots}</td>
                        </tr>
                        <tr>
                          <td>Average Rating</td>
                          <td className="num">{brandA.avgRating !== null ? brandA.avgRating.toFixed(2) : '—'}</td>
                          <td className="num">{brandB.avgRating !== null ? brandB.avgRating.toFixed(2) : '—'}</td>
                        </tr>
                        <tr>
                          <td>TV GRPs</td>
                          <td className="num">{brandA.tvGrps.toFixed(1)}</td>
                          <td className="num">{brandB.tvGrps.toFixed(1)}</td>
                        </tr>
                        {(brandA.cableTvGrps > 0 || brandB.cableTvGrps > 0) && (
                          <tr>
                            <td>Cable TV GRPs</td>
                            <td className="num">{brandA.cableTvGrps.toFixed(1)}</td>
                            <td className="num">{brandB.cableTvGrps.toFixed(1)}</td>
                          </tr>
                        )}
                        <tr>
                          <td>Radio GRPs</td>
                          <td className="num">{brandA.radioGrps.toFixed(1)}</td>
                          <td className="num">{brandB.radioGrps.toFixed(1)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </>
  );
}
