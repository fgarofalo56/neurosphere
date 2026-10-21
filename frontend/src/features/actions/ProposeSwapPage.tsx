import { useId, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ActionDetail } from "./ActionDetail";
import { ActionError, EmergencyBanner } from "./components";
import { useDraftIntent } from "./hooks";
import { buildDraftIntentRequest } from "./request";
import { STRINGS } from "./strings";
import type { ActionView } from "./types";

/**
 * "Propose model swap": drafts a button-channel intent for a model_deployment target, then hands
 * the server's answer to the same workflow the detail page uses (validate -> confirmation ->
 * confirm). The idempotency key is fixed for the page's lifetime so a retried submit replays the
 * original draft instead of creating a second one.
 */
export function ProposeSwapPage(): ReactElement {
  const [params] = useSearchParams();
  const initialDomain = params.get("domain_id") ?? "";
  const ids = { domain: useId(), target: useId(), version: useId(), name: useId(), mver: useId() };
  const [idempotencyKey] = useState<string>(() => `button-${crypto.randomUUID()}`);
  const [view, setView] = useState<ActionView | null>(null);
  const [domainId, setDomainId] = useState(initialDomain);
  const draft = useDraftIntent();
  const P = STRINGS.propose;
  return (
    <section aria-label={STRINGS.proposeTitle}>
      <h1>{STRINGS.proposeTitle}</h1>
      <EmergencyBanner />
      <p>{P.help}</p>
      {view === null ? (
        <form
          aria-label={STRINGS.proposeTitle}
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const text = (key: string): string => {
              const v = data.get(key);
              return typeof v === "string" ? v.trim() : "";
            };
            const domain = text("domain");
            setDomainId(domain);
            draft.mutate(
              {
                domainId: domain,
                request: buildDraftIntentRequest({
                  canonicalId: text("target"),
                  targetVersion: text("target_version"),
                  newModelName: text("model_name"),
                  newModelVersion: text("model_version"),
                  idempotencyKey,
                }),
              },
              { onSuccess: setView },
            );
          }}
        >
          <p>
            <label htmlFor={ids.domain}>{P.domain}</label>{" "}
            <input id={ids.domain} name="domain" required defaultValue={initialDomain} />
          </p>
          <p>
            <label htmlFor={ids.target}>{P.target}</label>{" "}
            <input id={ids.target} name="target" required />
          </p>
          <p>
            <label htmlFor={ids.version}>{P.version}</label>{" "}
            <input id={ids.version} name="target_version" required />
          </p>
          <p>
            <label htmlFor={ids.name}>{P.modelName}</label>{" "}
            <input id={ids.name} name="model_name" required />
          </p>
          <p>
            <label htmlFor={ids.mver}>{P.modelVersion}</label>{" "}
            <input id={ids.mver} name="model_version" />
          </p>
          <button type="submit" disabled={draft.isPending}>
            {draft.isPending ? STRINGS.steps.working : P.submit}
          </button>
          {draft.isError ? <ActionError error={draft.error} /> : null}
        </form>
      ) : (
        <ActionDetail domainId={domainId} view={view} onView={setView} />
      )}
    </section>
  );
}
