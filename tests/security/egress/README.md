# Government no-Commercial-egress tests (PRP-20 item 3)

Result label: **static and compose only; in-cluster proof OPEN (no Government subscription, D7).**

- `test_allowlist_no_commercial.py` (offline, runs in CI): scans the rendered Government Helm
  output, `sovereign-profile.yaml`, `values-government.yaml` and the compiled Government Bicep
  parameters against `commercial_deny_corpus.txt`, and checks the rendered NetworkPolicies keep
  egress default-deny with only private RFC1918 `ipBlock` allows. Helm/az parts skip only when
  the executable is missing.
- `test_compose_egress_blocked.py` (`integration`, needs Docker): from `egress-probe` on the
  `internal: true` network, each concrete corpus host fails to connect on 443, with a positive
  control that an emulator is reachable.

The in-cluster half (a pod in a real Government AKS cluster failing to reach Commercial endpoints)
is OPEN. Nothing here claims FedRAMP authorization, an ATO or compliance parity.
