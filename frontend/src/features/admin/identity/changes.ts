import type { ChangeDiffRow } from "../../governed-change/ChangeConfirmDialog";
import { identityPaths } from "../shared/adminPaths";
import { isReasonCode } from "../shared/ReasonCodeField";
import type { AdminRequest } from "../shared/transport";
import { IDENTITY_STRINGS as S } from "./strings";
import type { GrantPermission, PrincipalSummary, RoleName } from "./types";

export type DraftKind =
  | "assign-role"
  | "remove-role"
  | "add-membership"
  | "remove-membership"
  | "put-grant"
  | "remove-grant"
  | "revoke"
  | "lift";

/** What the administrator chose to change. Ids are fixed when the dialog opens. */
export interface Draft {
  readonly kind: DraftKind;
  /** Role assignment id (new for assign, existing for remove) or grant id. */
  readonly recordId?: string;
  readonly domainId?: string;
}

export interface ChangeForm {
  readonly role: RoleName;
  readonly domainIds: string;
  readonly domainId: string;
  readonly resourceId: string;
  readonly permissions: readonly GrantPermission[];
  readonly mode: "issued_before" | "until_lifted";
  readonly reason: string;
}

export const EMPTY_FORM: ChangeForm = {
  role: "viewer",
  domainIds: "",
  domainId: "",
  resourceId: "",
  permissions: ["read"],
  mode: "until_lifted",
  reason: "",
};

const SCHEMA = "1.0.0";

export function titleOf(kind: DraftKind): string {
  switch (kind) {
    case "assign-role":
      return S.dialog.assign;
    case "remove-role":
      return S.dialog.removeRole;
    case "add-membership":
      return S.dialog.addMembership;
    case "remove-membership":
      return S.dialog.removeMembership;
    case "put-grant":
      return S.dialog.putGrant;
    case "remove-grant":
      return S.dialog.removeGrant;
    case "revoke":
      return S.dialog.revoke;
    case "lift":
      return S.dialog.lift;
  }
}

export function splitIds(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

/** Whether the reason code is required: a grant removal route takes none. */
export function needsReason(kind: DraftKind): boolean {
  return kind !== "remove-grant";
}

export function expiryRequired(kind: DraftKind): boolean {
  return kind === "put-grant";
}

export function showsExpiry(kind: DraftKind): boolean {
  return kind === "put-grant" || kind === "assign-role";
}

/** True when every field the change needs is filled; the API still validates all of it. */
export function formValid(draft: Draft, form: ChangeForm): boolean {
  if (needsReason(draft.kind) && !isReasonCode(form.reason)) return false;
  switch (draft.kind) {
    case "assign-role":
      return splitIds(form.domainIds).length > 0;
    case "add-membership":
      return form.domainId.trim() !== "";
    case "put-grant":
      return form.resourceId.trim() !== "" && form.permissions.length > 0;
    default:
      return true;
  }
}

function listOf(values: readonly string[]): string {
  return values.length === 0 ? "none" : values.join(", ");
}

export function diffOf(draft: Draft, form: ChangeForm, summary: PrincipalSummary): ChangeDiffRow[] {
  switch (draft.kind) {
    case "assign-role":
      return [
        {
          field: "role assignment",
          before: "none",
          after: `${form.role} on ${listOf(splitIds(form.domainIds))}`,
        },
      ];
    case "remove-role": {
      const found = summary.assignments.find((a) => a.assignment_id === draft.recordId);
      return [
        {
          field: "role assignment",
          before: found === undefined ? "unknown" : `${found.role} on ${listOf(found.domain_ids)}`,
          after: "removed",
        },
      ];
    }
    case "add-membership":
      return [{ field: "domain membership", before: "none", after: form.domainId.trim() }];
    case "remove-membership":
      return [
        { field: "domain membership", before: draft.domainId ?? "unknown", after: "removed" },
      ];
    case "put-grant":
      return [
        {
          field: "resource grant",
          before: "none",
          after: `${listOf(form.permissions)} on ${form.resourceId.trim()}`,
        },
      ];
    case "remove-grant": {
      const found = summary.grants.find((g) => g.grant_id === draft.recordId);
      return [
        {
          field: "resource grant",
          before:
            found === undefined
              ? "unknown"
              : `${listOf(found.permissions)} on ${found.resource_id}`,
          after: "removed",
        },
      ];
    }
    case "revoke":
      return [{ field: "revocation", before: "not revoked", after: form.mode }];
    case "lift":
      return [
        { field: "revocation", before: summary.revocation.mode ?? "revoked", after: "lifted" },
      ];
  }
}

/** The ETag the dialog shows as "version"; revocation is not bound to the document ETag. */
export function versionOf(kind: DraftKind, etag: string | undefined): string {
  if (kind === "revoke" || kind === "lift") return S.dialog.noRevocationEtag;
  return etag ?? S.dialog.noEtag;
}

/** `datetime-local` text to the RFC 3339 UTC timestamp the API expects. */
export function toTimestamp(local: string): string {
  return new Date(local).toISOString();
}

export function buildRequest(
  draft: Draft,
  form: ChangeForm,
  ctx: { principalId: string; etag: string | undefined; expiry: string | null },
): AdminRequest {
  const { principalId, etag } = ctx;
  const expires = ctx.expiry === null ? null : toTimestamp(ctx.expiry);
  const recordId = draft.recordId ?? "";
  const reason = form.reason;
  switch (draft.kind) {
    case "assign-role":
      return {
        method: "PUT",
        path: identityPaths.role(principalId, recordId),
        ifMatch: etag,
        body: {
          schema_version: SCHEMA,
          op: "assign",
          principal_id: principalId,
          assignment_id: recordId,
          role: form.role,
          domain_ids: splitIds(form.domainIds),
          expires_at: expires,
          reason,
        },
      };
    case "remove-role":
      return {
        method: "DELETE",
        path: identityPaths.role(principalId, recordId),
        query: { reason },
        ifMatch: etag,
      };
    case "add-membership": {
      const domainId = form.domainId.trim();
      return {
        method: "PUT",
        path: identityPaths.membership(principalId, domainId),
        ifMatch: etag,
        body: {
          schema_version: SCHEMA,
          op: "add",
          principal_id: principalId,
          domain_id: domainId,
          reason,
        },
      };
    }
    case "remove-membership":
      return {
        method: "DELETE",
        path: identityPaths.membership(principalId, draft.domainId ?? ""),
        query: { reason },
        ifMatch: etag,
      };
    case "put-grant":
      return {
        method: "PUT",
        path: identityPaths.grant(principalId, recordId),
        ifMatch: etag,
        body: {
          schema_version: SCHEMA,
          principal_id: principalId,
          grant_id: recordId,
          resource_id: form.resourceId.trim(),
          permissions: form.permissions,
          expires_at: expires,
          reason,
        },
      };
    case "remove-grant":
      return { method: "DELETE", path: identityPaths.grant(principalId, recordId), ifMatch: etag };
    case "revoke":
      return {
        method: "POST",
        path: identityPaths.revocation(principalId),
        body: { schema_version: SCHEMA, reason, mode: form.mode },
      };
    case "lift":
      return {
        method: "DELETE",
        path: identityPaths.revocation(principalId),
        query: { reason },
      };
  }
}

/** True when the expiry is before `now`: the assignment or grant no longer applies. */
export function isExpired(expiresAt: string | null, now: number = Date.now()): boolean {
  if (expiresAt === null) return false;
  const at = Date.parse(expiresAt);
  return !Number.isNaN(at) && at <= now;
}
