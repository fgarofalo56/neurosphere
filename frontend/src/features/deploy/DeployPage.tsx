import { Button, Text, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { PageTemplate } from "../../design-system";
import { ChoicesStep, initialDraft, type ChoicesDraft } from "./ChoicesStep";
import { PlanStep } from "./PlanStep";
import { ScanStep } from "./ScanStep";
import { STRINGS } from "./strings";
import type { ScanResponse } from "./types";

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
 * Scan -> choices -> plan. The scan result and every draft live in component state only: nothing
 * is written to localStorage, sessionStorage or the URL. All three panels stay mounted so going
 * back keeps what was typed. There is no apply control; the plan is advisory.
 */
export function DeployPage(): ReactElement {
  const styles = useStyles();
  const [step, setStep] = useState(0);
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [draft, setDraft] = useState<ChoicesDraft>(initialDraft);
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
          <PlanStep scan={scan} draft={draft} />
        </div>
        <div className={styles.nav}>
          <Button disabled={step === 0} onClick={() => setStep(step - 1)} data-testid="step-back">
            {STRINGS.back}
          </Button>
          {step < 2 ? (
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
