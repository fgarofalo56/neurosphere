import { Button, Checkbox, Field, Input, Select } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { LoadingState, PageTemplate } from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import { useAdminGet, useEtagMutation } from "../shared/transport";
import { pricingPaths } from "../sources/apiPaths";
import {
  MAX_DURATION_SECONDS,
  describeSeconds,
  joinSeconds,
  splitSeconds,
  wholeNumber,
} from "./duration";

export const REVIEW_POLICY_STRINGS = {
  title: "Review policy",
  description:
    "Who may approve, and how long a review may wait. Defaults per review kind, with overrides per action kind. Durations are stored in whole seconds.",
  loading: "Loading the review policy",
  kindDefaults: "Defaults by review kind",
  overrides: "Overrides by action kind",
  noOverrides: "No action overrides.",
  addOverride: "Add override",
  removeOverride: "Remove override",
  preview: "Effective policy",
  save: "Save review policy",
  confirm: "Confirm review policy change",
  saved: "Review policy saved.",
  stale: "The policy changed since you loaded it. Reload and review it before saving again.",
  durationTooLong: "At most 90 days (7,776,000 seconds).",
} as const;

type Permission = "action.approve" | "catalog.curate";
interface Settings {
  readonly self_approval_forbidden: boolean;
  readonly approver_permission: Permission;
  readonly assignment_timeout_seconds: number;
  readonly sla_seconds: number;
  readonly escalation_step_seconds: number;
  readonly max_escalations: number;
  readonly expiry_seconds: number;
}
interface KindDefault {
  readonly review_kind: string;
  readonly policy: Settings;
}
interface ActionOverride {
  readonly review_kind: string;
  readonly action_kind: string;
  readonly policy: Settings;
}
interface PolicyDocument {
  readonly schema_version: string;
  readonly policy_version: string;
  readonly kind_defaults: readonly KindDefault[];
  readonly action_overrides: readonly ActionOverride[];
}
interface PolicyView {
  readonly source: string;
  readonly version: number;
  readonly policy_version: string;
  readonly document: PolicyDocument;
}
interface PolicyWriteView extends PolicyView {
  readonly changes?: readonly {
    readonly path: string;
    readonly before?: unknown;
    readonly after?: unknown;
  }[];
}

const REVIEW_KINDS = [
  "maker_checker",
  "relationship",
  "evaluation_dispute",
  "recommendation",
  "policy_exception",
] as const;
const DURATIONS = [
  ["assignment_timeout_seconds", "Assignment timeout"],
  ["sla_seconds", "SLA"],
  ["escalation_step_seconds", "Escalation step"],
  ["expiry_seconds", "Expiry"],
] as const;
const ACTION_KIND = /^[a-z][a-z0-9_]{0,63}$/;

function DurationField({
  label,
  seconds,
  onChange,
}: {
  readonly label: string;
  readonly seconds: number;
  readonly onChange: (seconds: number) => void;
}): ReactElement {
  const hm = splitSeconds(seconds);
  const tooLong = seconds > MAX_DURATION_SECONDS;
  return (
    <fieldset>
      <legend>{label}</legend>
      <Field label={`${label} hours`}>
        <Input
          inputMode="numeric"
          value={String(hm.hours)}
          onChange={(_e, d) => {
            const n = wholeNumber(d.value);
            if (n !== undefined) onChange(joinSeconds({ ...hm, hours: n }));
          }}
        />
      </Field>
      <Field
        label={`${label} minutes`}
        validationState={tooLong ? "error" : "none"}
        validationMessage={tooLong ? REVIEW_POLICY_STRINGS.durationTooLong : undefined}
      >
        <Input
          inputMode="numeric"
          value={String(hm.minutes)}
          onChange={(_e, d) => {
            const n = wholeNumber(d.value);
            if (n !== undefined && n < 60) onChange(joinSeconds({ ...hm, minutes: n }));
          }}
        />
      </Field>
      {hm.rest > 0 ? <span>+{hm.rest} s</span> : null}
    </fieldset>
  );
}

function SettingsEditor({
  name,
  value,
  onChange,
}: {
  readonly name: string;
  readonly value: Settings;
  readonly onChange: (next: Settings) => void;
}): ReactElement {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <Checkbox
        label={`${name}: self approval forbidden`}
        checked={value.self_approval_forbidden}
        onChange={(_e, d) => onChange({ ...value, self_approval_forbidden: d.checked === true })}
      />
      <Field label={`${name}: approver permission`}>
        <Select
          value={value.approver_permission}
          onChange={(_e, d) => onChange({ ...value, approver_permission: d.value as Permission })}
        >
          <option value="action.approve">action.approve</option>
          <option value="catalog.curate">catalog.curate</option>
        </Select>
      </Field>
      {DURATIONS.map(([field, label]) => (
        <DurationField
          key={field}
          label={`${name}: ${label}`}
          seconds={value[field]}
          onChange={(s) => onChange({ ...value, [field]: s })}
        />
      ))}
      <Field label={`${name}: max escalations (0 to 10)`}>
        <Input
          inputMode="numeric"
          value={String(value.max_escalations)}
          onChange={(_e, d) => {
            const n = wholeNumber(d.value);
            if (n !== undefined && n <= 10) onChange({ ...value, max_escalations: n });
          }}
        />
      </Field>
    </div>
  );
}

function summary(s: Settings): string {
  return `${s.approver_permission}, ${s.self_approval_forbidden ? "no self approval" : "self approval allowed"}, SLA ${describeSeconds(s.sla_seconds)}, escalate every ${describeSeconds(s.escalation_step_seconds)} up to ${s.max_escalations} time(s), expires after ${describeSeconds(s.expiry_seconds)}`;
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function PolicyEditor({
  view,
  etag,
  onSaved,
}: {
  readonly view: PolicyView;
  readonly etag: string | undefined;
  readonly onSaved: () => void;
}): ReactElement {
  const [doc, setDoc] = useState<PolicyDocument>(view.document);
  const [confirm, setConfirm] = useState(false);
  const [newKind, setNewKind] = useState<string>(REVIEW_KINDS[0]);
  const [newAction, setNewAction] = useState("");
  const save = useEtagMutation<PolicyDocument, PolicyWriteView>((d) => ({
    method: "PUT",
    path: pricingPaths.reviewPolicy(),
    body: d,
    ifMatch: etag,
  }));
  const stale = save.isError && save.error.status === 409;
  const diff: { field: string; before: string; after: string }[] = [];
  if (doc.policy_version !== view.document.policy_version) {
    diff.push({
      field: "policy_version",
      before: view.document.policy_version,
      after: doc.policy_version,
    });
  }
  for (const k of doc.kind_defaults) {
    const old = view.document.kind_defaults.find((o) => o.review_kind === k.review_kind);
    if (!same(old?.policy, k.policy)) {
      diff.push({
        field: `default ${k.review_kind}`,
        before: old === undefined ? "none" : summary(old.policy),
        after: summary(k.policy),
      });
    }
  }
  const key = (o: { review_kind: string; action_kind: string }): string =>
    `${o.review_kind}/${o.action_kind}`;
  for (const o of doc.action_overrides) {
    const old = view.document.action_overrides.find((x) => key(x) === key(o));
    if (!same(old?.policy, o.policy)) {
      diff.push({
        field: `override ${key(o)}`,
        before: old === undefined ? "none" : summary(old.policy),
        after: summary(o.policy),
      });
    }
  }
  for (const old of view.document.action_overrides) {
    if (!doc.action_overrides.some((x) => key(x) === key(old))) {
      diff.push({ field: `override ${key(old)}`, before: summary(old.policy), after: "removed" });
    }
  }
  const tooLong = [...doc.kind_defaults, ...doc.action_overrides].some((e) =>
    DURATIONS.some(([f]) => e.policy[f] > MAX_DURATION_SECONDS || e.policy[f] < 1),
  );
  const versionOk = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(doc.policy_version);

  return (
    <>
      <Field label="Policy version" required>
        <Input
          value={doc.policy_version}
          onChange={(_e, d) => setDoc({ ...doc, policy_version: d.value })}
        />
      </Field>
      <h2>{REVIEW_POLICY_STRINGS.kindDefaults}</h2>
      {doc.kind_defaults.map((k) => (
        <section
          key={k.review_kind}
          aria-label={`Default for ${k.review_kind}`}
          data-testid="kind-default"
        >
          <h3>{k.review_kind}</h3>
          <SettingsEditor
            name={k.review_kind}
            value={k.policy}
            onChange={(policy) =>
              setDoc({
                ...doc,
                kind_defaults: doc.kind_defaults.map((x) =>
                  x.review_kind === k.review_kind ? { ...x, policy } : x,
                ),
              })
            }
          />
        </section>
      ))}
      <h2>{REVIEW_POLICY_STRINGS.overrides}</h2>
      {doc.action_overrides.length === 0 ? <p>{REVIEW_POLICY_STRINGS.noOverrides}</p> : null}
      {doc.action_overrides.map((o) => (
        <section key={key(o)} aria-label={`Override ${key(o)}`} data-testid="action-override">
          <h3>{key(o)}</h3>
          <SettingsEditor
            name={key(o)}
            value={o.policy}
            onChange={(policy) =>
              setDoc({
                ...doc,
                action_overrides: doc.action_overrides.map((x) =>
                  key(x) === key(o) ? { ...x, policy } : x,
                ),
              })
            }
          />
          <Button
            size="small"
            aria-label={`${REVIEW_POLICY_STRINGS.removeOverride} ${key(o)}`}
            onClick={() =>
              setDoc({
                ...doc,
                action_overrides: doc.action_overrides.filter((x) => key(x) !== key(o)),
              })
            }
          >
            {REVIEW_POLICY_STRINGS.removeOverride}
          </Button>
        </section>
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <Field label="Override review kind">
          <Select value={newKind} onChange={(_e, d) => setNewKind(d.value)}>
            {REVIEW_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="Override action kind"
          validationState={newAction !== "" && !ACTION_KIND.test(newAction) ? "error" : "none"}
          validationMessage={
            newAction !== "" && !ACTION_KIND.test(newAction)
              ? "Lower-case letters, digits and _."
              : undefined
          }
        >
          <Input value={newAction} onChange={(_e, d) => setNewAction(d.value)} />
        </Field>
        <Button
          disabled={
            !ACTION_KIND.test(newAction) ||
            doc.action_overrides.some((o) => key(o) === `${newKind}/${newAction}`) ||
            doc.kind_defaults.every((k) => k.review_kind !== newKind)
          }
          onClick={() => {
            const base = doc.kind_defaults.find((k) => k.review_kind === newKind);
            if (base === undefined) return;
            setDoc({
              ...doc,
              action_overrides: [
                ...doc.action_overrides,
                { review_kind: newKind, action_kind: newAction, policy: base.policy },
              ],
            });
            setNewAction("");
          }}
        >
          {REVIEW_POLICY_STRINGS.addOverride}
        </Button>
      </div>
      <h2>{REVIEW_POLICY_STRINGS.preview}</h2>
      <ul data-testid="effective-policy">
        {doc.kind_defaults.map((k) => (
          <li key={k.review_kind}>
            {k.review_kind}: {summary(k.policy)}
          </li>
        ))}
        {doc.action_overrides.map((o) => (
          <li key={key(o)}>
            {key(o)}: {summary(o.policy)}
          </li>
        ))}
      </ul>
      <div>
        <Button
          appearance="primary"
          disabled={!versionOk || tooLong || diff.length === 0}
          onClick={() => {
            save.reset();
            setConfirm(true);
          }}
        >
          {REVIEW_POLICY_STRINGS.save}
        </Button>
      </div>
      {confirm ? (
        <ChangeConfirmDialog
          open
          title={REVIEW_POLICY_STRINGS.confirm}
          target="review-policy"
          version={etag ?? `version ${view.version}`}
          diff={diff}
          reasonMode="code"
          submitting={save.isPending}
          error={
            save.isError ? (
              <span data-testid="policy-error">
                {stale ? REVIEW_POLICY_STRINGS.stale : changeErrorText(save.error)}
              </span>
            ) : undefined
          }
          onSubmit={() =>
            save.mutate(doc, {
              onSuccess: () => {
                setConfirm(false);
                onSaved();
              },
            })
          }
          onClose={() => {
            setConfirm(false);
            save.reset();
          }}
        />
      ) : null}
    </>
  );
}

function ReviewPolicyBody(): ReactElement {
  const query = useAdminGet<PolicyView>("admin-review-policy", {
    path: pricingPaths.reviewPolicy(),
  });
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={REVIEW_POLICY_STRINGS.loading} rows={4} />
      </div>
    );
  }
  return (
    <>
      {saved ? (
        <div role="status" data-testid="policy-saved">
          {REVIEW_POLICY_STRINGS.saved}
        </div>
      ) : null}
      <PolicyEditor
        key={query.data.etag ?? query.data.data.version}
        view={query.data.data}
        etag={query.data.etag}
        onSaved={() => {
          setSaved(true);
          void queryClient.invalidateQueries({ queryKey: ["admin-review-policy"] });
        }}
      />
    </>
  );
}

export function ReviewPolicyPage(): ReactElement {
  return (
    <PageTemplate
      title={REVIEW_POLICY_STRINGS.title}
      description={REVIEW_POLICY_STRINGS.description}
    >
      <AdminTabs />
      <ReviewPolicyBody />
    </PageTemplate>
  );
}
