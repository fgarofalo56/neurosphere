### Security
- The frontend edge image moves to `nginxinc/nginx-unprivileged:mainline-alpine` (nginx 1.31.7),
  which fixes six High nginx advisories present in the stable 1.30.6 base; the time-boxed scanner
  exceptions for them are removed (PR #410).
