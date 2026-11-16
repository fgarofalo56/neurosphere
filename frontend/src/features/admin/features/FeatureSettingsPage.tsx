import { Checkbox, Button, Field, Input, Textarea } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { LoadingState, PageTemplate, StatusPill } from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import { useAdminGet, useEtagMutation } from "../shared/transport";
import { settingPaths } from "../sources/apiPaths";
import { CredentialReferenceField } from "../sources/CredentialReferenceField";
import { describeReference } from "../sources/credentialReference";
import type { CredentialReference } from "../sources/types";
import {
  EMPTY_DRAFT,
  SETTING_KEYS,
  SETTING_SPECS,
  type SettingKey,
  bodyFromDraft,
  draftDiff,
  draftFromStored,
  draftProblem,
  type SettingDraft,
  type SettingSpec,
} from "./settingSpecs";

export const FEATURE_STRINGS = {
  title: "Models and feature settings",
  description:
    "Runtime settings stored by the platform: endpoints, resource ids and credential references only. Changes apply after the API and workers restart.",
  loading: "Loading settings",
  restartNotice: "Saved. This setting applies after the API and workers restart.",
  restartRequired: "Restart required",
  applied: "Applied",
  source: "Source",
  revision: "Revision",
  enabled: "Enabled",
  save: "Save setting",
  confirm: "Confirm setting change",
  noDiff: "Nothing changed.",
  writeTargetsNote:
    "Write targets are shown as stored. Turning a stored write target into a registered connector needs PRP-54, which has not shipped; until then this page cannot register or edit them.",
  noStored: "Nothing is stored for this setting; it follows the environment or the default.",
  stale: "This setting changed since you loaded it. Reload and try again.",
  reload: "Reload",
} as const;

interface SettingEntry {
  readonly document_id: string;
  readonly version: number;
  readonly etag: string;
  readonly value: Record<string, unknown>;
}
interface SettingView {
  readonly key: string;
  readonly source: "stored" | "env" | "default";
  readonly stored_revision: number | null;
  readonly applied_revision: number | null;
  readonly restart_required: boolean;
  readonly applied_by_runtime: boolean;
  readonly etag: string | null;
  readonly entries: readonly SettingEntry[];
}
interface WriteResult {
  readonly key: string;
  readonly restart_required: boolean;
  readonly diff: readonly {
    readonly pointer: string;
    readonly before?: unknown;
    readonly after?: unknown;
  }[];
}

function showValue(value: unknown): string {
  return value === undefined ? "unset" : typeof value === "string" ? value : JSON.stringify(value);
}

function initialDraft(spec: SettingSpec, view: SettingView | undefined): SettingDraft {
  const stored = view?.entries[0]?.value;
  const draft = stored === undefined ? EMPTY_DRAFT : draftFromStored(spec, stored);
  if (draft.credential.kind === "none" && spec.credential === "managed_identity") {
    return { ...draft, credential: { kind: "managed_identity", value: "" } };
  }
  return draft;
}

function Meta({ view }: { readonly view: SettingView | undefined }): ReactElement {
  return (
    <p data-testid="setting-meta">
      {FEATURE_STRINGS.source}:{" "}
      <StatusPill
        label={view?.source ?? "default"}
        tone={view?.source === "stored" ? "success" : "neutral"}
      />{" "}
      {FEATURE_STRINGS.revision}: {view?.stored_revision ?? "none"}{" "}
      {view?.restart_required === true ? (
        <StatusPill label={FEATURE_STRINGS.restartRequired} tone="warning" />
      ) : (
        <StatusPill label={FEATURE_STRINGS.applied} tone="neutral" />
      )}
    </p>
  );
}

function SettingCard({
  spec,
  view,
  result,
  onSaved,
}: {
  readonly spec: SettingSpec;
  readonly view: SettingView | undefined;
  readonly result: WriteResult | undefined;
  readonly onSaved: (result?: WriteResult) => void;
}): ReactElement {
  const initial = initialDraft(spec, view);
  const [draft, setDraft] = useState<SettingDraft>(initial);
  const [confirm, setConfirm] = useState(false);
  const save = useEtagMutation<SettingDraft, WriteResult>((d) => ({
    method: "PUT",
    path: settingPaths.one(spec.key),
    body: bodyFromDraft(spec, d),
    ifMatch: view?.etag ?? undefined,
  }));
  const problem = draftProblem(spec, draft);
  const diff = draftDiff(spec, initial, draft);
  const stale = save.isError && save.error.status === 409;
  const headingId = `setting-${spec.key}`;

  return (
    <section aria-labelledby={headingId} data-testid="setting-card" data-key={spec.key}>
      <h2 id={headingId}>{spec.title}</h2>
      <p>{spec.description}</p>
      <Meta view={view} />
      {view?.entries.length === 0 || view === undefined ? <p>{FEATURE_STRINGS.noStored}</p> : null}
      <Checkbox
        label={`${FEATURE_STRINGS.enabled}: ${spec.title}`}
        checked={draft.enabled}
        onChange={(_e, d) => setDraft({ ...draft, enabled: d.checked === true })}
      />
      {spec.fields.map((f) => (
        <Field key={f.name} label={`${spec.title} ${f.label}`} required={f.required} hint={f.hint}>
          {f.kind === "lines" ? (
            <Textarea
              value={draft.values[f.name] ?? ""}
              onChange={(_e, d) =>
                setDraft({ ...draft, values: { ...draft.values, [f.name]: d.value } })
              }
            />
          ) : (
            <Input
              inputMode={f.kind === "number" ? "numeric" : undefined}
              value={draft.values[f.name] ?? ""}
              onChange={(_e, d) =>
                setDraft({ ...draft, values: { ...draft.values, [f.name]: d.value } })
              }
            />
          )}
        </Field>
      ))}
      <CredentialReferenceField
        value={draft.credential}
        allowNone={spec.credential === "optional"}
        allowKeyVault={spec.credential !== "managed_identity"}
        onChange={(credential) => setDraft({ ...draft, credential })}
      />
      <div>
        <Button
          appearance="primary"
          disabled={problem !== undefined}
          title={problem}
          onClick={() => {
            save.reset();
            setConfirm(true);
          }}
        >
          {`${FEATURE_STRINGS.save}: ${spec.title}`}
        </Button>
      </div>
      {result === undefined ? null : (
        <div role="status" data-testid="setting-saved">
          {FEATURE_STRINGS.restartNotice}
          <ul data-testid="setting-result-diff">
            {result.diff.map((d) => (
              <li key={d.pointer}>
                {d.pointer}: {showValue(d.before)} to {showValue(d.after)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {confirm ? (
        <ChangeConfirmDialog
          open
          title={`${FEATURE_STRINGS.confirm}: ${spec.title}`}
          target={spec.key}
          version={view?.etag ?? "none stored"}
          diff={diff}
          reasonMode="code"
          reasonNote={FEATURE_STRINGS.restartNotice}
          submitting={save.isPending}
          error={
            save.isError ? (
              <span data-testid="setting-error">
                {stale ? FEATURE_STRINGS.stale : changeErrorText(save.error)}
              </span>
            ) : undefined
          }
          onSubmit={() =>
            save.mutate(draft, {
              onSuccess: (r) => {
                setConfirm(false);
                onSaved(r.data);
              },
            })
          }
          onClose={() => {
            setConfirm(false);
            save.reset();
            if (stale) onSaved();
          }}
        />
      ) : null}
    </section>
  );
}

function WriteTargetsCard({ view }: { readonly view: SettingView | undefined }): ReactElement {
  return (
    <section
      aria-labelledby="setting-write_targets"
      data-testid="setting-card"
      data-key="write_targets"
    >
      <h2 id="setting-write_targets">Write targets</h2>
      <Meta view={view} />
      <p data-testid="write-targets-note">{FEATURE_STRINGS.writeTargetsNote}</p>
      {view === undefined || view.entries.length === 0 ? (
        <p>{FEATURE_STRINGS.noStored}</p>
      ) : (
        <ul>
          {view.entries.map((e) => {
            const target = (e.value["write_target"] ?? {}) as Record<string, unknown>;
            const credential = (target["credential"] ?? null) as CredentialReference | null;
            return (
              <li key={e.document_id}>
                <code>{e.document_id}</code>: {String(target["target_kind"] ?? "target")}
                {", "}
                {e.value["enabled"] === true ? "enabled" : "disabled"},{" "}
                {describeReference(credential)}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** One setting: its own read (GET /settings/{key}) so a failure shows on that card only. */
function SettingLoader({ settingKey }: { readonly settingKey: SettingKey }): ReactElement {
  const query = useAdminGet<SettingView>("admin-setting", { path: settingPaths.one(settingKey) });
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState<WriteResult | undefined>(undefined);
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={`${FEATURE_STRINGS.loading}: ${settingKey}`} rows={2} />
      </div>
    );
  }
  const view = query.data.data;
  if (settingKey === "write_targets") return <WriteTargetsCard view={view} />;
  return (
    <SettingCard
      // Remount on a new revision so the form re-reads what is stored.
      key={`${settingKey}:${view.etag ?? "none"}`}
      spec={SETTING_SPECS[settingKey]}
      view={view}
      result={saved}
      onSaved={(r) => {
        if (r !== undefined) setSaved(r);
        void queryClient.invalidateQueries({ queryKey: ["admin-setting"] });
      }}
    />
  );
}

function FeaturesBody(): ReactElement {
  return (
    <>
      {SETTING_KEYS.map((key) => (
        <SettingLoader key={key} settingKey={key} />
      ))}
    </>
  );
}

export function FeatureSettingsPage(): ReactElement {
  return (
    <PageTemplate title={FEATURE_STRINGS.title} description={FEATURE_STRINGS.description}>
      <AdminTabs />
      <FeaturesBody />
    </PageTemplate>
  );
}
