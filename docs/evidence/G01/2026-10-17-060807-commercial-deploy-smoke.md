# G01 Commercial deploy smoke - PASS

- Gate: G01 (Commercial only; Government stays OPEN)
- Script version: 1.0.0
- Window (UTC): 2026-10-17T05:47:56Z to 2026-10-17T06:08:07Z
- Subscription: <subscription:bc2c0815>
- Resource group: rg-neurosphere-g01-smoke-cus2 (centralus)
- Health: OK
- Teardown performed: True ok: True

## Resources created

- Microsoft.Storage/storageAccounts /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.Storage/storageAccounts/nspherestu7euz347twq6u (Succeeded)
- Microsoft.OperationalInsights/workspaces /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.OperationalInsights/workspaces/nsphere-law-u7euz347twq6u (Succeeded)
- Microsoft.DocumentDB/databaseAccounts /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.DocumentDB/databaseAccounts/nsphere-cosmos-u7euz347twq6u (Succeeded)
- Microsoft.Search/searchServices /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.Search/searchServices/nsphere-search-u7euz347twq6u (Succeeded)
- Microsoft.KeyVault/vaults /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.KeyVault/vaults/nsphere-kv-u7euz347twq6u (Succeeded)
- Microsoft.EventHub/namespaces /subscriptions/<subscription:bc2c0815>/resourceGroups/rg-neurosphere-g01-smoke-cus2/providers/Microsoft.EventHub/namespaces/nsphere-eh-u7euz347twq6u (Succeeded)

## Steps

- [ok] resource-group-create rg-neurosphere-g01-smoke-cus2
- [ok] what-if 6 change(s)
- [ok] deployment-create Succeeded
- [ok] health 6 resources
- [ok] removal-plan 7 removable, reused untouched
- [ok] resource-group-delete rg-neurosphere-g01-smoke-cus2
- [warning] keyvault-purge:nsphere-kv-u7euz347twq6u blocked by purge protection (retention applies)
