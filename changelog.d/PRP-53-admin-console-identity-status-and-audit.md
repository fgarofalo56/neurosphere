### Added
- PRP-53: the Admin workspace is a real console. `/admin/identity` manages principals, role assignments, domain memberships, resource grants and revocation; `/admin/domains` lists, creates and retires domains; `/admin/system` shows component state, the first-run checklist and stored-setting sources; `/admin/audit` searches, pages and exports audit records with a denials tab and SIEM status. Every write goes through the confirm dialog and the API decides access.

### Changed
- PRP-53: `/workspaces/admin` shows the console landing instead of the placeholder text.
