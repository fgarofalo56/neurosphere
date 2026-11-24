/**
 * The table reads the same wire shapes as the map. They are re-exported from the map's type module
 * (types only, no sigma) so the node kinds, facets and search types never drift apart.
 */
export type {
  Coverage,
  CoverageState,
  Health,
  MapNodeFacets,
  NodeKind,
  NodeMetrics,
  Provenance,
  SearchMatch,
  TruncationReason,
  ViewportEdge,
  ViewportNode,
  ViewportResponse,
} from "../map/types";
