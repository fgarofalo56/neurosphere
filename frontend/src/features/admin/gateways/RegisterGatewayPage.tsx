import { Button, Field, Input, Select } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link } from "react-router";
import { LoadingState, PageTemplate } from "../../../design-system";
import { ForbiddenError, StaleVersionError, type ApiError } from "../../../api/index.js";
import { QueryErrorState } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import { useEtagMutation } from "../shared/transport";
import { gatewayDetailHref } from "../../gateways/paths";
import { NoDataEmptyState } from "../../source-status";
import { existingPaths } from "../sources/apiPaths";
import { useReadableDomains } from "../sources/hooks";

export const GATEWAY_STRINGS = {
  title: "Register a gateway",
  description:
    "Register an API Management instance so its gateway can be observed. The API checks that you may register in the chosen domain.",
  domain: "Domain",
  arm: "API Management resource id",
  armHint:
    "/subscriptions/<id>/resourceGroups/<name>/providers/Microsoft.ApiManagement/service/<name>",
  armInvalid: "This does not look like an API Management resource id.",
  workspace: "Log Analytics workspace id (optional)",
  workspaceInvalid: "A workspace id is a GUID.",
  submit: "Register gateway",
  noDomains: "You can read no domains, so there is nothing to register into.",
  registered: "Gateway registered",
  open: "Open gateway detail",
  failed: "Registration failed",
} as const;

export const ARM_ID =
  /^\/subscriptions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/resourceGroups\/[A-Za-z0-9_.()-]{1,90}\/providers\/Microsoft\.ApiManagement\/service\/[A-Za-z][A-Za-z0-9-]{0,49}$/i;
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Registered {
  readonly id: string;
  readonly name: string;
  readonly domain_id: string;
}

function failureText(error: ApiError): string {
  const code = error.problem?.code ?? String(error.status);
  const detail = error.problem?.detail ?? error.message;
  if (error instanceof StaleVersionError) return `${code}: ${detail}`;
  if (error instanceof ForbiddenError) return `${code}: ${error.problem?.reason ?? detail}`;
  return `${code}: ${detail}`;
}

function RegisterBody(): ReactElement {
  const domains = useReadableDomains();
  const [domain, setDomain] = useState("");
  const [arm, setArm] = useState("");
  const [workspace, setWorkspace] = useState("");
  const register = useEtagMutation<
    { readonly domain: string; readonly arm: string; readonly workspace: string },
    Registered
  >((v) => ({
    method: "POST",
    path: existingPaths.gateways(v.domain),
    body: {
      arm_resource_id: v.arm,
      ...(v.workspace === "" ? {} : { workspace_id: v.workspace }),
    },
  }));

  if (domains.isError) {
    return <QueryErrorState error={domains.error} onRetry={() => void domains.refetch()} />;
  }
  if (domains.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label="Loading domains" rows={2} />
      </div>
    );
  }
  const items = domains.data.data.items;
  if (items.length === 0) {
    return (
      <NoDataEmptyState
        what={GATEWAY_STRINGS.noDomains}
        sources={[]}
        adminHref="/admin/domains"
        adminLabel="Create a domain in Admin Domains"
        testId="empty-state"
      />
    );
  }
  const chosen = domain === "" ? (items[0]?.domain_id ?? "") : domain;
  const armTrim = arm.trim();
  const wsTrim = workspace.trim();
  const armBad = armTrim !== "" && !ARM_ID.test(armTrim);
  const wsBad = wsTrim !== "" && !GUID.test(wsTrim);
  const valid = ARM_ID.test(armTrim) && !wsBad && chosen !== "";

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) register.mutate({ domain: chosen, arm: armTrim, workspace: wsTrim });
        }}
        style={{ display: "grid", gap: 12, maxWidth: 640 }}
      >
        <Field label={GATEWAY_STRINGS.domain} required>
          <Select value={chosen} onChange={(_e, d) => setDomain(d.value)}>
            {items.map((d) => (
              <option key={d.domain_id} value={d.domain_id}>
                {d.display_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label={GATEWAY_STRINGS.arm}
          required
          hint={GATEWAY_STRINGS.armHint}
          validationState={armBad ? "error" : "none"}
          validationMessage={armBad ? GATEWAY_STRINGS.armInvalid : undefined}
        >
          <Input value={arm} onChange={(_e, d) => setArm(d.value)} />
        </Field>
        <Field
          label={GATEWAY_STRINGS.workspace}
          validationState={wsBad ? "error" : "none"}
          validationMessage={wsBad ? GATEWAY_STRINGS.workspaceInvalid : undefined}
        >
          <Input value={workspace} onChange={(_e, d) => setWorkspace(d.value)} />
        </Field>
        <div>
          <Button type="submit" appearance="primary" disabled={!valid || register.isPending}>
            {GATEWAY_STRINGS.submit}
          </Button>
        </div>
      </form>
      {register.isError ? (
        <div role="alert" data-testid="register-error">
          {GATEWAY_STRINGS.failed}: {failureText(register.error)}
        </div>
      ) : null}
      {register.isSuccess ? (
        <div role="status" data-testid="register-done">
          {GATEWAY_STRINGS.registered}: <code>{register.data.data.name}</code>{" "}
          <Link to={gatewayDetailHref(register.data.data.domain_id, register.data.data.id)}>
            {GATEWAY_STRINGS.open}
          </Link>
        </div>
      ) : null}
    </>
  );
}

export function RegisterGatewayPage(): ReactElement {
  return (
    <PageTemplate title={GATEWAY_STRINGS.title} description={GATEWAY_STRINGS.description}>
      <AdminTabs />
      <RegisterBody />
    </PageTemplate>
  );
}
