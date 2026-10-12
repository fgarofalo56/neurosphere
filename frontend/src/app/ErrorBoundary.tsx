import { Component, type ReactNode } from "react";

interface Props {
  readonly children: ReactNode;
}

interface State {
  readonly error: Error | null;
}

/** Reads a correlation ID off an error if the API client attached one. */
export function correlationIdOf(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const id = (error as { correlationId?: unknown }).correlationId;
  return typeof id === "string" && id !== "" ? id : undefined;
}

/** Catches render errors. Error contents are deliberately never logged (may carry tokens or user data). */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  private readonly reset = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;
    const correlationId = correlationIdOf(error);
    return (
      <div role="alert">
        <h2>Something went wrong</h2>
        <p>This page hit an unexpected error. You can try again or return to the home page.</p>
        {correlationId !== undefined && (
          <p>
            Correlation ID: <code>{correlationId}</code>
          </p>
        )}
        <button type="button" onClick={this.reset}>
          Try again
        </button>
      </div>
    );
  }
}
