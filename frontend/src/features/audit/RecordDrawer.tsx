import {
  Button,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  OverlayDrawer,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { Timestamp } from "../../design-system";
import { STRINGS } from "./strings";
import type { AuditRecord } from "./types";

const useStyles = makeStyles({
  list: {
    display: "grid",
    gridTemplateColumns: "minmax(120px, max-content) minmax(0, 1fr)",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  term: { fontWeight: tokens.fontWeightSemibold, color: tokens.colorNeutralForeground1 },
  value: { margin: 0, overflowWrap: "anywhere", color: tokens.colorNeutralForeground1 },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
});

interface Row {
  readonly label: string;
  readonly value: ReactNode;
  readonly mono?: boolean;
}

const text = (v: string | number | boolean | null | undefined): string =>
  v === null || v === undefined ? STRINGS.notRecorded : String(v);

/** Every field of the record, in the order and wording the API returned it. Lane-local DetailList. */
export function recordRows(r: AuditRecord): readonly Row[] {
  return [
    { label: "Sequence", value: text(r.sequence) },
    { label: "Kind", value: r.kind },
    { label: "Recorded at", value: <Timestamp value={r.recorded_at} /> },
    { label: "Operation", value: r.operation },
    { label: "Channel", value: text(r.channel) },
    { label: "Actor pseudonym", value: r.actor.principal_pseudonym },
    { label: "Actor kind", value: r.actor.principal_kind },
    { label: "On behalf of", value: text(r.actor.on_behalf_of) },
    { label: "Subject id", value: text(r.subject?.target.canonical_id) },
    { label: "Subject type", value: text(r.subject?.target.entity_type) },
    { label: "Subject version", value: text(r.subject?.target_version) },
    { label: "State digest", value: text(r.subject?.state_digest), mono: true },
    { label: "Snapshot ref", value: text(r.subject?.snapshot_ref) },
    { label: "Outcome result", value: text(r.outcome?.result) },
    { label: "Outcome verified", value: text(r.outcome?.verified) },
    { label: "Outcome detail", value: text(r.outcome?.detail) },
    { label: "Denial code", value: text(r.denial?.code) },
    { label: "Denial reason", value: text(r.denial?.reason) },
    { label: "Intent id", value: text(r.intent_id), mono: true },
    { label: "Correlation id", value: r.correlation_id, mono: true },
    { label: "Audit id", value: r.audit_id, mono: true },
    { label: "Chain id", value: r.chain_id, mono: true },
    { label: "Previous hash", value: text(r.previous_hash), mono: true },
    { label: "Record hash", value: r.record_hash, mono: true },
    { label: "Scope hash", value: r.scope_hash, mono: true },
    { label: "Schema version", value: r.schema_version },
  ];
}

export interface RecordDrawerProps {
  readonly record: AuditRecord | null;
  readonly onClose: () => void;
}

/** Read-only detail drawer; it has no copy-all or export control. */
export function RecordDrawer({ record, onClose }: RecordDrawerProps): ReactElement {
  const styles = useStyles();
  return (
    <OverlayDrawer
      open={record !== null}
      position="end"
      size="medium"
      onOpenChange={(_e, data) => {
        if (!data.open) onClose();
      }}
    >
      {record === null ? null : (
        <>
          <DrawerHeader>
            <DrawerHeaderTitle
              action={
                <Button appearance="subtle" onClick={onClose} data-testid="audit-drawer-close">
                  {STRINGS.drawerClose}
                </Button>
              }
            >
              {STRINGS.drawerTitle(record.sequence)}
            </DrawerHeaderTitle>
          </DrawerHeader>
          <DrawerBody
            data-testid="audit-drawer"
            tabIndex={0}
            role="region"
            aria-label={STRINGS.drawerTitle(record.sequence)}
          >
            <dl className={styles.list}>
              {recordRows(record).map((row) => (
                <div key={row.label} style={{ display: "contents" }}>
                  <dt className={styles.term}>{row.label}</dt>
                  <dd
                    className={row.mono === true ? `${styles.value} ${styles.mono}` : styles.value}
                  >
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </DrawerBody>
        </>
      )}
    </OverlayDrawer>
  );
}
