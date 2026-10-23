# G07 FinOps forecast evidence (PRP-21 item 4)

`forecast-vs-actual-sandbox.json` records forecast versus actual cost rows.

- Environment: sandbox in-memory ledger, synthetic data (sandbox generator seed 7, one synthetic
  month, October 2026, 2 domains). No production data, no network, no paid call.
- Method: `linear_trend_ols` - an ordinary least squares line over complete daily totals of the
  17 days before 2026-10-18, extrapolated 14 days. The uncertainty band is the normal-approximation
  prediction interval (z = 1.96, about 95 %), clamped at 0. Estimated and invoiced cost are
  separate series and are never summed. Unknown stays `null` (`actual_status: "unknown"`), never 0.
- Price version: the file cites the price version id (`sandbox-prices-2026-10`) of the estimated
  observations.
- This is a backtest on synthetic data: it shows the hook and the method work end to end. It is not
  a statement about real spend, not a savings claim, and says nothing about forecast accuracy on
  production data.

Reproduce (from the repository root):

```
uv run python -m neurosphere_api.finops
```

The command regenerates the JSON deterministically (only `generated_on` changes between runs).
