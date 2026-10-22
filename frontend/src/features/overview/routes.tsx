import type { RouteObject } from "react-router";
import { OverviewPage } from "./OverviewPage";

/** The home route (index of the shell layout). */
export const overviewRoutes: RouteObject[] = [{ index: true, element: <OverviewPage /> }];
