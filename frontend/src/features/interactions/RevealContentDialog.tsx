import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useRef, useState, type ReactElement } from "react";
import { isApiError, useApiClient } from "../../api/index.js";
import { ErrorState } from "../../design-system";
import { readInteractionContent } from "./hooks";
import { describeActionError, type ProblemView } from "./problems";
import { EMPTY_PURPOSE, PurposeFields, toPurpose, type PurposeDraft } from "./PurposeFields";
import { STRINGS } from "./strings";
import type { RedactedContent } from "./types";

const useStyles = makeStyles({
  form: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  text: {
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    margin: 0,
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground2,
    fontFamily: tokens.fontFamilyMonospace,
  },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  part: { margin: 0, fontSize: tokens.fontSizeBase300, fontWeight: tokens.fontWeightSemibold },
  muted: { margin: 0, color: tokens.colorNeutralForeground2 },
});

export interface RevealContentDialogProps {
  readonly domainId: string;
  readonly interactionId: string;
  /** False when nothing was stored (redaction failed): the button is disabled. */
  readonly hasContent: boolean;
}

function RevealedContent({ content }: { readonly content: RedactedContent }): ReactElement {
  const styles = useStyles();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section aria-labelledby="reveal-content-heading" data-testid="revealed-content">
      <h3 id="reveal-content-heading" ref={heading} tabIndex={-1} className={styles.heading}>
        {STRINGS.reveal.contentHeading}
      </h3>
      <p className={styles.muted}>{STRINGS.reveal.notCached}</p>
      {content.parts.map((part) => (
        <div key={part.part} data-testid="revealed-part">
          <h4 className={styles.part}>{part.part}</h4>
          <pre className={styles.text}>{part.text}</pre>
          {part.truncated === true ? (
            <p className={styles.muted}>{STRINGS.reveal.truncated}</p>
          ) : null}
          {(part.findings ?? []).length > 0 ? (
            <ul aria-label={`${STRINGS.reveal.partFindings}: ${part.part}`}>
              {(part.findings ?? []).map((f, i) => (
                <li key={`${f.category}-${f.detector_id}-${i}`}>
                  {f.category}: {f.count} ({STRINGS.detail.findingAction[f.action]})
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </section>
  );
}

/**
 * The only way the page shows captured content. A purpose code is required (the server refuses
 * anything else with 422); the result lives in this component's state only and is dropped when
 * the dialog closes, and a read that answers after the close is discarded.
 */
export function RevealContentDialog({
  domainId,
  interactionId,
  hasContent,
}: RevealContentDialogProps): ReactElement {
  const styles = useStyles();
  const client = useApiClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<PurposeDraft>(EMPTY_PURPOSE);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [content, setContent] = useState<RedactedContent | null>(null);
  const [problem, setProblem] = useState<ProblemView | null>(null);
  const generation = useRef(0);

  const reset = (): void => {
    generation.current += 1;
    setDraft(EMPTY_PURPOSE);
    setAttempted(false);
    setBusy(false);
    setContent(null);
    setProblem(null);
  };

  // Unmounted (the parent keys this dialog by interaction id): a late answer is discarded.
  useEffect(() => {
    const ref = generation;
    return () => {
      ref.current += 1;
    };
  }, []);

  const submit = async (): Promise<void> => {
    setAttempted(true);
    const purpose = toPurpose(draft);
    if (purpose === null) return;
    const mine = ++generation.current;
    setBusy(true);
    setProblem(null);
    try {
      const result = await readInteractionContent(client, domainId, interactionId, purpose);
      if (generation.current === mine) setContent(result);
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
        if (!data.open) reset();
        setOpen(data.open);
      }}
    >
      <DialogTrigger disableButtonEnhancement>
        <Button appearance="primary" disabled={!hasContent} data-testid="reveal-open">
          {STRINGS.reveal.open}
        </Button>
      </DialogTrigger>
      <DialogSurface aria-describedby="reveal-intro">
        <DialogBody>
          <DialogTitle>{STRINGS.reveal.title}</DialogTitle>
          <DialogContent>
            <div className={styles.form}>
              <p id="reveal-intro" className={styles.muted}>
                {STRINGS.reveal.intro}
              </p>
              {content === null ? (
                <form
                  noValidate
                  aria-label={STRINGS.reveal.title}
                  className={styles.form}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void submit();
                  }}
                >
                  <PurposeFields
                    value={draft}
                    onChange={setDraft}
                    showRequired={attempted}
                    idPrefix="reveal"
                  />
                  <div>
                    <Button
                      type="submit"
                      appearance="primary"
                      disabled={busy}
                      data-testid="reveal-submit"
                    >
                      {busy ? STRINGS.reveal.revealing : STRINGS.reveal.submit}
                    </Button>
                  </div>
                </form>
              ) : (
                <RevealedContent content={content} />
              )}
              {problem !== null ? (
                <ErrorState
                  testId={`reveal-${problem.kind}`}
                  title={problem.title}
                  message={problem.message}
                  tone={problem.kind === "forbidden" ? "warning" : "danger"}
                />
              ) : null}
            </div>
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary">{STRINGS.reveal.close}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
