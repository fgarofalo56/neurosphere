# PRP-06 live Cosmos run (2026-10-13)

Operator-approved live run (NS_LIVE_APPROVED=1) against a throwaway serverless Commercial
Cosmos NoSQL account, Entra auth only. Outcomes only: no document content or identities.

| Check | Outcome | Pass |
|---|---|---|
| audit: 4 parallel writers, 12 appends, chain verifies | records=12 sequences_contiguous=True verify_ok=True | yes |
| audit records: replace_item refused by the service | HTTP 403 | yes |
| audit records: upsert_item refused by the service | HTTP 403 | yes |
| audit records: delete_item refused by the service | HTTP 403 | yes |
| audit records: patch_item refused by the service | HTTP 403 | yes |
| audit: chain still verifies after the refused mutations | verify_ok=True records_checked=12 | yes |
| policy: head and principal read through CosmosPolicyRepository; absent doc is None | head=ok principal=ok absent_is_none=True | yes |
| revocation: put/get round trip; a later revocation replaces the earlier one | read_back=True newer_kept=True | yes |

Scope of the immutability result: the 403s prove the SERVICE refuses replace, upsert, patch
and delete on the audit records container for this identity, because its role grants only
create/read/query there. It is not a WORM guarantee: an account owner or anyone holding a
broader data-plane or control-plane role can still change data, so the hash chain remains
the tamper-detection control. Not a compliance, ATO or FedRAMP claim.
