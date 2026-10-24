import { Switch } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { STRINGS } from "./strings";
import { useSandboxStore } from "./store";

/** Labelled switch. Turning it on shows the banner and the sandbox route family. */
export function SandboxToggle(): ReactElement {
  const enabled = useSandboxStore((s) => s.enabled);
  const setEnabled = useSandboxStore((s) => s.setEnabled);
  return (
    <Switch
      label={STRINGS.toggleLabel}
      checked={enabled}
      onChange={(_event, data) => {
        setEnabled(data.checked);
      }}
    />
  );
}
