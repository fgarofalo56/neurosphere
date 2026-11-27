import { useMutation } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { UnexpectedResponseError, type ApiError } from "../../../api/index.js";
import { ChangeConfirmDialog, type ChangeDiffRow } from "../../governed-change";
import { changeErrorText } from "../shared/AdminStates";
import {
  adminRequest,
  useAdminTransport,
  type AdminRequest,
  type AdminResponse,
} from "../shared/transport";
import { NOTIFICATION_STRINGS as S } from "./strings";

export interface PendingChange {
  readonly title: string;
  readonly target: string;
  readonly version: string;
  readonly diff: readonly ChangeDiffRow[];
  readonly request: AdminRequest;
}

function show(value: unknown): string {
  if (value === undefined || value === null) return "none";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Top-level before/after rows for the fields that differ. Credentials are references only. */
export function diffRows(
  before: Readonly<Record<string, unknown>> | null,
  after: Readonly<Record<string, unknown>>,
): ChangeDiffRow[] {
  const rows: ChangeDiffRow[] = [];
  for (const [field, value] of Object.entries(after)) {
    if (field === "schema_version") continue;
    const old = before?.[field];
    if (show(old) !== show(value)) rows.push({ field, before: show(old), after: show(value) });
  }
  return rows;
}

/** Problem text for a failed write: a stale version (409 or 412) or the API's own reason code. */
export function errorText(error: ApiError): string {
  if (error.status === 409 || error.status === 412) {
    const code = error.problem?.code;
    if (code !== undefined && code !== "stale_version" && error.status === 409) {
      return `Refused: ${code}`;
    }
    return S.stale;
  }
  if (error.status === 428) return S.stale;
  const code = error.problem?.code;
  if (error.status === 422 && code !== undefined) {
    return `Refused: ${code}${error.problem?.detail === undefined ? "" : ` (${error.problem.detail})`}`;
  }
  return changeErrorText(error);
}

/** The governed-change confirm dialog wired to one request. Sends If-Match as the request says. */
export function ConfirmedChange({
  change,
  onDone,
  onClose,
}: {
  readonly change: PendingChange;
  readonly onDone: (response: AdminResponse<unknown>) => void;
  readonly onClose: () => void;
}): ReactElement {
  const transport = useAdminTransport();
  const mutation = useMutation<AdminResponse<unknown>, ApiError, null>({
    mutationFn: async () => {
      try {
        return await adminRequest<unknown>(transport, change.request);
      } catch (caught) {
        // A successful DELETE answers 204 with no body, which the shared transport reports as
        // an unexpected empty response.
        if (caught instanceof UnexpectedResponseError && caught.status === 204) {
          return { data: null, etag: undefined };
        }
        throw caught;
      }
    },
  });
  return (
    <ChangeConfirmDialog
      open
      title={change.title}
      target={change.target}
      version={change.version}
      diff={change.diff}
      reasonMode="code"
      submitting={mutation.isPending}
      error={
        mutation.isError ? (
          <span data-testid="notification-error">{errorText(mutation.error)}</span>
        ) : undefined
      }
      onSubmit={() => mutation.mutate(null, { onSuccess: (response) => onDone(response) })}
      onClose={() => {
        mutation.reset();
        onClose();
      }}
    />
  );
}
