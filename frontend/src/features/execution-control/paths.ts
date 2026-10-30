/**
 * Path constants for the execution control (emergency disable) page. Kept free of heavy imports
 * so the app shell can reference routes without loading Fluent UI.
 *
 * GET reads the state; PUT needs config.manage and the API answers 403 for anyone else.
 */
export const EMERGENCY_DISABLE_PATH = "/api/v1/actions/emergency-disable";

export const EXECUTION_CONTROL_ROUTE = "admin/execution-control";
