"""Declared SQLite rewrites that let T-SQL run on the contract stub (test support only).

Every rule is an emulator-parity gap (PRP-11 G12). They prove the SHAPE of the statements the
Synapse dialects emit, not that Synapse accepts them. Order matters: object-existence and DDL
forms are rewritten while brackets are still present, then bracket quoting is normalised, and
only then do the base ``decimal-cost`` rules run (they match double-quoted identifiers).
"""

from __future__ import annotations

from neurosphere_core.analytics.base import RewriteRule, Shim
from neurosphere_core.analytics.base.stub import decimal_cost_shim

_HOUR = r"DATEADD\(hour, DATEDIFF\(hour, 0, (\[event_time\])\), 0\)"
_DAY = r"DATEADD\(day, DATEDIFF\(day, 0, (\[event_time\])\), 0\)"


def tsql_query_shim() -> Shim:
    return Shim(
        name="tsql-query-rewrites",
        description=(
            "T-SQL SELECT TOP n -> trailing LIMIT n; OPTION (LABEL = ...) stripped; "
            "DATEADD/DATEDIFF bucketing -> SUBSTR on the fixed-width ISO text column; "
            "[bracket] quoting -> ANSI double quotes (must precede the scan counter)"
        ),
        rules=(
            RewriteRule("tsql-top", r"^SELECT TOP (\d+) (.*)$", r"SELECT \2 LIMIT \1"),
            RewriteRule("tsql-label", r" OPTION \(LABEL = '[^']*'\)", ""),
            RewriteRule("tsql-hour", _HOUR, r"(SUBSTR(\1, 1, 13) || ':00:00.000000Z')"),
            RewriteRule("tsql-day", _DAY, r"(SUBSTR(\1, 1, 10) || 'T00:00:00.000000Z')"),
            RewriteRule("tsql-brackets", r"\[([A-Za-z0-9_]+)\]", r'"\1"'),
        ),
    )


def tsql_ddl_shim() -> Shim:
    return Shim(
        name="tsql-ddl-rewrites",
        description=(
            "T-SQL migration DDL on SQLite: IF OBJECT_ID/IF NOT EXISTS guards, WITH (DISTRIBUTION"
            " ...), CREATE OR ALTER VIEW, OPENROWSET, sys.objects/sys.stats and N'' literals are"
            " rewritten or stubbed; real catalog, distribution and columnstore behaviour is"
            " untested"
        ),
        rules=(
            RewriteRule(
                "ddl-ledger-exists",
                r"^SELECT COUNT\(\*\) FROM sys\.objects o JOIN sys\.schemas s ON "
                r"s\.schema_id = o\.schema_id WHERE s\.name = N'(\w+)' AND o\.name = N'(\w+)'$",
                r"SELECT COUNT(*) FROM \1.sqlite_master WHERE name = '\2'",
            ),
            RewriteRule("ddl-schema", r"^IF SCHEMA_ID\(.*$", "SELECT 1"),
            RewriteRule("ddl-stats", r"^IF NOT EXISTS \(SELECT 1 FROM sys\.stats.*$", "SELECT 1"),
            RewriteRule(
                "ddl-if-table",
                r"^IF OBJECT_ID\(N'[^']*', N'U'\) IS NULL CREATE TABLE",
                "CREATE TABLE IF NOT EXISTS",
            ),
            RewriteRule("ddl-with-dist", r" WITH \(DISTRIBUTION = [A-Z_]+, CLUSTERED .*\)$", ""),
            RewriteRule(
                "ddl-openrowset",
                r"FROM OPENROWSET\(.*\) WITH \(.*\) AS \[r\]$",
                'FROM "ns"."lake_events" AS "r"',  # a view cannot read another SQLite database
            ),
            RewriteRule(
                "ddl-create-or-alter-view",
                r"^CREATE OR ALTER VIEW (\[\w+\]\.\[\w+\]) AS",
                r"DROP VIEW IF EXISTS \1; CREATE VIEW \1 AS",
            ),
            RewriteRule("ddl-nliteral", r"\bN'", "'"),
            RewriteRule("tsql-brackets", r"\[([A-Za-z0-9_]+)\]", r'"\1"'),
        ),
    )


def synapse_stub_shims() -> tuple[Shim, ...]:
    """Shims for ``StubSqlEndpoint`` (query path). No quantile shim: both modes refuse it."""
    return (tsql_query_shim(), decimal_cost_shim())
