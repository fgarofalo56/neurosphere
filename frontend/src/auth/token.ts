import {
  InteractionRequiredAuthError,
  type AccountInfo,
  type IPublicClientApplication,
} from "@azure/msal-browser";

interface TokenSource {
  readonly instance: IPublicClientApplication;
  readonly scopes: readonly string[];
}

let source: TokenSource | null = null;

/** Called by AuthProvider. Returns an unregister function. */
export function registerTokenSource(
  instance: IPublicClientApplication,
  apiScope: string,
): () => void {
  const entry: TokenSource = { instance, scopes: [apiScope] };
  source = entry;
  return () => {
    if (source === entry) source = null;
  };
}

function pickAccount(instance: IPublicClientApplication): AccountInfo | null {
  return instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null;
}

/**
 * The ONLY token exit. Silent acquisition first; falls back to a redirect when
 * interaction is required. Never logs or stores the token anywhere else.
 */
export async function getToken(): Promise<string> {
  if (source === null) {
    throw new Error("Auth is not initialised");
  }
  const { instance, scopes } = source;
  const account = pickAccount(instance);
  if (account === null) {
    await instance.loginRedirect({ scopes: [...scopes] });
    throw new Error("Redirecting to sign-in");
  }
  try {
    const result = await instance.acquireTokenSilent({ scopes: [...scopes], account });
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await instance.acquireTokenRedirect({ scopes: [...scopes], account });
      throw new Error("Redirecting to sign-in", { cause: error });
    }
    throw error;
  }
}

export async function signOut(): Promise<void> {
  if (source === null) return;
  const { instance } = source;
  const account = pickAccount(instance);
  await instance.logoutRedirect(account === null ? undefined : { account });
}
