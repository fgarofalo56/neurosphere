import { existsSync } from "node:fs";
import { AUTH_STATE_FILE } from "../../playwright.hosted.config";

/**
 * Refuses to start the hosted run without a target and a signed-in state. It runs for a real run
 * only (not for `--list`), which is how listing stays possible offline.
 */
export default function globalSetup(): void {
  const url = process.env["NS_HOSTED_URL"];
  if (url === undefined || url === "") {
    throw new Error("NS_HOSTED_URL is not set: point it at the deployed frontend, https://<host>");
  }
  if (!url.startsWith("https://")) {
    throw new Error("NS_HOSTED_URL must be an https:// URL");
  }
  if (!existsSync(AUTH_STATE_FILE)) {
    throw new Error(
      "temp/hosted-demo/auth.json is missing: save a signed-in Playwright storageState there first",
    );
  }
}
