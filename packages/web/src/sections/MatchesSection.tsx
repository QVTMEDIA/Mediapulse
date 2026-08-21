import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  correctMatch,
  listMatches,
  listMediaActivity,
  listProjectRatingsDatasets,
  listRatingRows,
  recomputeMatches,
} from '../api/client';
import type { MediaActivityRow, Project, RatingMatch, RatingRow } from '../api/contracts';

function describeRatingOption(row: RatingRow) {
  const rating = row.rating === null ? 'no rating value' : row.rating;
  return `${row.station} · ${row.day} · ${row.programme || 'No programme'} · ${rating}`;
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
  const base = `${row.station} · ${row.day} · ${row.programme || 'No programme'} · ${row.spots} spot${row.spots === 1 ? '' : 's'}`;
  // cost is null when the upload never had a Cost/Rate column mapped —
  // omit the clause entirely rather than showing a misleading "spend 0".
  return row.cost !== null ? `${base} · spend ${row.cost.toLocaleString()}` : base;
}

function describeRating(row?: RatingRow) {
  if (!row) return 'Rating no longer available';
  const rating = row.rating === null ? 'no rating value' : `rating ${row.rating}`;
  return `${row.station} · ${row.day} · ${row.programme || 'No programme'} · ${rating}`;
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

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const [matchResults, activityResults, datasets] = await Promise.all([
        listMatches(projectId),
        listMediaActivity(projectId),
        listProjectRatingsDatasets(projectId),
      ]);
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
      await recomputeMatches(project.projectId);
      await refresh(project.projectId);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not recompute matches.');
    } finally {
      setIsRecomputing(false);
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
  const ratingOptions = Array.from(ratingsById.values()).sort((a, b) =>
    `${a.station} ${a.day} ${a.programme}`.localeCompare(`${b.station} ${b.day} ${b.programme}`),
  );

  return (
    <>
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

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Needs review</h2>
            <p>Fuzzy-matched spots — confirm the suggestion or reject it</p>
          </div>
        </div>
        <div className="match-list">
          {!loading && suggested.length === 0 && <p className="empty-state">Nothing needs review right now.</p>}
          {suggested.map((match) => {
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
      </div>

      <div className="content-grid bottom-grid">
        <div className="panel">
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
            {unmatched.map((match) => (
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
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Confirmed</h2>
              <p>Exact key matches and manually confirmed rows</p>
            </div>
          </div>
          <div className="match-list">
            {!loading && resolved.length === 0 && <p className="empty-state">No confirmed matches yet.</p>}
            {resolved.map((match) => (
              <div className="match-row" key={match.ratingMatchId}>
                <div className="match-row-main">
                  <span className={STATUS_CLASS[match.matchStatus]}>{STATUS_LABEL[match.matchStatus]}</span>
                </div>
                <p className="match-input">{describeActivity(activityById.get(match.mediaActivityId))}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
