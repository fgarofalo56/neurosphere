import { Button, FluentProvider, webLightTheme } from "@fluentui/react-components";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChangeConfirmDialog, type ChangeConfirmSubmit } from "./index";

afterEach(cleanup);

const TARGET = "commercial:e2e:sandbox:edge:agent-a/uses/model-b";
const DIFF = [{ field: "status", before: "inferred", after: "curated" }] as const;

function Harness(props: {
  readonly onSubmit: (v: ChangeConfirmSubmit) => void;
  readonly showExpiry?: boolean;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <FluentProvider theme={webLightTheme}>
      <Button ref={ref} onClick={() => setOpen(true)}>
        Open change
      </Button>
      <ChangeConfirmDialog
        open={open}
        target={TARGET}
        version="etag-7"
        diff={DIFF}
        showExpiry={props.showExpiry}
        triggerRef={ref}
        onSubmit={props.onSubmit}
        onClose={() => setOpen(false)}
      />
    </FluentProvider>
  );
}

describe("ChangeConfirmDialog", () => {
  it("shows target, version and the before/after diff", async () => {
    const user = userEvent.setup();
    render(<Harness onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Open change" }));
    expect(await screen.findByTestId("change-target")).toHaveTextContent(TARGET);
    expect(screen.getByTestId("change-version")).toHaveTextContent("etag-7");
    const row = screen.getByTestId("change-diff-row");
    expect(row).toHaveTextContent("status");
    expect(row).toHaveTextContent("inferred");
    expect(row).toHaveTextContent("curated");
  });

  it("keeps submit disabled until a reason is given, then submits it trimmed", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: "Open change" }));
    const submit = await screen.findByRole("button", { name: "Confirm change" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: /Reason/ }), "   ");
    expect(submit).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: /Reason/ }), " duplicate edge ");
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({ reason: "duplicate edge", expiry: null });
  });

  it("offers the expiry control only when asked", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Open change" }));
    await screen.findByTestId("change-target");
    expect(screen.queryByLabelText(/Expiry/)).toBeNull();
    rerender(<Harness onSubmit={vi.fn()} showExpiry />);
    expect(screen.getByLabelText(/Expiry/)).toBeInTheDocument();
  });

  it("returns focus to the trigger when cancelled", async () => {
    const user = userEvent.setup();
    render(<Harness onSubmit={vi.fn()} />);
    const opener = screen.getByRole("button", { name: "Open change" });
    await user.click(opener);
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
