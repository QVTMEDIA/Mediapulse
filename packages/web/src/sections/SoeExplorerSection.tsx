import { useCallback, useEffect, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { ApiError, getSoe, getSoeFilterOptions } from '../api/client';
import type { Project, SoeFilterOptions, SoeReport } from '../api/contracts';
import { formatNumber } from './SpendIntelligenceSection';

const EMPTY_FILTER_OPTIONS: SoeFilterOptions = { mediums: [], stations: [], regions: [], days: [] };
const EMPTY_REPORT: SoeReport = { totalSpend: 0, brands: [] };

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
}

function FilterGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div className="soe-filter-group">
      <h3>
        {label}
        {selected.length > 0 && <span className="soe-filter-count">{selected.length}</span>}
      </h3>
      <div className="soe-filter-options">
        {options.map((option) => (
          <label className="checkbox-field" key={option}>
            <input type="checkbox" checked={selected.includes(option)} onChange={() => onToggle(option)} />
            {option}
          </label>
        ))}
      </div>
    </div>
  );
}

export default function SoeExplorerSection({ project }: { project: Project | null }) {
  const [filterOptions, setFilterOptions] = useState<SoeFilterOptions>(EMPTY_FILTER_OPTIONS);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [mediums, setMediums] = useState<string[]>([]);
  const [stations, setStations] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [days, setDays] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const [report, setReport] = useState<SoeReport>(EMPTY_REPORT);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    // Selections from a previous project don't carry over — a "Lagos"
    // filter left on from a different project would silently exclude
    // everything here rather than erroring, which is worse than resetting.
    setMediums([]);
    setStations([]);
    setRegions([]);
    setDays([]);
    setDateFrom('');
    setDateTo('');
    if (!project) {
      setFilterOptions(EMPTY_FILTER_OPTIONS);
      setReport(EMPTY_REPORT);
      return;
    }
    setOptionsLoading(true);
    setOptionsError(null);
    getSoeFilterOptions(project.projectId)
      .then(setFilterOptions)
      .catch((error) => setOptionsError(error instanceof ApiError ? error.message : 'Could not load filters.'))
      .finally(() => setOptionsLoading(false));
  }, [project]);

  const refresh = useCallback(() => {
    if (!project) return;
    setReportLoading(true);
    setReportError(null);
    getSoe(project.projectId, {
      medium: mediums,
      station: stations,
      region: regions,
      day: days,
      dateFrom: dateFrom || null,
      dateTo: dateTo || null,
    })
      .then(setReport)
      .catch((error) => setReportError(error instanceof ApiError ? error.message : 'Could not load Share of Expenditure.'))
      .finally(() => setReportLoading(false));
  }, [project, mediums, stations, regions, days, dateFrom, dateTo]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActiveFilters =
    mediums.length > 0 || stations.length > 0 || regions.length > 0 || days.length > 0 || !!dateFrom || !!dateTo;

  function clearFilters() {
    setMediums([]);
    setStations([]);
    setRegions([]);
    setDays([]);
    setDateFrom('');
    setDateTo('');
  }

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to explore its Share of Expenditure.</p>
      </div>
    );
  }

  const hasAnyFilterableData = filterOptions.mediums.length > 0 || filterOptions.stations.length > 0;
  const maxSpend = Math.max(1, ...report.brands.map((brand) => brand.spend));

  return (
    <>
      {optionsError && <p className="inline-error">{optionsError}</p>}

      {!optionsLoading && !hasAnyFilterableData && !optionsError && (
        <div className="panel placeholder-panel">
          <h2>No spend data yet</h2>
          <p>Upload a report with a Cost or Rate column, then come back here to explore it.</p>
        </div>
      )}

      {hasAnyFilterableData && (
        <>
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Filters</h2>
                <p>Narrow Share of Expenditure by whatever your uploads actually contain — every checkbox reflects real data, not a fixed list.</p>
              </div>
              <SlidersHorizontal size={20} aria-hidden />
            </div>
            <div className="soe-filters">
              <FilterGroup
                label="Medium"
                options={filterOptions.mediums}
                selected={mediums}
                onToggle={(value) => setMediums((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Station"
                options={filterOptions.stations}
                selected={stations}
                onToggle={(value) => setStations((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Region"
                options={filterOptions.regions}
                selected={regions}
                onToggle={(value) => setRegions((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Day"
                options={filterOptions.days}
                selected={days}
                onToggle={(value) => setDays((current) => toggleValue(current, value))}
              />
              <div className="soe-filter-group">
                <h3>Date range</h3>
                <div className="soe-date-inputs">
                  <label>
                    From
                    <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
                  </label>
                  <label>
                    To
                    <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
                  </label>
                </div>
              </div>
            </div>
            {hasActiveFilters && (
              <button type="button" className="secondary-button soe-clear-button" onClick={clearFilters}>
                Clear filters
              </button>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Share of Expenditure</h2>
                <p>
                  {reportLoading
                    ? 'Loading…'
                    : hasActiveFilters
                      ? `Filtered — ${formatNumber(report.totalSpend)} total spend`
                      : `${formatNumber(report.totalSpend)} total spend across every upload`}
                </p>
              </div>
            </div>
            {reportError && <p className="inline-error">{reportError}</p>}
            {!reportLoading && !reportError && report.brands.length === 0 && (
              <p className="empty-state">No spend matches these filters.</p>
            )}
            {report.brands.length > 0 && (
              <div className="brand-list">
                {report.brands.map((brand) => (
                  <div className="brand-row" key={brand.brandId}>
                    <div className="brand-line">
                      <span>{brand.brand}</span>
                      <strong className="soe-value">{brand.soe.toFixed(1)}% SOE</strong>
                    </div>
                    <div className="bar-track" aria-label={`${brand.brand} spend contribution`}>
                      <div className="bar-fill" style={{ width: `${Math.max((brand.spend / maxSpend) * 100, 3)}%` }} />
                    </div>
                    <small>
                      {formatNumber(brand.spend)} spend · {brand.spots} spot{brand.spots === 1 ? '' : 's'}
                    </small>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
