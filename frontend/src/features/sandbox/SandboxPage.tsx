import { Button, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import { PageTemplate } from "../../design-system";
import { useSandboxStatus } from "./hooks";
import { SandboxToggle } from "./SandboxToggle";
import { STRINGS } from "./strings";

const NO_PARAMS: Record<string, never> = {};

function Summary(): ReactElement {
  const query = useSandboxStatus(NO_PARAMS);
  if (query.isError) {
    const forbidden = query.error instanceof ForbiddenError;
    return (
      <MessageBar intent="warning" role="alert" data-testid="sandbox-error">
        <MessageBarBody>
          <MessageBarTitle>{forbidden ? STRINGS.forbidden : STRINGS.unavailable}</MessageBarTitle>
          {forbidden ? STRINGS.forbiddenDetail : STRINGS.unavailableDetail}{" "}
          {forbidden ? null : <Button onClick={() => void query.refetch()}>{STRINGS.retry}</Button>}
        </MessageBarBody>
      </MessageBar>
    );
  }
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const data = query.data;
  return (
    <>
      <dl data-testid="sandbox-flags">
        <dt>{STRINGS.environment}</dt>
        <dd>{data.environment}</dd>
        <dt>{STRINGS.synthetic}</dt>
        <dd>{data.synthetic ? STRINGS.yes : ""}</dd>
      </dl>
      <table aria-label={STRINGS.pageTitle}>
        <thead>
          <tr>
            <th scope="col">{STRINGS.headers.kind}</th>
            <th scope="col">{STRINGS.headers.count}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.counts).map(([kind, count]) => (
            <tr key={kind} data-testid="sandbox-row">
              <td>
                {kind in STRINGS.kinds ? STRINGS.kinds[kind as keyof typeof STRINGS.kinds] : kind}
              </td>
              <td>{count}</td>
            </tr>
          ))}
          <tr>
            <td>{STRINGS.relations}</td>
            <td>{data.relations}</td>
          </tr>
        </tbody>
      </table>
      <p>
        {STRINGS.total}: <span data-testid="sandbox-total">{data.total}</span>
      </p>
    </>
  );
}

export function SandboxPage(): ReactElement {
  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      actions={<SandboxToggle />}
    >
      <Summary />
    </PageTemplate>
  );
}
