import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link } from "react-router";
import { MutationError } from "./components";
import { useInvalidateReports, useSaveReport } from "./hooks";
import { buildSaveReportRequest } from "./request";
import { reportViewHref } from "./paths";
import { STRINGS } from "./strings";
import type { ChartPlan, ReportMetric, StructuredQuery } from "./types";

export interface SaveReportDialogProps {
  readonly chartPlan: ChartPlan;
  readonly querySpec: StructuredQuery;
  readonly metric?: ReportMetric | undefined;
  /** Preselected domain (for example the copilot context chip's domain). */
  readonly domainId?: string | undefined;
  readonly defaultTitle?: string | undefined;
}

/** Save-from-plan: the chat panel renders this next to an inline chart. */
export function SaveReportDialog({
  chartPlan,
  querySpec,
  metric,
  domainId = "",
  defaultTitle = "",
}: SaveReportDialogProps): ReactElement {
  const [title, setTitle] = useState(defaultTitle);
  const [domain, setDomain] = useState(domainId);
  const invalidate = useInvalidateReports();
  const save = useSaveReport();
  const body = buildSaveReportRequest({ title, chartPlan, querySpec, metric });
  const canSubmit = body !== null && domain.trim() !== "" && !save.isPending;

  return (
    <Dialog>
      <DialogTrigger disableButtonEnhancement>
        <Button data-testid="save-report-open">{STRINGS.save.open}</Button>
      </DialogTrigger>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{STRINGS.save.title}</DialogTitle>
          <DialogContent>
            <p>{STRINGS.save.help}</p>
            <form
              aria-label={STRINGS.save.title}
              onSubmit={(e) => {
                e.preventDefault();
                if (body === null || domain.trim() === "") return;
                save.mutate(
                  { domainId: domain.trim(), body },
                  { onSuccess: () => void invalidate() },
                );
              }}
            >
              <Field label={STRINGS.save.titleLabel}>
                <Input
                  value={title}
                  maxLength={200}
                  onChange={(_e, data) => setTitle(data.value)}
                />
              </Field>
              <Field label={STRINGS.save.domainLabel}>
                <Input value={domain} onChange={(_e, data) => setDomain(data.value)} />
              </Field>
              <Button type="submit" appearance="primary" disabled={!canSubmit}>
                {STRINGS.save.submit}
              </Button>
            </form>
            {save.isSuccess ? (
              <p role="status" data-testid="report-saved">
                {STRINGS.save.saved}{" "}
                <Link to={reportViewHref(save.data.domain_id, save.data.id)}>
                  {STRINGS.save.open_report}
                </Link>
              </p>
            ) : null}
            {save.error !== null ? <MutationError error={save.error} /> : null}
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary">{STRINGS.save.cancel}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
