### Added
- PRP-62: read-only `aws-bedrock` reference connector (Bedrock inventory, CloudWatch usage, Cost Explorer daily cost, metadata only, Commercial AWS only) with a least-privilege IAM policy and a live-check script that refuses without `NS_LIVE_APPROVED=1`. Library only: no stored configuration or worker role yet (PR #317).
