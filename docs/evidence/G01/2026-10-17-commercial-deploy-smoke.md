# G01 Commercial deploy smoke - FAIL

- Gate: G01 (Commercial only; Government stays OPEN)
- Script version: 1.0.0
- Window (UTC): 2026-10-17T03:54:58Z to 2026-10-17T04:15:01Z
- Subscription: <subscription:bc2c0815>
- Resource group: rg-neurosphere-g01-smoke-cus (centralus)
- Health: OK
- Teardown performed: True ok: False

## Resources created

- Microsoft.EventHub/namespaces /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.EventHub/namespaces/nsphere-eh-p7eiwcjpiszno (Succeeded)
- Microsoft.DocumentDB/databaseAccounts /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.DocumentDB/databaseAccounts/nsphere-cosmos-p7eiwcjpiszno (Succeeded)
- Microsoft.OperationalInsights/workspaces /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.OperationalInsights/workspaces/nsphere-law-p7eiwcjpiszno (Succeeded)
- Microsoft.Search/searchServices /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.Search/searchServices/nsphere-search-p7eiwcjpiszno (Succeeded)
- Microsoft.Storage/storageAccounts /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.Storage/storageAccounts/nspherestp7eiwcjpiszno (Succeeded)
- Microsoft.KeyVault/vaults /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus/providers/Microsoft.KeyVault/vaults/nsphere-kv-p7eiwcjpiszno (Succeeded)

## Steps

- [ok] resource-group-create rg-neurosphere-g01-smoke-cus
- [ok] what-if 6 change(s)
- [ok] deployment-create Succeeded
- [ok] health 6 resources
- [ok] removal-plan 7 removable, reused untouched
- [ok] resource-group-delete rg-neurosphere-g01-smoke-cus
- [failed] keyvault-purge:nsphere-kv-p7eiwcjpiszno ERROR: (MethodNotAllowed) Operation 'DeletedVaultPurge' is not allowed. Code: MethodNotAllowed Message: Operation 'DeletedVaultPurge' is not allowed.

## Errors

- teardown did not complete cleanly
