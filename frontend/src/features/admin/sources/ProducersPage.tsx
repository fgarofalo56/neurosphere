import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Select,
  Textarea,
} from "@fluentui/react-components";
import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  StatusPill,
} from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import {
  PRODUCERS_KEY,
  useCreateProducer,
  useInvalidate,
  useProducers,
  useReadProducer,
  useRotateProducer,
  useSetProducerStatus,
} from "./hooks";
import { PRODUCER_STRINGS as S, SOURCE_STRINGS as SS } from "./strings";
import { ADMIN_CONNECTORS_ROUTE } from "./apiPaths";
import { OBSERVATION_KINDS, type ProducerView } from "./types";

const PRODUCER_ID = /^[A-Za-z0-9_-]{1,128}$/;

/** Parses "source_id kind" lines into the sources map, or undefined when a line is wrong. */
export function parseSources(text: string): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l !== "");
  if (lines.length === 0) return undefined;
  for (const line of lines) {
    const [id, kind, ...rest] = line.split(/\s+/);
    if (
      id === undefined ||
      kind === undefined ||
      rest.length > 0 ||
      !OBSERVATION_KINDS.includes(kind as (typeof OBSERVATION_KINDS)[number])
    ) {
      return undefined;
    }
    out[id] = kind;
  }
  return out;
}

type Dialogs =
  | { readonly kind: "create" }
  | { readonly kind: "rotate"; readonly producer: ProducerView; readonly etag: string | undefined }
  | {
      readonly kind: "status";
      readonly producer: ProducerView;
      readonly etag: string | undefined;
      readonly enable: boolean;
    };

/** A one-time secret held only in this component's state; cleared on close and on unmount. */
interface Issued {
  readonly producerId: string;
  readonly secret: string;
}

function SecretDialog({
  issued,
  onDone,
}: {
  readonly issued: Issued;
  readonly onDone: () => void;
}): ReactElement {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog open modalType="alert" surfaceMotion={null}>
      <DialogSurface aria-describedby="secret-body" data-testid="secret-dialog">
        <DialogBody>
          <DialogTitle>{S.secret.title}</DialogTitle>
          <DialogContent id="secret-body">
            <p>
              {S.secret.warning} Producer: <code>{issued.producerId}</code>
            </p>
            <Field label={S.secret.label}>
              <code data-testid="secret-value" style={{ overflowWrap: "anywhere" }}>
                {issued.secret}
              </code>
            </Field>
            <div role="status" aria-live="polite" data-testid="secret-copied">
              {copied ? S.secret.copied : ""}
            </div>
          </DialogContent>
          <DialogActions>
            <Button
              onClick={() => {
                void navigator.clipboard?.writeText(issued.secret);
                setCopied(true);
              }}
            >
              {S.secret.copy}
            </Button>
            <Button appearance="primary" onClick={onDone}>
              {S.secret.confirm}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function ProducersBody(): ReactElement {
  const query = useProducers();
  const create = useCreateProducer();
  const rotate = useRotateProducer();
  const setStatus = useSetProducerStatus();
  const read = useReadProducer();
  const invalidate = useInvalidate(PRODUCERS_KEY);
  const [dialog, setDialog] = useState<Dialogs | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [producerId, setProducerId] = useState("");
  const [cloud, setCloud] = useState<"commercial" | "government">("commercial");
  const [sourcesText, setSourcesText] = useState("");

  // The secret never outlives this component.
  useEffect(() => () => setIssued(null), []);

  const closeDialog = (): void => {
    setDialog(null);
    create.reset();
    rotate.reset();
    setStatus.reset();
  };

  /** Moves the one-time secret into local state and drops it from the mutation cache. */
  const take = (producerIdOfSecret: string, secret: string, reset: () => void): void => {
    setIssued({ producerId: producerIdOfSecret, secret });
    reset();
    setDialog(null);
    void invalidate();
  };

  const openChange = (producer: ProducerView, kind: "rotate" | "status", enable = false): void => {
    closeDialog();
    setDone(null);
    read.mutate(producer.producer_id, {
      onSuccess: (r) =>
        setDialog(
          kind === "rotate"
            ? { kind: "rotate", producer, etag: r.etag }
            : { kind: "status", producer, etag: r.etag, enable },
        ),
    });
  };

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={4} />
      </div>
    );
  }
  const items = query.data.data.items;
  const parsedSources = parseSources(sourcesText);
  const createValid = PRODUCER_ID.test(producerId.trim()) && parsedSources !== undefined;

  return (
    <>
      <div>
        <Button
          appearance="primary"
          onClick={() => {
            closeDialog();
            setDone(null);
            setProducerId("");
            setSourcesText("");
            setDialog({ kind: "create" });
          }}
        >
          {S.create}
        </Button>
      </div>
      {done === null ? null : (
        <div role="status" data-testid="change-done">
          {done}
        </div>
      )}
      {read.isError ? (
        <div role="alert" data-testid="read-error">
          {S.dialog.readFailed} {changeErrorText(read.error)}
        </div>
      ) : null}
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState
            title={S.empty}
            description={S.emptyHint}
            action={
              <Link
                data-testid="empty-connectors-link"
                to={`/${ADMIN_CONNECTORS_ROUTE}#first-sources`}
              >
                {SS.producersEmptyLink}
              </Link>
            }
          />
        </div>
      ) : (
        <DataTable
          label={S.title}
          rows={items}
          getRowId={(row) => row.producer_id}
          getRowProps={() => ({ "data-testid": "producer-row" })}
          columns={[
            {
              key: "id",
              header: S.headers.id,
              render: (row) => <code>{row.producer_id}</code>,
            },
            { key: "cloud", header: S.headers.cloud, render: (row) => row.cloud },
            {
              key: "sources",
              header: S.headers.sources,
              render: (row) =>
                row.sources.map((s) => `${s.source_id} (${s.observation_kind})`).join(", "),
            },
            {
              key: "status",
              header: S.headers.status,
              render: (row) => (
                <StatusPill
                  label={row.status === "active" ? S.active : S.disabled}
                  tone={row.status === "active" ? "success" : "neutral"}
                />
              ),
            },
            {
              key: "rotated",
              header: S.headers.rotated,
              render: (row) => row.rotated_at ?? S.never,
            },
            {
              key: "actions",
              header: S.headers.actions,
              render: (row) => (
                <span style={{ display: "inline-flex", gap: 8 }}>
                  <Button
                    size="small"
                    aria-label={`${S.rotate} ${row.producer_id}`}
                    onClick={() => openChange(row, "rotate")}
                  >
                    {S.rotate}
                  </Button>
                  <Button
                    size="small"
                    aria-label={`${row.status === "active" ? S.disable : S.enable} ${row.producer_id}`}
                    onClick={() => openChange(row, "status", row.status !== "active")}
                  >
                    {row.status === "active" ? S.disable : S.enable}
                  </Button>
                </span>
              ),
            },
          ]}
        />
      )}

      {dialog?.kind === "create" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog.create}
          target={producerId.trim() === "" ? "(new producer)" : producerId.trim()}
          version={S.dialog.noVersion}
          diff={[
            {
              field: "producer",
              before: "none",
              after: `${cloud}, ${parsedSources === undefined ? "?" : Object.keys(parsedSources).length} source(s)`,
            },
          ]}
          reasonMode="code"
          controlsValid={createValid}
          submitting={create.isPending}
          error={create.isError ? changeErrorText(create.error) : undefined}
          controls={
            <>
              <Field label={S.fields.producerId} required>
                <Input value={producerId} onChange={(_e, d) => setProducerId(d.value)} />
              </Field>
              <Field label={S.fields.cloud} required>
                <Select
                  value={cloud}
                  onChange={(_e, d) => setCloud(d.value as "commercial" | "government")}
                >
                  <option value="commercial">commercial</option>
                  <option value="government">government</option>
                </Select>
              </Field>
              <Field
                label={S.fields.sources}
                required
                hint={S.sourcesHint}
                validationState={sourcesText.trim() !== "" && !parsedSources ? "error" : "none"}
                validationMessage={
                  sourcesText.trim() !== "" && !parsedSources ? S.sourcesInvalid : undefined
                }
              >
                <Textarea value={sourcesText} onChange={(_e, d) => setSourcesText(d.value)} />
              </Field>
            </>
          }
          onSubmit={() => {
            if (parsedSources === undefined) return;
            create.mutate(
              { producerId: producerId.trim(), cloud, sources: parsedSources },
              {
                onSuccess: (r) => take(r.data.producer_id, r.data.secret, create.reset),
              },
            );
          }}
          onClose={closeDialog}
        />
      ) : null}

      {dialog?.kind === "rotate" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog.rotate}
          target={dialog.producer.producer_id}
          version={dialog.etag ?? "unknown"}
          diff={[{ field: "secret", before: "current", after: "new (shown once)" }]}
          reasonMode="code"
          reasonNote={S.dialog.rotateNote}
          submitting={rotate.isPending}
          error={rotate.isError ? changeErrorText(rotate.error) : undefined}
          onSubmit={() =>
            rotate.mutate(
              { producerId: dialog.producer.producer_id, etag: dialog.etag },
              { onSuccess: (r) => take(r.data.producer_id, r.data.secret, rotate.reset) },
            )
          }
          onClose={closeDialog}
        />
      ) : null}

      {dialog?.kind === "status" ? (
        <ChangeConfirmDialog
          open
          title={dialog.enable ? S.dialog.enable : S.dialog.disable}
          target={dialog.producer.producer_id}
          version={dialog.etag ?? "unknown"}
          diff={[
            {
              field: "status",
              before: dialog.producer.status,
              after: dialog.enable ? "active" : "disabled",
            },
          ]}
          reasonMode="code"
          submitting={setStatus.isPending}
          error={setStatus.isError ? changeErrorText(setStatus.error) : undefined}
          onSubmit={() =>
            setStatus.mutate(
              { producerId: dialog.producer.producer_id, etag: dialog.etag, enable: dialog.enable },
              {
                onSuccess: () => {
                  setDone(S.done(dialog.enable ? S.dialog.enable : S.dialog.disable));
                  setDialog(null);
                  void invalidate();
                },
              },
            )
          }
          onClose={closeDialog}
        />
      ) : null}

      {issued === null ? null : <SecretDialog issued={issued} onDone={() => setIssued(null)} />}
    </>
  );
}

export function ProducersPage(): ReactElement {
  return (
    <PageTemplate title={S.title} description={S.description}>
      <AdminTabs />
      <ProducersBody />
    </PageTemplate>
  );
}
