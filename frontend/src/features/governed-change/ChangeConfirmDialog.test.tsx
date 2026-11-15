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
    // hidden: Tabster can mark the dialog subtree aria-hidden mid-animation under load.
    const reason = await screen.findByRole("textbox", { name: /Reason/, hidden: true });
    await user.type(reason, "   ");
    expect(submit).toBeDisabled();
    await user.type(reason, " duplicate edge ");
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

describe("ChangeConfirmDialog code mode", () => {
  function CodeHarness(props: {
    readonly valid: boolean;
    readonly onSubmit: (v: ChangeConfirmSubmit) => void;
  }): ReactElement {
    return (
      <FluentProvider theme={webLightTheme}>
        <ChangeConfirmDialog
          open
          target={TARGET}
          version="etag-7"
          diff={DIFF}
          reasonMode="code"
          controls={<span data-testid="slot">picker</span>}
          controlsValid={props.valid}
          onSubmit={props.onSubmit}
          onClose={vi.fn()}
        />
      </FluentProvider>
    );
  }

  it("hides the free-text reason and renders the controls slot", async () => {
    render(<CodeHarness valid onSubmit={vi.fn()} />);
    expect(await screen.findByTestId("slot")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { hidden: true })).toBeNull();
  });

  it("enables submit only while the slot reports valid, with an empty reason", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<CodeHarness valid={false} onSubmit={onSubmit} />);
    const submit = await screen.findByRole("button", { name: "Confirm change", hidden: true });
    expect(submit).toBeDisabled();
    rerender(<CodeHarness valid onSubmit={onSubmit} />);
    const enabled = await screen.findByRole("button", { name: "Confirm change", hidden: true });
    await userEvent.setup().click(enabled);
    expect(onSubmit).toHaveBeenCalledWith({ reason: "", expiry: null });
  });
});
