# Demo script (~10 minutes)

> _Write this during the build. It should let a presenter run the live
> end-to-end demo and narrate the zero-move story._

Outline to fill in:
1. `cp .env.example .env && make demo` — bring the stack up, seed, run
   the query.
2. Show the headline answer printed **through the gateway** (with the
   correlation id).
3. Prove zero-move: show the system of record is unreachable from the
   client network (`make test` -> `test_zero_move.py`), and that the
   only path is the gateway.
4. Show auth at the edge: no token -> 401, valid token -> 200,
   over-limit -> 429.
5. Show discovery: the catalog entry + the OpenAPI.
6. Show the MCP tool answering the same question as an agent would.
7. Show the dashboard: per-consumer calls + latency.
8. Close on the Azure swap (`docs/AZURE-DEPLOYMENT.md`): same pattern,
   managed services.
