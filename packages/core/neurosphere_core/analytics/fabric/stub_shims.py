"""Declared SQLite shims that let ``StubSqlEndpoint`` run ``FabricDialect`` statements.

Each rule is a G12 emulator-parity gap: SQLite is not T-SQL. Order matters. Quoting is
normalised FIRST so the stub's scan-counter (which matches the table as the ANSI renderer
quotes it) and the decimal-cost shim (which matches ``"cost_amount"``) both see double quotes.
Nothing here is evidence that Fabric accepts these statements.
"""

from __future__ import annotations

from neurosphere_core.analytics.base import RewriteRule, Shim, standard_shims

QUANTILE_FUNCTION = "NS_FABRIC_PERCENTILE"


def fabric_stub_shims() -> tuple[Shim, ...]:
    """Fabric-specific rewrites followed by the standard decimal and quantile shims."""
    dialect_shim = Shim(
        name="fabric-tsql-rewrite",
        description=(
            "T-SQL rendered by FabricDialect is rewritten for SQLite: [bracket] quoting to "
            '"double" quotes, SELECT TOP (n) to a trailing LIMIT, DATETRUNC(day|hour) to '
            "fixed-width ISO text truncation, APPROX_PERCENTILE_CONT ... WITHIN GROUP to a "
            "two-argument exact nearest-rank aggregate"
        ),
        rules=(
            RewriteRule("bracket-quoting", r"\[([^\]]+)\]", r'"\1"'),
            RewriteRule("top-to-limit", r"(?s)^SELECT TOP \((\d+)\) (.*)$", r"SELECT \2 LIMIT \1"),
            RewriteRule(
                "datetrunc-hour",
                r'DATETRUNC\(hour, ("[a-z_]+")\)',
                r"(SUBSTR(\1, 1, 13) || ':00:00.000000Z')",
            ),
            RewriteRule(
                "datetrunc-day",
                r'DATETRUNC\(day, ("[a-z_]+")\)',
                r"(SUBSTR(\1, 1, 10) || 'T00:00:00.000000Z')",
            ),
            RewriteRule(
                "approx-percentile-cont",
                r'APPROX_PERCENTILE_CONT\(([0-9.]+)\) WITHIN GROUP \(ORDER BY ("[a-z_]+")\)',
                rf"{QUANTILE_FUNCTION}(\2, \1)",
            ),
        ),
    )
    return (dialect_shim, *standard_shims(QUANTILE_FUNCTION))


__all__ = ["QUANTILE_FUNCTION", "fabric_stub_shims"]
