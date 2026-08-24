import type { MappingWarning } from './api/contracts';

// Logical mapping-field names read fine in the mapping dict but not in a
// sentence a user reads once and acts on — kept in sync with the field
// names services/api/app/parsing.py's REQUIRED/OPTIONAL_MAPPING_FIELDS and
// RATINGS_REQUIRED/OPTIONAL_MAPPING_FIELDS use. Shared between the media
// report upload (App.tsx) and the ratings file upload (RatingsSection.tsx)
// — the two upload flows this warning can come back from.
const MAPPING_FIELD_LABELS: Record<string, string> = {
  channel: 'Station',
  programme: 'Programme',
  spots: 'Spots',
  brand: 'Brand',
  medium: 'Medium',
  date: 'Date',
  day: 'Day',
  rate: 'Rate',
  cost: 'Cost',
  time_band: 'Time Band',
  rating: 'Rating',
  source: 'Source',
};

export function describeMappingWarning(warning: MappingWarning): string {
  const label = MAPPING_FIELD_LABELS[warning.field] ?? warning.field;
  return (
    `${label}: the saved mapping template used "${warning.templateColumn}", but this file's ` +
    `"${warning.detectedColumn}" column looks like a better match. Check the template before trusting ` +
    'this upload — a wrong Time Band or Station mapping can silently produce 0 matches.'
  );
}
