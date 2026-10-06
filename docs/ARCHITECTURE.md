# Architecture

The POC builds the **local / open-source analogue** of each managed-cloud
target service, so the same architecture promotes to the cloud later by
swapping the gateway, catalog, and identity for their managed
equivalents — the *pattern* is identical.

## The zero-move flow

```text
   client / MCP agent
          |  (bearer token from the local issuer)
          v
   +--------------+   only path to data
   |  gateway     |   JWT . rate-limit . meter . correlation-id
   |  (OSS)       |
   +------+-------+
          | REST / OData
          v
   +--------------+   auto-generated REST + GraphQL + OpenAPI (no hand-written API)
   | Data API     |
   | Builder      |
   +------+-------+
          |  (internal network only — unreachable from clients)
          v
   +--------------+   system of record — data NEVER leaves here
   |  PostgreSQL  |   (synthetic, clearly-labeled dataset)
   +--------------+

   catalog service ---- publishes the OpenAPI + owner + classification + request path
   prometheus/grafana -- per-consumer call + latency metrics
```

> _Fill in the concrete network config + the local <-> managed mapping
> table during the build (PRP §3)._
