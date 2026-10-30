import {
  Button,
  Checkbox,
  Field,
  Input,
  Text,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  StatusPill,
  Timestamp,
  type DataTableColumn,
} from "../../design-system";
import { ForbiddenState } from "../workspaces";
import { useScan } from "./data";
import { STRINGS } from "./strings";
import type { DiscoveredResource, ScanResponse } from "./types";
import { checkAttestation, checkSubscriptions, splitLines } from "./validate";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  note: {
    padding: tokens.spacingVerticalS,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

const SUB_COLUMNS: readonly DataTableColumn<ScanResponse["subscriptions"][number]>[] = [
  { key: "id", header: "Subscription", render: (s) => s.subscription_id },
  {
    key: "status",
    header: "Visibility",
    render: (s) => (
      <StatusPill
        label={s.status === "visible" ? STRINGS.visible : STRINGS.notVisible}
        tone={s.status === "visible" ? "success" : "warning"}
      />
    ),
  },
  { key: "count", header: "Resources", render: (s) => s.resources.length },
  { key: "note", header: "Note", render: (s) => s.note ?? "" },
];

const RES_COLUMNS: readonly DataTableColumn<DiscoveredResource>[] = [
  { key: "category", header: "Category", render: (r) => r.category },
  { key: "name", header: "Name", render: (r) => r.name },
  { key: "sku", header: "SKU", render: (r) => r.sku ?? "" },
  { key: "location", header: "Location", render: (r) => r.location ?? "" },
  { key: "sub", header: "Subscription", render: (r) => r.subscription_id },
  { key: "id", header: "Resource id", render: (r) => r.id },
];

export function ScanResult({ scan }: { readonly scan: ScanResponse }): ReactElement {
  const styles = useStyles();
  const resources = scan.subscriptions.flatMap((s) => s.resources);
  return (
    <section
      className={styles.stack}
      aria-label={STRINGS.scanResultTitle}
      data-testid="scan-result"
    >
      <div className={styles.note} data-testid="visibility-note">
        <Text weight="semibold">{STRINGS.visibilityNoteLabel}: </Text>
        <Text>{scan.visibility_note}</Text>
      </div>
      <Text className={styles.muted}>
        {STRINGS.scannedAt} <Timestamp value={scan.scanned_at} />
      </Text>
      <DataTable
        label={STRINGS.subscriptionsTable}
        columns={SUB_COLUMNS}
        rows={scan.subscriptions}
        getRowId={(s) => s.subscription_id}
        getRowProps={(s) => ({ "data-testid": "scan-sub", "data-status": s.status })}
      />
      {resources.length === 0 ? (
        <EmptyState title={STRINGS.noResources} testId="scan-no-resources" />
      ) : (
        <DataTable
          label={STRINGS.resourcesTable}
          columns={RES_COLUMNS}
          rows={resources}
          getRowId={(r) => r.id}
          getRowProps={() => ({ "data-testid": "scan-resource" })}
        />
      )}
    </section>
  );
}

export interface ScanStepProps {
  readonly scan: ScanResponse | null;
  readonly onScanned: (scan: ScanResponse) => void;
}

/** Step 1. The consent record and the result stay in memory only; nothing is persisted. */
export function ScanStep({ scan, onScanned }: ScanStepProps): ReactElement {
  const styles = useStyles();
  const mutation = useScan();
  const [subs, setSubs] = useState("");
  const [consentId, setConsentId] = useState("");
  const [attestation, setAttestation] = useState("");
  const [same, setSame] = useState(true);
  const [consented, setConsented] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const subIds = splitLines(subs);
  const consentedIds = same ? subIds : splitLines(consented);
  const errors = {
    subs: checkSubscriptions(subIds),
    consentId: consentId.trim() === "" ? STRINGS.needConsentId : null,
    attestation: checkAttestation(attestation),
    consented: same ? null : checkSubscriptions(consentedIds),
  };
  const invalid = Object.values(errors).some((e) => e !== null);
  const show = (e: string | null): string | undefined => (submitted && e !== null ? e : undefined);
  // The email rejection shows as soon as it is typed, not only after submit.
  const attestationShown =
    attestation !== "" && errors.attestation !== null
      ? errors.attestation
      : show(errors.attestation);

  function run(): void {
    setSubmitted(true);
    if (invalid) return;
    mutation.mutate(
      {
        consent: {
          consent_id: consentId.trim(),
          consented_by: attestation.trim(),
          consented_subscriptions: consentedIds,
        },
        subscription_ids: subIds,
      },
      { onSuccess: onScanned },
    );
  }

  const error = mutation.isError ? mutation.error : null;
  return (
    <div className={styles.stack}>
      <Field
        label={STRINGS.subscriptionsLabel}
        hint={STRINGS.subscriptionsHint}
        validationState={show(errors.subs) === undefined ? "none" : "error"}
        validationMessage={show(errors.subs)}
      >
        <Textarea value={subs} onChange={(_, d) => setSubs(d.value)} rows={4} />
      </Field>
      <Field
        label={STRINGS.consentIdLabel}
        required
        validationState={show(errors.consentId) === undefined ? "none" : "error"}
        validationMessage={show(errors.consentId)}
      >
        <Input value={consentId} onChange={(_, d) => setConsentId(d.value)} />
      </Field>
      <Field
        label={STRINGS.attestationLabel}
        required
        hint={STRINGS.attestationHint}
        validationState={attestationShown === undefined ? "none" : "error"}
        validationMessage={attestationShown}
      >
        <Input value={attestation} onChange={(_, d) => setAttestation(d.value)} />
      </Field>
      <Checkbox
        checked={same}
        onChange={(_, d) => setSame(d.checked === true)}
        label={STRINGS.consentSame}
      />
      {same ? null : (
        <Field
          label={STRINGS.consentedLabel}
          validationState={show(errors.consented) === undefined ? "none" : "error"}
          validationMessage={show(errors.consented)}
        >
          <Textarea value={consented} onChange={(_, d) => setConsented(d.value)} rows={3} />
        </Field>
      )}
      <div>
        <Button
          appearance="primary"
          onClick={run}
          disabled={mutation.isPending}
          data-testid="scan-run"
        >
          {STRINGS.scanButton}
        </Button>
      </div>
      {error === null ? null : error instanceof ForbiddenError ? (
        <ForbiddenState
          workspace={STRINGS.forbiddenWorkspace}
          correlationId={error.correlationId}
        />
      ) : (
        <ErrorState
          title={STRINGS.scanFailed}
          message={error.correlationId === "" ? undefined : `Reference: ${error.correlationId}.`}
          testId="scan-error"
        />
      )}
      {scan === null ? null : <ScanResult scan={scan} />}
    </div>
  );
}
