import { createContext, useContext } from "react";
import type { AppConfig } from "./config";

export const ConfigContext = createContext<AppConfig | null>(null);

export function useAppConfig(): AppConfig {
  const config = useContext(ConfigContext);
  if (config === null) throw new Error("useAppConfig must be used inside <App>");
  return config;
}
