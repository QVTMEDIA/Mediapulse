import { useCallback, useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import {
  ApiError,
  correctMatch,
  downloadMatchReport,
  getMatchJob,
  listMatches,
  listMediaActivity,
  listProjectRatingsDatasets,
  listRatingRows,
  startMatchJob,
} from '../api/client';
import type { MediaActivityRow, Project, RatingMatch, RatingRow } from '../api/contracts';
import { LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

type MatchFilter = 'all' | 'matched' | 'suggested' | 'unmatched';

function suggestedReportFileName(project: Project): string {
  const safe = project.projectName.replace(/[^a-zA-Z0-9 _-]/g, '').trim().replace(/\s+/g, '_');
  return `${safe || 'mediapulse'}_match_report.csv`;
}

// Programme and Time Band are captured as separate fields (a vendor file
// often has both — e.g. a named programme plus its own "TIME BELT" column)
// but Time Band is blank far more often than not, so it's appended only
// when present rather than always showing a bare " · " for rows without one.
function describeSlot(programme: string, timeBand: string): string {
  const label = programme || 'No programme';
  return timeBand ? `${label} · ${timeBand}` : label;
}

function describeRatingOption(row: RatingRow) {
  const rating = row.rating === null ? 'no rating value' : row.rating;
  return `${row.station} · ${row.day} · ${describeSlot(row.programme, row.timeBand)} · ${rating}`;
}

const STATUS_LABEL: Record<RatingMatch['matchStatus'], string> = {
  exact: 'Exact',
  suggested: 'Suggested',
  unmatched: 'Unmatched',
  manual: 'Manual',
};

const STATUS_CLASS: Record<RatingMatch['matchStatus'], string> = {
  exact: 'status status-complete',
  suggested: 'status status-review',
  unmatched: 'status status-setup',
  manual: 'status status-complete',
};

function describeActivity(row?: MediaActivityRow) {
  if (!row) return 'Activity row no longer available';
  const base = `${row.station} · ${row.day} · ${describeSlot(row.programme, row.timeBand)} · ${row.spots} spot${row.spots === 1 ? '' : 's'}`;
  // cost is null when the upload never had a Cost/Rate column mapped —
  // omit the clause entirely rather than showing a misleading "spend 0".
  return row.cost !== null ? `${base} · spend ${row.cost.toLocaleString()}` : base;
}

function describeRating(row?: RatingRow) {
  if (!row) return 'Rating no longer available';
  const rating = row.rating === null ? 'no rating value' : `rating ${row.rating}`;
  return `${row.station} · ${row.day} · ${describeSlot(row.programme, row.timeBand)} · ${rating}`;
}

// A confirmed/manual match's matchedRatingId can be genuinely absent -- a
// human explicitly confirmed "no rating applies here" (see MatchCorrection's
// docstring) -- which reads very differently from describeRating's "no
// longer available" (a rating id is set, but that row can't be found
// anymore, e.g. its dataset was detached). Keeping the two messages
// distinct instead of collapsing both into "no longer available" is the
// whole point of showing the matched rating detail on confirmed rows at all.
function describeMatchedRating(match: RatingMatch, ratingsById: Map<string, RatingRow>) {
  if (!match.matchedRatingId) return 'Confirmed as unmatched — no rating assigned';
  return describeRating(ratingsById.get(match.matchedRatingId));
}

export default function MatchesSection({ project }: { project: Project | null }) {
  const [matches, setMatches] = useState<RatingMatch[]>([]);
  const [activityById, setActivityById] = useState<Map<string, MediaActivityRow>>(new Map());
  const [ratingsById, setRatingsById] = useState<Map<string, RatingRow>>(new Map());
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [correctingId, setCorrectingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isRecomputing, setIsRecomputing] = useState(false);
  const [assignSelections, setAssignSelections] = useState<Record<string, string>>({});
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all');
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const [job, activityResults, datasets] = await Promise.all([
        startMatchJob(projectId),
        listMediaActivity(projectId),
        listProjectRatingsDatasets(projectId),
      ]);
      let jobResult = job;
      while (jobResult.status === 'queued' || jobResult.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        jobResult = await getMatchJob(projectId, job.jobId);
      }
      if (jobResult.status === 'failed') throw new ApiError(500, jobResult.error ?? 'Matching failed.');
      const matchResults = await listMatches(projectId);
      setMatches(matchResults);
      setActivityById(new Map(activityResults.map((row) => [row.mediaActivityId, row])));

      const rowLists = await Promise.all(datasets.map((dataset) => listRatingRows(dataset.ratingsDatasetId)));
      const ratingsMap = new Map<string, RatingRow>();
      for (const rows of rowLists) {
        for (const row of rows) ratingsMap.set(row.ratingRowId, row);
      }
      setRatingsById(ratingsMap);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load matches.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setMatches([]);
      setActivityById(new Map());
      setRatingsById(new Map());
    }
  }, [project, refresh]);

  async function handleCorrect(match: RatingMatch, matchedRatingId: string | null) {
    if (!project) return;
    setCorrectingId(match.ratingMatchId);
    setActionError(null);
    try {
      await correctMatch(project.projectId, match.ratingMatchId, matchedRatingId);
      setAssignSelections((current) => {
        const next = { ...current };
        delete next[match.ratingMatchId];
        return next;
      });
      await refresh(project.projectId);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not update that match.');
    } finally {
      setCorrectingId(null);
    }
  }

  async function handleRecompute() {
    if (!project) return;
    setIsRecomputing(true);
    setActionError(null);
    try {
      const job = await startMatchJob(project.projectId, 'recompute');
      let jobResult = job;
      while (jobResult.status === 'queued' || jobResult.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        jobResult = await getMatchJob(project.projectId, job.jobId);
      }
      if (jobResult.status === 'failed') throw new ApiError(500, jobResult.error ?? 'Matching failed.');
      await refresh(project.projectId);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not recompute matches.');
    } finally {
      setIsRecomputing(false);
    }
  }

  async function handleExportReport() {
    if (!project) return;
    setIsExporting(true);
    setExportError(null);
    try {
      await downloadMatchReport(project.projectId, suggestedReportFileName(project));
    } catch (error) {
      setExportError(error instanceof ApiError ? error.message : 'Could not download the match report.');
    } finally {
      setIsExporting(false);
    }
  }

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to review its matches.</p>
      </div>
    );
  }

  const counts = matches.reduce<Record<string, number>>((acc, match) => {
    acc[match.matchStatus] = (acc[match.matchStatus] ?? 0) + 1;
    return acc;
  }, {});
  const suggested = matches.filter((match) => match.matchStatus === 'suggested');
  const unmatched = matches.filter((match) => match.matchStatus === 'unmatched');
  const resolved = matches.filter((match) => match.matchStatus === 'exact' || match.matchStatus === 'manual');
  const showSuggested = matchFilter === 'all' || matchFilter === 'suggested';
  const showUnmatched = matchFilter === 'all' || matchFilter === 'unmatched';
  const showResolved = matchFilter === 'all' || matchFilter === 'matched';
  const ratingOptions = Array.from(ratingsById.values()).sort((a, b) =>
    `${a.station} ${a.day} ${a.programme}`.localeCompare(`${b.station} ${b.day} ${b.programme}`),
  );
  const limitedSuggested = useLimitedRows(suggested);
  const limitedUnmatched = useLimitedRows(unmatched);
  const limitedResolved = useLimitedRows(resolved);

  return (
    <>
      <div className="toolbar match-export-bar">
        <button
          type="button"
          className="secondary-button"
          disabled={isExporting || matches.length === 0}
          title="Download a CSV of every media spend row alongside the rating it matched to"
          onClick={handleExportReport}
        >
          <Download size={16} aria-hidden />
          {isExporting ? 'Preparing…' : 'Download match report'}
        </button>
      </div>
      {exportError && <p className="inline-error">{exportError}</p>}

      <section className="metric-grid" aria-label="Match summary">
        <div className="metric-panel">
          <span>Total Spots</span>
          <strong>{matches.length}</strong>
          <small>{loading ? 'Loading…' : ' '}</small>
        </div>
        <div className="metric-panel">
          <span>Exact + Manual</span>
          <strong>{(counts.exact ?? 0) + (counts.manual ?? 0)}</strong>
          <small>confirmed matches</small>
        </div>
        <div className="metric-panel warning-panel">
          <span>Suggested</span>
          <strong>{counts.suggested ?? 0}</strong>
          <small>need review</small>
        </div>
        <div className="metric-panel warning-panel">
          <span>Unmatched</span>
          <strong>{counts.unmatched ?? 0}</strong>
          <small>no rating found</small>
        </div>
      </section>

      {actionError && <p className="inline-error">{actionError}</p>}
      {loadError && <p className="inline-error">{loadError}</p>}

      <div className="match-filter-bar" aria-label="Filter matches">
        {([
          ['all', 'All', matches.length],
          ['matched', 'Matched', (counts.exact ?? 0) + (counts.manual ?? 0)],
          ['suggested', 'Fuzzy matched', counts.suggested ?? 0],
          ['unmatched', 'Unmatched', counts.unmatched ?? 0],
        ] as const).map(([value, label, count]) => (
          <button
            type="button"
            className={matchFilter === value ? 'primary-button' : 'secondary-button'}
            aria-pressed={matchFilter === value}
            onClick={() => setMatchFilter(value)}
            key={value}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      {showSuggested && <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Needs review</h2>
            <p>Fuzzy-matched spots — confirm the suggestion or reject it</p>
          </div>
        </div>
        <div className="match-list">
          {!loading && suggested.length === 0 && <p className="empty-state">Nothing needs review right now.</p>}
          {limitedSuggested.visibleRows.map((match) => {
            const activity = activityById.get(match.mediaActivityId);
            const rating = match.matchedRatingId ? ratingsById.get(match.matchedRatingId) : undefined;
            return (
              <div className="match-row" key={match.ratingMatchId}>
                <div className="match-row-main">
                  <span className={STATUS_CLASS[match.matchStatus]}>{STATUS_LABEL[match.matchStatus]}</span>
                  {match.matchConfidence !== null && (
                    <span className="match-confidence">{Math.round(match.matchConfidence * 100)}% match</span>
                  )}
                </div>
                <p className="match-input">Activity: {describeActivity(activity)}</p>
                <p className="match-suggestion">Suggested: {describeRating(rating)}</p>
                <div className="form-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={correctingId === match.ratingMatchId}
                    onClick={() => handleCorrect(match, match.matchedRatingId)}
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={correctingId === match.ratingMatchId}
                    onClick={() => handleCorrect(match, null)}
                  >
                    Reject
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <LimitedRowsControls {...limitedSuggested} total={suggested.length} />
      </div>}

      <div className="content-grid bottom-grid">
        {showUnmatched && <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Unmatched</h2>
              <p>No rating found for these spots — assign one, or retry after attaching new ratings</p>
            </div>
            <button
              type="button"
              className="secondary-button"
              disabled={isRecomputing || unmatched.length === 0}
              title="Re-attempt matching for unmatched rows against the project's current ratings"
              onClick={handleRecompute}
            >
              {isRecomputing ? 'Recomputing…' : 'Recompute'}
            </button>
          </div>
          <div className="match-list">
            {!loading && unmatched.length === 0 && <p className="empty-state">No unmatched spots.</p>}
            {limitedUnmatched.visibleRows.map((match) => (
              <div className="match-row" key={match.ratingMatchId}>
                <p className="match-input">{describeActivity(activityById.get(match.mediaActivityId))}</p>
                {ratingOptions.length === 0 ? (
                  <p className="match-suggestion">No ratings attached to this project yet.</p>
                ) : (
                  <div className="form-actions">
                    <select
                      value={assignSelections[match.ratingMatchId] ?? ''}
                      onChange={(event) =>
                        setAssignSelections((current) => ({ ...current, [match.ratingMatchId]: event.target.value }))
                      }
                    >
                      <option value="">Assign a rating…</option>
                      {ratingOptions.map((rating) => (
                        <option value={rating.ratingRowId} key={rating.ratingRowId}>
                          {describeRatingOption(rating)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={!assignSelections[match.ratingMatchId] || correctingId === match.ratingMatchId}
                      onClick={() => handleCorrect(match, assignSelections[match.ratingMatchId])}
                    >
                      Assign
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <LimitedRowsControls {...limitedUnmatched} total={unmatched.length} />
        </div>}

        {showResolved && <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Confirmed</h2>
              <p>Exact key matches and manually confirmed rows</p>
            </div>
          </div>
          <div className="match-list">
            {!loading && resolved.length === 0 && <p className="empty-state">No confirmed matches yet.</p>}
            {limitedResolved.visibleRows.map((match) => {
              const activity = activityById.get(match.mediaActivityId);
              return (
                <div className="match-row" key={match.ratingMatchId}>
                  <div className="match-row-main">
                    <span className={STATUS_CLASS[match.matchStatus]}>{STATUS_LABEL[match.matchStatus]}</span>
                  </div>
                  <p className="match-input">Activity: {describeActivity(activity)}</p>
                  <p className="match-suggestion">Rating: {describeMatchedRating(match, ratingsById)}</p>
                </div>
              );
            })}
          </div>
          <LimitedRowsControls {...limitedResolved} total={resolved.length} />
        </div>}
      </div>
    </>
  );
}
