import { Button, Text, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSelectedDomain } from "../../app/domain";
import { PageTemplate } from "../../design-system";
import { ApplyStep } from "./ApplyStep";
import { ChoicesStep, initialDraft, type ChoicesDraft } from "./ChoicesStep";
import { PlanStep } from "./PlanStep";
import { ScanStep } from "./ScanStep";
import { STRINGS } from "./strings";
import type { PlanResponse, ScanResponse } from "./types";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalL },
  steps: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalL,
    listStyleType: "none",
    margin: 0,
    padding: 0,
  },
  current: { fontWeight: tokens.fontWeightSemibold },
  nav: { display: "flex", columnGap: tokens.spacingHorizontalS },
});

/**
 * Scan -> choices -> plan -> approve/apply. The scan result, plan and every draft live in
 * component state only: nothing is written to localStorage, sessionStorage or the URL. All panels
 * stay mounted so going back keeps what was typed. The plan is advisory; step 4 only talks to the
 * apply API, which authorizes and fails closed.
 */
export function DeployPage(): ReactElement {
  const styles = useStyles();
  const [step, setStep] = useState(0);
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [draft, setDraft] = useState<ChoicesDraft>(initialDraft);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const { domainId } = useSelectedDomain();
  const name = STRINGS.steps[step] ?? "";

  return (
    <PageTemplate title={STRINGS.pageTitle} description={STRINGS.pageDescription}>
      <div className={styles.stack}>
        <ol className={styles.steps} aria-label={STRINGS.stepsLabel}>
          {STRINGS.steps.map((s, i) => (
            <li
              key={s}
              className={i === step ? styles.current : undefined}
              aria-current={i === step ? "step" : undefined}
              data-testid={`step-${i + 1}`}
            >
              {i + 1}. {s}
            </li>
          ))}
        </ol>
        <Text weight="semibold" data-testid="step-title">
          {STRINGS.stepOf(step + 1, name)}
        </Text>
        <div hidden={step !== 0}>
          <ScanStep
            scan={scan}
            onScanned={(s) => {
              setScan(s);
            }}
          />
        </div>
        <div hidden={step !== 1}>
          <ChoicesStep scan={scan} draft={draft} onChange={setDraft} />
        </div>
        <div hidden={step !== 2}>
          <PlanStep scan={scan} draft={draft} onPlanned={setPlan} />
        </div>
        <div hidden={step !== 3}>
          <ApplyStep plan={plan} domainId={domainId} />
        </div>
        <div className={styles.nav}>
          <Button disabled={step === 0} onClick={() => setStep(step - 1)} data-testid="step-back">
            {STRINGS.back}
          </Button>
          {step < 3 ? (
            <Button
              appearance="primary"
              disabled={step === 0 && scan === null}
              onClick={() => setStep(step + 1)}
              data-testid="step-next"
            >
              {STRINGS.next}
            </Button>
          ) : null}
        </div>
        {step === 0 && scan === null ? <Text>{STRINGS.scanRequired}</Text> : null}
      </div>
    </PageTemplate>
  );
}
