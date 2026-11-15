### Changed
- PRP-18 (round 2): the map viewport reads edges through one bulk `RepositoryGraphQuery.edges_among` call (new `EdgesAmongQuery` protocol, per-node walk kept as fallback) instead of one neighbour read per node; the realtime pump sleeps the smaller of the poll interval and the scope refresh interval; the map client ignores deltas after a 4403 revoke; replay gap detail for a missing parent is generic and no longer reveals another domain; gap badges have unique keys; the map table no longer steals focus on `Load more` and falls back to a tabbable row; the mock API answers an unknown replay trace with problem+json 404 (PR #280).

### Security
- The replay read-only import guard now also catches relative imports, `importlib.import_module` and `__import__` calls.
