import { Button, Field, Input, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSelectedDomain } from "../../app/domain";
import { EmptyState, PageTemplate, Panel } from "../../design-system";
import { ActionDetail } from "./ActionDetail";
import { ActionError, EmergencyBanner } from "./components";
import { useDraftIntent } from "./hooks";
import { buildDraftIntentRequest } from "./request";
import { STRINGS } from "./strings";
import type { ActionView } from "./types";

const useStyles = makeStyles({
  form: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    maxWidth: "36rem",
  },
});

/**
 * "Propose model swap": drafts a button-channel intent for a model_deployment target, then hands
 * the server's answer to the same workflow the detail page uses (validate -> confirmation ->
 * confirm). The idempotency key is fixed for the page's lifetime so a retried submit replays the
 * original draft instead of creating a second one. The domain is the one chosen in the header.
 */
export function ProposeSwapPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  const styles = useStyles();
  const [idempotencyKey] = useState<string>(() => `button-${crypto.randomUUID()}`);
  const [view, setView] = useState<ActionView | null>(null);
  const [draftDomain, setDraftDomain] = useState("");
  const draft = useDraftIntent();
  const P = STRINGS.propose;
  return (
    <PageTemplate title={STRINGS.proposeTitle} description={P.help}>
      <EmergencyBanner />
      {view !== null ? (
        <ActionDetail domainId={draftDomain} view={view} onView={setView} />
      ) : domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <Panel>
          <form
            aria-label={STRINGS.proposeTitle}
            className={styles.form}
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              const text = (key: string): string => {
                const v = data.get(key);
                return typeof v === "string" ? v.trim() : "";
              };
              draft.mutate(
                {
                  domainId,
                  request: buildDraftIntentRequest({
                    canonicalId: text("target"),
                    targetVersion: text("target_version"),
                    newModelName: text("model_name"),
                    newModelVersion: text("model_version"),
                    idempotencyKey,
                  }),
                },
                {
                  onSuccess: (next) => {
                    // The workflow keeps acting on the domain the draft was created in.
                    setDraftDomain(domainId);
                    setView(next);
                  },
                },
              );
            }}
          >
            <Field label={P.target}>
              <Input name="target" required />
            </Field>
            <Field label={P.version}>
              <Input name="target_version" required />
            </Field>
            <Field label={P.modelName}>
              <Input name="model_name" required />
            </Field>
            <Field label={P.modelVersion}>
              <Input name="model_version" />
            </Field>
            <div>
              <Button appearance="primary" type="submit" disabled={draft.isPending}>
                {draft.isPending ? STRINGS.steps.working : P.submit}
              </Button>
            </div>
            {draft.isError ? <ActionError error={draft.error} /> : null}
          </form>
        </Panel>
      )}
    </PageTemplate>
  );
}
