import { Input } from "@fluentui/react-components";
import type { ReactElement } from "react";

// Fluent's Input type union has no "file", but it passes `type` through to the native element, so
// a Fluent control stays in use (the PRP-28 rule: no raw native form controls in feature pages).
const FILE_TYPE = { type: "file", accept: "application/json,.json" } as Record<string, string>;

/** Reads a chosen JSON file as text. The text goes into a field the user can still edit. */
export function JsonFileInput({
  label,
  onText,
}: {
  readonly label: string;
  readonly onText: (text: string) => void;
}): ReactElement {
  return (
    <Input
      {...FILE_TYPE}
      aria-label={label}
      onChange={(event) => {
        const file = event.target.files?.[0];
        if (file !== undefined) void file.text().then(onText);
      }}
    />
  );
}
