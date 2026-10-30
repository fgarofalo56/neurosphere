import {
  Button,
  Checkbox,
  Field,
  Input,
  Radio,
  RadioGroup,
  Text,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  ANALYTICS_OPTIONS,
  CLOUD_OPTIONS,
  HOSTING_OPTIONS,
  REGIONS,
  STRINGS,
  type Cloud,
} from "./strings";
import {
  CATEGORY_SERVICE,
  MANIFEST_SERVICES,
  type DiscoveredResource,
  type ManifestService,
  type OwnerConsentRecord,
  type ScanResponse,
  type ServiceChoice,
} from "./types";
import { isPrincipal, splitLines } from "./validate";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  card: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS, alignItems: "center" },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

export type DraftDecision = "default" | "reuse" | "create" | "skip";

export interface ServiceDraft {
  readonly decision: DraftDecision;
  readonly resourceId: string;
  readonly sku: string;
  readonly fallback: "create" | "skip";
}

export interface ProfileDraft {
  readonly cloud: Cloud;
  readonly region: string;
  readonly hosting: string;
  readonly analytics: string;
}

export interface ChoicesDraft {
  readonly profile: ProfileDraft;
  readonly services: Readonly<Record<string, ServiceDraft>>;
  readonly consents: readonly OwnerConsentRecord[];
}

export const EMPTY_SERVICE: ServiceDraft = {
  decision: "default",
  resourceId: "",
  sku: "",
  fallback: "create",
};

export function initialDraft(): ChoicesDraft {
  return {
    profile: {
      cloud: "commercial",
      region: REGIONS.commercial[0] ?? "eastus",
      hosting: "aks",
      analytics: "fabric",
    },
    services: {},
    consents: [],
  };
}

/** Only explicit choices go on the wire; "planner default" sends nothing for that service. */
export function buildChoices(services: ChoicesDraft["services"]): Record<string, ServiceChoice> {
  const out: Record<string, ServiceChoice> = {};
  for (const [name, d] of Object.entries(services)) {
    if (d.decision === "default") continue;
    out[name] = {
      decision: d.decision,
      fallback: d.fallback,
      ...(d.decision === "reuse" && d.resourceId.trim() !== ""
        ? { resource_id: d.resourceId.trim() }
        : {}),
      ...(d.sku.trim() === "" ? {} : { sku: d.sku.trim() }),
    };
  }
  return out;
}

function candidatesFor(scan: ScanResponse | null, service: ManifestService): DiscoveredResource[] {
  if (scan === null) return [];
  return scan.subscriptions
    .flatMap((s) => s.resources)
    .filter((r) => CATEGORY_SERVICE[r.category] === service);
}

function ServiceRow({
  service,
  draft,
  candidates,
  onChange,
}: {
  readonly service: ManifestService;
  readonly draft: ServiceDraft;
  readonly candidates: readonly DiscoveredResource[];
  readonly onChange: (next: ServiceDraft) => void;
}): ReactElement {
  const styles = useStyles();
  return (
    <div className={styles.card} data-testid="choice-row" data-service={service}>
      <Text weight="semibold">{service}</Text>
      <RadioGroup
        layout="horizontal"
        aria-label={`Decision for ${service}`}
        value={draft.decision}
        onChange={(_, d) => onChange({ ...draft, decision: d.value as DraftDecision })}
      >
        <Radio value="default" label={STRINGS.decisionDefault} />
        <Radio value="reuse" label="reuse" />
        <Radio value="create" label="create" />
        <Radio value="skip" label="skip" />
      </RadioGroup>
      {draft.decision === "default" || draft.decision === "skip" ? null : (
        <>
          {draft.decision === "reuse" ? (
            <Field label={`${STRINGS.resourceIdLabel} (${service})`}>
              <Input
                value={draft.resourceId}
                onChange={(_, d) => onChange({ ...draft, resourceId: d.value })}
              />
            </Field>
          ) : null}
          <Field label={`${STRINGS.skuLabel} (${service})`}>
            <Input value={draft.sku} onChange={(_, d) => onChange({ ...draft, sku: d.value })} />
          </Field>
          <Field label={`${STRINGS.fallbackLabel} (${service})`}>
            <RadioGroup
              layout="horizontal"
              value={draft.fallback}
              onChange={(_, d) => onChange({ ...draft, fallback: d.value as "create" | "skip" })}
            >
              <Radio value="create" label="create" />
              <Radio value="skip" label="skip" />
            </RadioGroup>
          </Field>
        </>
      )}
      {draft.decision === "reuse" && candidates.length > 0 ? (
        <div className={styles.row}>
          <Text className={styles.muted}>{STRINGS.candidates}:</Text>
          {candidates.map((c) => (
            <Button
              key={c.id}
              size="small"
              onClick={() => onChange({ ...draft, resourceId: c.id, sku: c.sku ?? draft.sku })}
            >
              {STRINGS.useCandidate(c.name)}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ConsentForm({
  onAdd,
}: {
  readonly onAdd: (record: OwnerConsentRecord) => void;
}): ReactElement {
  const styles = useStyles();
  const [id, setId] = useState("");
  const [granted, setGranted] = useState(true);
  const [principal, setPrincipal] = useState("");
  const [resources, setResources] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const resourceIds = splitLines(resources);
  const errors = {
    id: id.trim() === "" ? STRINGS.needOwnerConsentId : null,
    principal:
      principal !== "" && !isPrincipal(principal)
        ? STRINGS.principalInvalid
        : granted && principal === ""
          ? STRINGS.needGrantedPrincipal
          : null,
    resources: resourceIds.length === 0 ? STRINGS.needOwnerResources : null,
  };
  const shown = (e: string | null): string | undefined => (submitted && e !== null ? e : undefined);
  const principalShown =
    principal !== "" && errors.principal !== null ? errors.principal : shown(errors.principal);

  function add(): void {
    setSubmitted(true);
    if (Object.values(errors).some((e) => e !== null)) return;
    onAdd({
      consent_id: id.trim(),
      granted,
      ...(principal === "" ? {} : { owner_principal: principal }),
      resource_ids: resourceIds,
      recorded_at: new Date().toISOString(),
    });
    setId("");
    setPrincipal("");
    setResources("");
    setSubmitted(false);
  }

  return (
    <div className={styles.card}>
      <Field
        label={STRINGS.ownerConsentId}
        validationState={shown(errors.id) === undefined ? "none" : "error"}
        validationMessage={shown(errors.id)}
      >
        <Input value={id} onChange={(_, d) => setId(d.value)} />
      </Field>
      <Checkbox
        checked={granted}
        onChange={(_, d) => setGranted(d.checked === true)}
        label={STRINGS.ownerGranted}
      />
      <Field
        label={STRINGS.ownerPrincipal}
        validationState={principalShown === undefined ? "none" : "error"}
        validationMessage={principalShown}
      >
        <Input value={principal} onChange={(_, d) => setPrincipal(d.value)} />
      </Field>
      <Field
        label={STRINGS.ownerResourceIds}
        validationState={shown(errors.resources) === undefined ? "none" : "error"}
        validationMessage={shown(errors.resources)}
      >
        <Textarea value={resources} onChange={(_, d) => setResources(d.value)} rows={3} />
      </Field>
      <div>
        <Button onClick={add} data-testid="consent-add">
          {STRINGS.addConsent}
        </Button>
      </div>
    </div>
  );
}

export interface ChoicesStepProps {
  readonly scan: ScanResponse | null;
  readonly draft: ChoicesDraft;
  readonly onChange: (next: ChoicesDraft) => void;
}

/** Step 2: profile, per-service reuse/create/skip, and owner consent records for shared reuse. */
export function ChoicesStep({ scan, draft, onChange }: ChoicesStepProps): ReactElement {
  const styles = useStyles();
  const { profile } = draft;
  const setProfile = (next: ProfileDraft): void => onChange({ ...draft, profile: next });
  return (
    <div className={styles.stack}>
      <section className={styles.card} aria-label={STRINGS.profileTitle}>
        <Text weight="semibold">{STRINGS.profileTitle}</Text>
        <Field label={STRINGS.cloudLabel}>
          <RadioGroup
            layout="horizontal"
            value={profile.cloud}
            onChange={(_, d) => {
              const cloud = d.value as Cloud;
              // A region never carries across clouds: a Government profile has no Commercial region.
              setProfile({ ...profile, cloud, region: REGIONS[cloud][0] ?? "" });
            }}
          >
            {CLOUD_OPTIONS.map((c) => (
              <Radio key={c} value={c} label={c} />
            ))}
          </RadioGroup>
        </Field>
        <Field label={STRINGS.regionLabel}>
          <RadioGroup
            layout="horizontal"
            value={profile.region}
            onChange={(_, d) => setProfile({ ...profile, region: d.value })}
          >
            {REGIONS[profile.cloud].map((r) => (
              <Radio key={r} value={r} label={r} />
            ))}
          </RadioGroup>
        </Field>
        <Field label={STRINGS.hostingLabel}>
          <RadioGroup
            layout="horizontal"
            value={profile.hosting}
            onChange={(_, d) => setProfile({ ...profile, hosting: d.value })}
          >
            {HOSTING_OPTIONS.map((h) => (
              <Radio key={h} value={h} label={h} />
            ))}
          </RadioGroup>
        </Field>
        <Field label={STRINGS.analyticsLabel}>
          <RadioGroup
            layout="horizontal"
            value={profile.analytics}
            onChange={(_, d) => setProfile({ ...profile, analytics: d.value })}
          >
            {ANALYTICS_OPTIONS.map((a) => (
              <Radio key={a} value={a} label={a} />
            ))}
          </RadioGroup>
        </Field>
      </section>

      <section className={styles.stack} aria-label={STRINGS.servicesTitle}>
        <Text weight="semibold">{STRINGS.servicesTitle}</Text>
        <Text className={styles.muted}>{STRINGS.servicesHint}</Text>
        {MANIFEST_SERVICES.map((service) => (
          <ServiceRow
            key={service}
            service={service}
            draft={draft.services[service] ?? EMPTY_SERVICE}
            candidates={candidatesFor(scan, service)}
            onChange={(next) =>
              onChange({ ...draft, services: { ...draft.services, [service]: next } })
            }
          />
        ))}
      </section>

      <section className={styles.stack} aria-label={STRINGS.consentsTitle}>
        <Text weight="semibold">{STRINGS.consentsTitle}</Text>
        <Text className={styles.muted}>{STRINGS.consentsHint}</Text>
        {draft.consents.map((c) => (
          <div key={c.consent_id} className={styles.row} data-testid="consent-row">
            <Text>
              {c.consent_id}: {c.granted ? "granted" : "not granted"}
              {c.owner_principal === undefined ? "" : ` by ${c.owner_principal}`},{" "}
              {c.resource_ids.length} resource id(s)
            </Text>
            <Button
              size="small"
              aria-label={STRINGS.removeConsent(c.consent_id)}
              onClick={() =>
                onChange({
                  ...draft,
                  consents: draft.consents.filter((x) => x.consent_id !== c.consent_id),
                })
              }
            >
              Remove
            </Button>
          </div>
        ))}
        <ConsentForm onAdd={(rec) => onChange({ ...draft, consents: [...draft.consents, rec] })} />
      </section>
    </div>
  );
}
