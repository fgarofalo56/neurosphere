import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
  Select,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useRef, useState, type ReactElement } from "react";
import { isApiError, useApiClient } from "../../api/index.js";
import { ErrorState, Timestamp } from "../../design-system";
import { createInteractionExport, downloadExportBundle, toUtc } from "./hooks";
import { describeActionError, type ProblemView } from "./problems";
import { EMPTY_PURPOSE, PurposeFields, toPurpose, type PurposeDraft } from "./PurposeFields";
import { STRINGS } from "./strings";
import {
  DETECTED_CATEGORIES,
  type DetectedCategory,
  type InteractionExportManifest,
  type InteractionFilters,
} from "./types";

const useStyles = makeStyles({
  form: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  muted: { margin: 0, color: tokens.colorNeutralForeground2 },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  facts: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
    "& dd": { margin: 0, overflowWrap: "anywhere" },
  },
});

interface ExportDraft {
  readonly from: string;
  readonly to: string;
  readonly agentId: string;
  readonly category: string;
}

function draftFrom(filters: InteractionFilters): ExportDraft {
  return {
    from: filters.from,
    to: filters.to,
    agentId: filters.agentId,
    category: filters.detectedCategory,
  };
}

function saveBundle(bundle: unknown, exportId: string): void {
  const blob = new Blob([JSON.stringify(bundle)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `interaction-export-${exportId}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function Manifest({
  manifest,
  domainId,
}: {
  readonly manifest: InteractionExportManifest;
  readonly domainId: string;
}): ReactElement {
  const styles = useStyles();
  const client = useApiClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [problem, setProblem] = useState<ProblemView | null>(null);
  const S = STRINGS.exportFlow;
  useEffect(() => {
    heading.current?.focus();
  }, []);

  const download = async (): Promise<void> => {
    setBusy(true);
    setProblem(null);
    setDone(false);
    try {
      saveBundle(
        await downloadExportBundle(client, domainId, manifest.export_id),
        manifest.export_id,
      );
      setDone(true);
    } catch (error) {
      if (!isApiError(error)) throw error;
      setProblem(describeActionError(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="export-manifest-heading" data-testid="export-manifest">
      <h3 id="export-manifest-heading" ref={heading} tabIndex={-1} className={styles.heading}>
        {S.manifestHeading}
      </h3>
      <dl className={styles.facts}>
        <dt>{S.exportId}</dt>
        <dd data-testid="export-id">{manifest.export_id}</dd>
        <dt>{S.count}</dt>
        <dd data-testid="export-count">{manifest.interaction_count}</dd>
        <dt>{S.ids}</dt>
        <dd data-testid="export-ids">{manifest.interaction_ids.length}</dd>
        <dt>{S.excluded}</dt>
        <dd data-testid="export-excluded">{manifest.excluded_count}</dd>
        <dt>{S.held}</dt>
        <dd data-testid="export-held">{manifest.includes_held_content ? S.yes : S.no}</dd>
        <dt>{S.expires}</dt>
        <dd data-testid="export-expires">
          <Timestamp value={manifest.expires_at} />
        </dd>
        <dt>{S.auditId}</dt>
        <dd data-testid="export-audit-id">{manifest.audit_id}</dd>
      </dl>
      <div>
        <Button onClick={() => void download()} disabled={busy} data-testid="export-download">
          {busy ? S.downloading : S.download}
        </Button>
      </div>
      {done ? (
        <p role="status" className={styles.muted} data-testid="export-downloaded">
          {S.downloaded}
        </p>
      ) : null}
      {problem !== null ? (
        <ErrorState
          testId={`export-${problem.kind}`}
          title={problem.title}
          message={problem.message}
        />
      ) : null}
    </section>
  );
}

/**
 * Create an audited export from the current filters. The manifest is metadata only; the bundle
 * is fetched on demand, written straight to a file and never cached. Closing drops it all.
 */
export function ExportDialog({
  domainId,
  filters,
}: {
  readonly domainId: string;
  readonly filters: InteractionFilters;
}): ReactElement {
  const styles = useStyles();
  const client = useApiClient();
  const S = STRINGS.exportFlow;
  const [open, setOpen] = useState(false);
  const [purpose, setPurpose] = useState<PurposeDraft>(EMPTY_PURPOSE);
  const [draft, setDraft] = useState<ExportDraft>(() => draftFrom(filters));
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [manifest, setManifest] = useState<InteractionExportManifest | null>(null);
  const [problem, setProblem] = useState<ProblemView | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    const ref = generation;
    return () => {
      ref.current += 1;
    };
  }, []);

  const reset = (): void => {
    generation.current += 1;
    setPurpose(EMPTY_PURPOSE);
    setAttempted(false);
    setBusy(false);
    setManifest(null);
    setProblem(null);
  };

  const from = toUtc(draft.from);
  const to = toUtc(draft.to);
  const rangeMissing = attempted && (from === null || to === null);

  const submit = async (): Promise<void> => {
    setAttempted(true);
    const wire = toPurpose(purpose);
    if (wire === null || from === null || to === null) return;
    const mine = ++generation.current;
    setBusy(true);
    setProblem(null);
    try {
      const result = await createInteractionExport(client, domainId, {
        purpose: wire,
        filters: {
          from,
          to,
          agent_ids: draft.agentId.trim() === "" ? [] : [draft.agentId.trim()],
          detected_categories: draft.category === "" ? [] : [draft.category as DetectedCategory],
        },
      });
      if (generation.current === mine) setManifest(result);
    } catch (error) {
      if (generation.current !== mine) return;
      if (!isApiError(error)) throw error;
      setProblem(describeActionError(error));
    } finally {
      if (generation.current === mine) setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(_e, data) => {
        if (data.open) setDraft(draftFrom(filters));
        else reset();
        setOpen(data.open);
      }}
    >
      <DialogTrigger disableButtonEnhancement>
        <Button data-testid="export-open">{S.open}</Button>
      </DialogTrigger>
      <DialogSurface aria-describedby="export-intro">
        <DialogBody>
          <DialogTitle>{S.title}</DialogTitle>
          <DialogContent>
            <div className={styles.form}>
              <p id="export-intro" className={styles.muted}>
                {S.intro}
              </p>
              {manifest === null ? (
                <form
                  noValidate
                  aria-label={S.title}
                  className={styles.form}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void submit();
                  }}
                >
                  <PurposeFields
                    value={purpose}
                    onChange={setPurpose}
                    showRequired={attempted}
                    idPrefix="export"
                  />
                  <Field
                    label={S.from}
                    hint={STRINGS.filters.timeHint}
                    required
                    validationState={rangeMissing && from === null ? "error" : "none"}
                    validationMessage={rangeMissing && from === null ? S.rangeRequired : undefined}
                  >
                    <Input
                      data-testid="export-from"
                      value={draft.from}
                      onChange={(_e, d) => setDraft({ ...draft, from: d.value })}
                    />
                  </Field>
                  <Field
                    label={S.to}
                    hint={STRINGS.filters.timeHint}
                    required
                    validationState={rangeMissing && to === null ? "error" : "none"}
                    validationMessage={rangeMissing && to === null ? S.rangeRequired : undefined}
                  >
                    <Input
                      data-testid="export-to"
                      value={draft.to}
                      onChange={(_e, d) => setDraft({ ...draft, to: d.value })}
                    />
                  </Field>
                  <Field label={S.agent}>
                    <Input
                      data-testid="export-agent"
                      value={draft.agentId}
                      maxLength={512}
                      onChange={(_e, d) => setDraft({ ...draft, agentId: d.value })}
                    />
                  </Field>
                  <Field label={S.category}>
                    <Select
                      data-testid="export-category"
                      value={draft.category}
                      onChange={(_e, d) => setDraft({ ...draft, category: d.value })}
                    >
                      <option value="">{STRINGS.filters.any}</option>
                      {DETECTED_CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <div>
                    <Button
                      type="submit"
                      appearance="primary"
                      disabled={busy}
                      data-testid="export-submit"
                    >
                      {busy ? S.creating : S.submit}
                    </Button>
                  </div>
                </form>
              ) : (
                <Manifest manifest={manifest} domainId={domainId} />
              )}
              {problem !== null ? (
                <ErrorState
                  testId={`export-${problem.kind}`}
                  title={problem.title}
                  message={problem.message}
                  tone={
                    problem.kind === "forbidden" || problem.kind === "limit" ? "warning" : "danger"
                  }
                />
              ) : null}
            </div>
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary">{S.close}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
