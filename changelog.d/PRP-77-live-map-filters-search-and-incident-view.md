### Added
- Live map filter bar for node type, tag, environment, cloud and health, kept in the URL and shared with the table view (PRP-77, PR #405).
- Live map search box that jumps to any node: server search, neighbourhood merge under the 2000-node client cap, camera centring (PRP-77, PR #405).
- Incident view: "Show impact" (shortcut `i`) highlights every dependent of the selected node with a ring and a text list by depth (1 to 5), recomputes live when health or topology changes, and starts by itself when the selected node turns failing (PRP-77, PR #405).
- Map table parity: the same filters, search and impact toggle, plus kind, environment, cloud, health, error-rate and depth columns (PRP-77, PR #405).
- Own shapes and labels for service, tool and MCP server nodes, and an error-rate size option (PRP-77, PR #405).
- Interaction-latency measurement `frontend/tests/e2e/map-latency.spec.ts` and evidence file `docs/evidence/G07/map/interaction-latency.json` for the supported 2000-node view (PRP-77, PR #405).

### Fixed
- The map now refetches when the server pushes a topology change, so new agents and edges appear without a reload (PRP-77, PR #405).
- A live delta that omits a metric no longer blanks the last known value, and model nodes now update live (PRP-77, PR #405).
