import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  Switch,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useMemo, useRef, useState, type ReactElement, type RefObject } from "react";
import {
  ForbiddenError,
  InvalidSchemaError,
  StaleVersionError,
  type ApiError,
} from "../../api/index.js";
import { Panel } from "../../design-system";
import { ChangeConfirmDialog } from "../governed-change";
import { useCreateEntity, useReloadEntity, useUpdateEntity } from "./explorerHooks";
import { EXPLORER_STRINGS } from "./explorerStrings";
import type { CatalogEntityView } from "./explorerTypes";
import {
  FIELD_DEFS,
  FORM_TYPES,
  buildBody,
  diffRows,
  initialValues,
  publishBlocked,
  validate,
  type FieldDef,
  type FormType,
  type FormValues,
} from "./entityFormModel";

const S = EXPLORER_STRINGS.form;

const useStyles = makeStyles({
  fields: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    maxWidth: "560px",
  },
  row: { display: "flex", columnGap: tokens.spacingHorizontalS },
});

function label(key: string): string {
  return S.fields[key] ?? key;
}

function FieldInput(props: {
  readonly def: FieldDef;
  readonly value: string;
  readonly problem: string | undefined;
  readonly disabled: boolean;
  readonly onChange: (value: string) => void;
}): ReactElement {
  const { def, value, problem, disabled, onChange } = props;
  const message =
    problem === undefined
      ? undefined
      : problem === "token"
        ? S.token
        : problem === "url"
          ? S.url
          : S.required;
  if (def.kind === "switch") {
    return (
      <Switch
        label={label(def.key)}
        checked={value === "true"}
        disabled={disabled}
        onChange={(_e, d) => onChange(d.checked ? "true" : "false")}
      />
    );
  }
  return (
    <Field
      label={label(def.key)}
      required={def.required}
      validationState={message === undefined ? "none" : "error"}
      validationMessage={message}
    >
      {def.kind === "select" ? (
        <Dropdown
          value={value}
          selectedOptions={[value]}
          disabled={disabled}
          onOptionSelect={(_e, d) => onChange(d.optionValue ?? value)}
        >
          {(def.options ?? []).map((o) => (
            <Option key={o} value={o}>
              {o}
            </Option>
          ))}
        </Dropdown>
      ) : def.kind === "textarea" ? (
        <Textarea
          value={value}
          maxLength={def.maxLength}
          disabled={disabled}
          onChange={(_e, d) => onChange(d.value)}
        />
      ) : (
        <Input
          value={value}
          maxLength={def.maxLength}
          disabled={disabled}
          onChange={(_e, d) => onChange(d.value)}
        />
      )}
    </Field>
  );
}

function errorText(error: ApiError | null): string | null {
  if (error === null) return null;
  if (error instanceof StaleVersionError) return S.stale;
  if (error instanceof ForbiddenError) return S.forbidden;
  if (error instanceof InvalidSchemaError) return S.invalid;
  return S.failed;
}

export interface EntityFormPanelProps {
  /** Domain the entity is created in or lives in. It goes in the URL path only. */
  readonly domain: string;
  /** Present on edit; absent on create. */
  readonly entity?: CatalogEntityView;
  readonly onCancel: () => void;
  /** Called after a successful write with the server's entity. */
  readonly onSaved: (entity: CatalogEntityView) => void;
  readonly triggerRef?: RefObject<HTMLElement | null>;
}

/**
 * Create / edit form for agent, tool, model_deployment and mcp_server. Review opens the shared
 * ChangeConfirmDialog (target, version, before/after diff, reason); only its submit sends.
 */
export function EntityFormPanel(props: EntityFormPanelProps): ReactElement {
  const { domain, entity, onCancel, onSaved, triggerRef } = props;
  const styles = useStyles();
  const create = useCreateEntity();
  const update = useUpdateEntity();
  const reload = useReloadEntity();
  const editing = entity !== undefined;
  const entityType = entity?.entity_type;
  const [type, setType] = useState<FormType>(
    entityType !== undefined && (FORM_TYPES as readonly string[]).includes(entityType)
      ? (entityType as FormType)
      : "agent",
  );
  const [values, setValues] = useState<FormValues>(() => initialValues(type, entity));
  const [attempted, setAttempted] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const nowRef = useRef(new Date().toISOString().replace(/\.\d+Z$/, "Z"));
  const mutation = editing ? update : create;
  const problems = validate(type, values);
  const blocked = publishBlocked(values);

  const body = useMemo(
    () => buildBody(type, values, { ...(entity !== undefined && { entity }), now: nowRef.current }),
    [type, values, entity],
  );
  const diff = useMemo(() => diffRows(body, entity, S.none), [body, entity]);
  const noChange = editing && diff.length === 0;

  const set = (key: string, value: string): void => setValues((v) => ({ ...v, [key]: value }));

  const review = (): void => {
    setAttempted(true);
    if (Object.keys(problems).length === 0 && !noChange) setConfirming(true);
  };
  const closeConfirm = (): void => {
    setConfirming(false);
    create.reset();
    update.reset();
  };
  const send = (): void => {
    const onSuccess = (saved: CatalogEntityView): void => {
      setConfirming(false);
      void reload();
      onSaved(saved);
    };
    const onError = (): void => {
      // 409 or any refusal: re-read so the dialog shows the version the server now holds.
      void reload();
    };
    if (entity !== undefined) {
      update.mutate(
        { domain, entityId: entity.id, etag: entity.etag, body },
        { onSuccess, onError },
      );
    } else {
      create.mutate({ domain, body }, { onSuccess, onError });
    }
  };

  return (
    <Panel title={editing ? S.editHeading : S.createTitle} testId="entity-form">
      <div className={styles.fields}>
        {editing ? null : (
          <Field label={S.typeLabel}>
            <Dropdown
              value={type}
              selectedOptions={[type]}
              onOptionSelect={(_e, d) => {
                const next = (d.optionValue ?? type) as FormType;
                setType(next);
                setValues(initialValues(next));
                setAttempted(false);
              }}
            >
              {FORM_TYPES.map((t) => (
                <Option key={t} value={t}>
                  {t}
                </Option>
              ))}
            </Dropdown>
          </Field>
        )}
        {FIELD_DEFS[type].map((def) => (
          <FieldInput
            key={`${type}:${def.key}`}
            def={def}
            value={values[def.key] ?? def.initial}
            problem={attempted ? problems[def.key] : undefined}
            disabled={def.key === "publishable" && blocked}
            onChange={(v) => set(def.key, v)}
          />
        ))}
        {type === "mcp_server" && blocked ? (
          <p data-testid="publish-blocked">{S.publishableBlocked}</p>
        ) : null}
        {noChange && attempted ? <p role="status">{S.noChanges}</p> : null}
        <div className={styles.row}>
          <Button appearance="primary" data-testid="entity-form-review" onClick={review}>
            {S.review}
          </Button>
          <Button onClick={onCancel}>{S.cancel}</Button>
        </div>
      </div>
      <ChangeConfirmDialog
        open={confirming}
        title={editing ? S.editConfirmTitle : S.createConfirmTitle}
        target={entity?.id ?? S.newTarget(type, domain)}
        version={entity?.etag ?? S.newVersion}
        diff={diff}
        submitting={mutation.isPending}
        reasonNote={S.noteCreate}
        error={errorText(mutation.error)}
        triggerRef={triggerRef}
        onSubmit={send}
        onClose={closeConfirm}
      />
    </Panel>
  );
}
