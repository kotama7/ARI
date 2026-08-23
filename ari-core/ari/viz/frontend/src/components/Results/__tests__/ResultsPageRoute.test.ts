import { describe, expect, it } from 'vitest';
import { runFromResultsHash } from '../ResultsPage';

describe('paper workspace run route', () => {
  it('reads the explicit run id from the hash query', () => {
    expect(runFromResultsHash('#/results?run=paper%20run')).toBe('paper run');
  });

  it('returns an empty selection when the run query is absent', () => {
    expect(runFromResultsHash('#/results')).toBe('');
  });
});
