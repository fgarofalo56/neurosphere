import type { ReactElement } from "react";
import { ConfigError } from "./config";

export function ConfigErrorScreen({ error }: { readonly error: unknown }): ReactElement {
  const problems =
    error instanceof ConfigError
      ? error.problems
      : ["Unexpected error while loading configuration"];
  return (
    <main role="alert" aria-labelledby="config-error-title">
      <h1 id="config-error-title">Configuration error</h1>
      <p>
        NeuroSphere could not start because /config.json is missing or invalid. Contact your
        administrator.
      </p>
      <ul>
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </main>
  );
}
