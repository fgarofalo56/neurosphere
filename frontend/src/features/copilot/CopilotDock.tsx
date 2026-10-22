import { Button, Field, Textarea, makeStyles, tokens } from "@fluentui/react-components";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { useLocation } from "react-router";
import { AssistantTurnView, ContextChip } from "./components";
import { buildMessageContext } from "./requestContext";
import { useCurrentCopilotSelection } from "./selection";
import { STRINGS } from "./strings";
import { useCopilotTransport } from "./transport";
import { useCopilotChat } from "./useChat";

// No animation or transition is used anywhere in the dock, so reduced-motion preferences are
// respected by construction. Keep it that way: any future motion must sit behind
// `@media (prefers-reduced-motion: no-preference)`.
const useStyles = makeStyles({
  toggle: {
    position: "fixed",
    right: tokens.spacingHorizontalL,
    bottom: tokens.spacingVerticalL,
    zIndex: 1000,
  },
  panel: {
    position: "fixed",
    right: tokens.spacingHorizontalL,
    bottom: "64px",
    zIndex: 1000,
    width: "min(420px, calc(100vw - 32px))",
    maxHeight: "min(640px, calc(100vh - 96px))",
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusLarge,
    boxShadow: tokens.shadow16,
  },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between" },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400 },
  log: {
    flexGrow: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    minHeight: "120px",
  },
  form: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXS },
});

/**
 * The chat panel mounted once in the authenticated app shell. Chat state lives here (not in the
 * panel), so closing the panel or navigating keeps the conversation; unmounting aborts any
 * in-flight stream.
 */
export function CopilotDock(): ReactElement {
  const styles = useStyles();
  const ids = { title: useId(), panel: useId() };
  const location = useLocation();
  const selection = useCurrentCopilotSelection();
  const transport = useCopilotTransport();
  const chat = useCopilotChat(transport);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const toggleRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  // Focus management: into the input when opened, back to the toggle when closed.
  useEffect(() => {
    if (open) inputRef.current?.focus();
    else if (wasOpen.current) toggleRef.current?.focus();
    wasOpen.current = open;
  }, [open]);

  // Keep the newest streamed text in view.
  useEffect(() => {
    const log = logRef.current;
    if (log !== null) log.scrollTop = log.scrollHeight;
  }, [chat.turns]);

  const submit = useCallback(() => {
    const text = draft.trim();
    if (text === "") return;
    setDraft("");
    void chat.send(
      text,
      buildMessageContext({ pathname: location.pathname, search: location.search, selection }),
    );
  }, [chat, draft, location.pathname, location.search, selection]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
    }
  };

  return (
    <>
      <Button
        ref={toggleRef}
        className={styles.toggle}
        appearance="primary"
        aria-expanded={open}
        aria-controls={open ? ids.panel : undefined}
        onClick={() => setOpen((o) => !o)}
        data-testid="copilot-toggle"
      >
        {open ? STRINGS.close : STRINGS.open}
      </Button>
      {open ? (
        <section
          id={ids.panel}
          className={styles.panel}
          aria-labelledby={ids.title}
          onKeyDown={onKeyDown}
          data-testid="copilot-panel"
        >
          <div className={styles.header}>
            <h2 id={ids.title} className={styles.heading}>
              {STRINGS.title}
            </h2>
            <Button appearance="subtle" onClick={() => setOpen(false)}>
              {STRINGS.close}
            </Button>
          </div>
          <ContextChip echo={chat.echo} />
          <div
            ref={logRef}
            className={styles.log}
            role="log"
            aria-label={STRINGS.logLabel}
            aria-live="polite"
            aria-relevant="additions text"
            aria-busy={chat.busy}
            tabIndex={0}
          >
            {chat.turns.length === 0 ? <p>{STRINGS.empty}</p> : null}
            {chat.turns.map((turn) => (
              <AssistantTurnView
                key={turn.key}
                turn={turn}
                echo={chat.echo}
                onNavigate={() => setOpen(false)}
              />
            ))}
          </div>
          <form
            className={styles.form}
            aria-label={STRINGS.inputLabel}
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <Field label={STRINGS.inputLabel}>
              <Textarea
                ref={inputRef}
                value={draft}
                placeholder={STRINGS.inputPlaceholder}
                resize="vertical"
                maxLength={8000}
                onChange={(_e, data) => setDraft(data.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
            </Field>
            <div>
              <Button type="submit" appearance="primary" disabled={draft.trim() === ""}>
                {STRINGS.send}
              </Button>
            </div>
          </form>
        </section>
      ) : null}
    </>
  );
}
