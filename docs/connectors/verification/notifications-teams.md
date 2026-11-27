# Microsoft Teams notification channel (PRP-107 item 1)

Status date: 2026-11-26. Every statement below was read from the cited page on that day while
writing this file (design item U-5). Rule for this document: **no payload shape, host or cloud
claim that is not on this page is coded**. Anything not found is "not coded".

## Verdict

| Channel kind | Commercial | Government | Verdict |
|---|---|---|---|
| `teams_webhook` (Workflows "When a Teams webhook request is received") | Available | GCC tenants only; not GCC High, not DoD | `degraded` |

`degraded` means: the sender is built and posts the documented Adaptive Card envelope below, but
it is offered only where the Workflows webhook exists. A Government deployment may create a
`teams_webhook` channel only when its allowed host is on that deployment's own egress allow-list
(the cloud-boundary rule of PRP-107); NeuroSphere does not assert which host a Government
Workflows URL uses, and it does not claim the channel works for GCC High or DoD tenants.

## Sources

| Source | Retrieved | What it says |
|---|---|---|
| [Create Incoming Webhooks](https://learn.microsoft.com/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook) | 2026-11-26 | Office 365 Connectors in Teams, including connector-based Incoming Webhooks, were retired in May 2026; webhooks are now created with the Workflows app. Message size limit 28 KB. More than four requests a second are throttled; retry with exponential backoff. Adaptive Card envelope example. HTML in card text is ignored. |
| [Microsoft Teams connector - Microsoft Teams Webhook](https://learn.microsoft.com/connectors/teams/#microsoft-teams-webhook) | 2026-11-26 | Trigger `TeamsIncomingWebhookTrigger`: POST only; the caller may be "anyone", any user in the tenant, or a subset of users; request body schema for Adaptive Cards and for a single MessageCard; actionable messages not supported. Connector available in all Power Automate regions except China. |
| [Plan for government clouds - Teams app capabilities](https://learn.microsoft.com/microsoftteams/platform/concepts/cloud-overview#teams-app-capabilities) | 2026-11-26 | Workflows: GCC yes, GCC High no, DoD no. |
| [Power Automate US Government](https://learn.microsoft.com/power-automate/us-govt) | 2026-11-26 | Separate GCC, GCC High and DoD service URLs; feature parity is not guaranteed. |

## What a posted message needs (coded)

`POST <workflow callback URL>` with `Content-Type: application/json` and this body:

```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "contentUrl": null,
      "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [{ "type": "TextBlock", "text": "..." }]
      }
    }
  ]
}
```

- `type` must be `message`; each attachment has `contentType`
  `application/vnd.microsoft.card.adaptive`, `contentUrl` null and the card in `content`.
- NeuroSphere uses `TextBlock` elements only (title, event class, severity, domain, ids, link,
  timestamp from the closed field set). No actions, no images, no mentions.
- The whole body stays under 28 KB; a larger body is refused before sending.
- A 2xx answer means "accepted by the workflow", not "posted" or "read".
- HTTP 429 and 5xx are retryable with the outbox backoff; other 4xx are terminal.

## Authentication

The callback URL itself is the credential: it is held only in Key Vault
(`endpoint_credential`, a `key_vault_secret` reference) and never stored, logged or shown.
The trigger's tenant-user and specific-user options need a Microsoft Entra bearer token from
the caller; NeuroSphere does not obtain one, so a channel must use a workflow whose trigger
allows "anyone" (the URL is the secret). The HMAC header NeuroSphere adds to generic webhooks is
not verified by Teams and is not sent on this kind.

## Not coded

- MessageCard payloads (supported by Workflows but not interactive; not needed).
- The host name of a Workflows callback URL in any cloud: the operator puts it on the
  allow-list after creating the workflow.
- Delivery to GCC High or DoD tenants (Workflows not available there).
- Bots, proactive messages, Graph `chatMessage` posting, per-person delivery (PRP-107 NOT
  building).
- Read receipts.

## Fallback

Where Workflows is unavailable (GCC High, DoD), use a `webhook` channel to a customer-run
receiver inside the same boundary, which can relay to Teams by its own approved means.

## Live gate

One real post to a Teams channel through a Workflows webhook needs an operator tenant and
`NS_LIVE_APPROVED=1`; it is OPEN here and handed to PRP-136.
