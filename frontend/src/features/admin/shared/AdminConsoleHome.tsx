import type { ReactElement } from "react";
import { Link } from "react-router";
import { PageTemplate, Panel } from "../../../design-system";
import { ADMIN_AREAS } from "./areas";
import { ADMIN_STRINGS } from "./strings";
import { checklistCounts, restartCount, useChecklist, useSettings } from "./systemHooks";

/**
 * The console landing for the Admin persona: links to the areas, the first-run checklist summary
 * and the restart-required count. A summary that cannot be read is "unknown", never zero.
 */
export function AdminConsoleHome({ title }: { readonly title: string }): ReactElement {
  const checklist = useChecklist({});
  const settings = useSettings({});
  const counts = checklist.isSuccess ? checklistCounts(checklist.data) : undefined;
  const restarts = settings.isSuccess ? restartCount(settings.data) : undefined;

  return (
    <PageTemplate title={title} description={ADMIN_STRINGS.consoleDescription} layout="grid">
      <Panel title={ADMIN_STRINGS.areasHeading}>
        <ul data-testid="admin-areas">
          {ADMIN_AREAS.map((area) => (
            <li key={area.id}>
              <Link to={area.to}>{area.label}</Link>: {area.description}
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title={ADMIN_STRINGS.checklistHeading}>
        <p data-testid="checklist-summary">
          {counts === undefined
            ? ADMIN_STRINGS.summaryUnknown
            : ADMIN_STRINGS.checklistSummary(counts.done, counts.total)}
        </p>
      </Panel>
      <Panel title={ADMIN_STRINGS.restartHeading}>
        <p data-testid="restart-summary">
          {restarts === undefined
            ? ADMIN_STRINGS.summaryUnknown
            : ADMIN_STRINGS.restartCount(restarts)}
        </p>
      </Panel>
    </PageTemplate>
  );
}
