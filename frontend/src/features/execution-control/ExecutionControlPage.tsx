import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { useRef, useState, type ReactElement, type ReactNode } from "react";
import { ApiError, ForbiddenError } from "../../api/index.js";
import { ErrorState, LoadingState, PageTemplate, StatusPill, Timestamp } from "../../design-system";
import { ChangeConfirmDialog, type ChangeConfirmSubmit } from "../governed-change";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import {
  REASON_PATTERN,
  useApplyExecutionView,
  useExecutionControl,
  useSetExecutionControl,
  type EmergencyDisableView,
} from "./data";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  list: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  term: { fontWeight: tokens.fontWeightSemibold },
  value: { margin: 0 },
});

function describeError(error: ApiError): ReactNode {
  const ref = STRINGS.reference(error.correlationId);
  if (error instanceof ForbiddenError) return `${STRINGS.accessDenied}${ref}`;
  // The server's own words (for example its 422 detail) are shown as returned.
  const detail = error.problem?.detail ?? error.message;
  return `${STRINGS.changeFailed} ${detail}${ref}`;
}

function State({ view }: { readonly view: EmergencyDisableView }): ReactElement {
  const styles = useStyles();
  return (
    <dl className={styles.list} data-testid="execution-state">
      <dt className={styles.term}>{STRINGS.stateLabel}</dt>
      <dd className={styles.value}>
        <StatusPill
          tone={view.disabled ? "danger" : "success"}
          label={view.disabled ? STRINGS.disabledText : STRINGS.enabledText}
          testId="execution-pill"
        />
      </dd>
      <dt className={styles.term}>{STRINGS.reason}</dt>
      <dd className={styles.value} data-testid="execution-reason">
        {view.reason ?? STRINGS.unknown}
      </dd>
      <dt className={styles.term}>{STRINGS.changedBy}</dt>
      <dd className={styles.value} data-testid="execution-changed-by">
        {view.changed_by ?? STRINGS.unknown}
      </dd>
      <dt className={styles.term}>{STRINGS.changedAt}</dt>
      <dd className={styles.value}>
        {view.changed_at === null ? STRINGS.unknown : <Timestamp value={view.changed_at} />}
      </dd>
    </dl>
  );
}

function Controls({ view }: { readonly view: EmergencyDisableView }): ReactElement {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const [localError, setLocalError] = useState<ReactNode>(undefined);
  const trigger = useRef<HTMLElement | null>(null);
  const setControl = useSetExecutionControl();
  const apply = useApplyExecutionView();
  const target = !view.disabled; // the state the change moves to: true = disable

  const close = (): void => {
    setOpen(false);
    setLocalError(undefined);
    setControl.reset();
  };

  const submit = (value: ChangeConfirmSubmit): void => {
    if (!REASON_PATTERN.test(value.reason)) {
      setLocalError(STRINGS.invalidReason);
      return;
    }
    setLocalError(undefined);
    setControl.mutate(
      { disabled: target, reason: value.reason },
      {
        onSuccess: (next) => {
          apply(next);
          setOpen(false);
        },
      },
    );
  };

  const error: ReactNode =
    localError ?? (setControl.isError ? describeError(setControl.error) : undefined);

  return (
    <div className={styles.stack}>
      <div>
        <Button
          ref={(el) => {
            trigger.current = el;
          }}
          appearance="primary"
          onClick={() => setOpen(true)}
          data-testid="execution-toggle"
        >
          {target ? STRINGS.disable : STRINGS.enable}
        </Button>
      </div>
      <ChangeConfirmDialog
        open={open}
        title={target ? STRINGS.disableTitle : STRINGS.enableTitle}
        target={STRINGS.target}
        version={STRINGS.versionNone}
        diff={[
          {
            field: STRINGS.fieldState,
            before: view.disabled ? STRINGS.stateDisabled : STRINGS.stateEnabled,
            after: target ? STRINGS.stateDisabled : STRINGS.stateEnabled,
          },
        ]}
        submitting={setControl.isPending}
        error={error === undefined ? undefined : <span>{error}</span>}
        triggerRef={trigger}
        onSubmit={submit}
        onClose={close}
      />
      <span data-testid="execution-hint">{STRINGS.reasonCodeHint}</span>
    </div>
  );
}

/**
 * Kill switch for the action executor. Reads and writes the same endpoint the actions page
 * reads; the API decides who may change it (config.manage) and the view always comes from the
 * server's response.
 */
export function ExecutionControlPage(): ReactElement {
  const q = useExecutionControl({});
  let body: ReactNode;
  if (q.isPending) {
    body = <LoadingState label={STRINGS.loading} rows={3} />;
  } else if (q.isError) {
    body =
      q.error instanceof ForbiddenError ? (
        <ForbiddenState
          workspace={STRINGS.forbiddenWorkspace}
          correlationId={q.error.correlationId}
        />
      ) : (
        <ErrorState
          title={STRINGS.failedTitle}
          message={STRINGS.reference(q.error.correlationId)}
          testId="execution-error"
          onRetry={() => void q.refetch()}
        />
      );
  } else {
    body = (
      <>
        <State view={q.data} />
        <Controls view={q.data} />
      </>
    );
  }
  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      data-testid="execution-control-page"
      busy={q.isPending}
    >
      {body}
    </PageTemplate>
  );
}
