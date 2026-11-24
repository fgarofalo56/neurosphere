/** Incident view building blocks shared by the map and the accessible table. */
export {
  concernsImpact,
  deriveImpact,
  highlightOf,
  type GraphPresence,
  type ImpactLevelRows,
  type ImpactRow,
  type ImpactSelection,
  type ImpactState,
} from "./impactState";
export {
  DEFAULT_IMPACT_DEPTH,
  MAX_IMPACT_DEPTH,
  MIN_IMPACT_DEPTH,
  clampDepth,
  fetchImpact,
  impactPath,
  useMapImpact,
} from "./useMapImpact";
export { IMPACT_STRINGS } from "./strings";
