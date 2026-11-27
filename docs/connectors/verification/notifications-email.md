# Email notification channel (PRP-107 item 1)

Status date: 2026-11-26. Every statement below was read from the cited page on that day while
writing this file (design item U-6). Rule for this document: **no transport, payload or cloud
claim that is not on this page is coded**.

## Verdict

| Channel kind | Commercial | Government | Verdict |
|---|---|---|---|
| `email` | Transport exists (Azure Communication Services Email, SDK/REST and SMTP) | Transport exists (ACS Email GA through SDK/REST; SMTP not supported) | `not_built` |

`not_built` in PRP-107: the admin page lists the kind with the reason
`email_transport_not_built`, and the channel create route refuses `kind: email`. No email
sender code exists. The reason is not availability but cost and dependency: every verified
transport needs a paid, operator-provisioned Azure Communication Services resource with a
verified sender domain, plus either a new client library or a hand-written request signer, and
the owner decision GD-10 puts email after the transport is verified and approved.

## Transport options found

| Option | Commercial | Government | New dependency | Paid | Notes |
|---|---|---|---|---|---|
| ACS Email through the Python SDK (`azure-communication-email`) | Yes | Yes (GA) | Yes (new package) | Yes, per message, on an ACS resource | Auth: connection string, `AzureKeyCredential`, or Microsoft Entra ID (`DefaultAzureCredential`); the docs recommend service principals in production. |
| ACS Email REST API (`Email` group, version 2023-03-31) over the existing `httpx` | Yes | Yes (the Government page names SDK-based sending; REST is what the SDK calls) | No package, but a hand-written HMAC request signer or an Entra token flow | Yes | Same resource and domain prerequisites as the SDK. |
| ACS SMTP endpoint | Yes | **No** ("SMTP endpoint is not supported in Azure US Government Cloud at this time") | No (stdlib `smtplib`) | Yes | Not usable for a Government deployment. |
| A customer-run SMTP relay over stdlib `smtplib` | n/a | n/a | No | No new paid dependency | Not an Azure service; would need an SMTP egress guard (STARTTLS, pinned connect, allowed host). The PRP-107 egress guard is HTTP-only. |

The only option with **no new paid dependency** is a customer-run SMTP relay over stdlib
`smtplib`, and it needs an SMTP-specific egress guard that this PRP does not build.

## Limits recorded (ACS Email)

- Send rate per subscription for custom domains: 30 emails a minute, 100 an hour (higher on
  request); Azure-managed domains: 5 a minute, 10 an hour (no increase).
- Up to 50 recipients per email; total request size 10 MB including attachments.
- A successful send-status poll means "out for delivery", not "delivered to the recipient".

## Sources

| Source | Retrieved | What it says |
|---|---|---|
| [Azure Communication Services for US Government](https://learn.microsoft.com/azure/communication-services/concepts/government) | 2026-11-26 | GA in Azure Government; Email included; email through SDK-based integration; SMTP endpoint not supported in Azure US Government. |
| [Email SDK features](https://learn.microsoft.com/azure/communication-services/concepts/email/sdk-features) | 2026-11-26 | Email client libraries (REST protocol) for send and status, including Python. |
| [Send an email using Azure Communication Services](https://learn.microsoft.com/azure/communication-services/quickstarts/email/send-email) | 2026-11-26 | Sender address from a verified domain, recipients, subject and plain-text/HTML content; authentication options; small per-message cost. |
| [Azure Communication Services REST API](https://learn.microsoft.com/rest/api/communication/) | 2026-11-26 | `Email` group, current API version 2023-03-31. |
| [Service limits - Email](https://learn.microsoft.com/azure/communication-services/concepts/service-limits#email) | 2026-11-26 | Rate and size limits above. |

## Not coded

- Any email sender, MIME body, SMTP session or ACS request.
- Per-person addresses (channels are group-addressed; a distribution-list address would live in
  the channel's Key Vault secret when this is built).

## Path to build (follow-up)

Pick the ACS Email REST option (works in both clouds, no new package), provision the ACS
resource and a verified domain with operator approval, add an Entra token flow for the
managed identity, then lift `email` from `not_built`. Live delivery is OPEN and handed to
PRP-136.
