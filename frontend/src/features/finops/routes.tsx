import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ForecastPage } from "./ForecastPage";
import { FINOPS_FORECAST_ROUTE } from "./paths";

export const finopsRoutes: RouteObject[] = [
  { path: FINOPS_FORECAST_ROUTE, element: <ForecastPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function finopsNavItems(): NavItem[] {
  return [{ to: `/${FINOPS_FORECAST_ROUTE}`, label: "Forecast", permission: "data.read" }];
}
