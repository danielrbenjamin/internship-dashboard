
# Security

Report suspected vulnerabilities through GitHub private vulnerability reporting. Send details privately and redact real credentials and candidate data.

The public API allows explicit catalog fields. The owner API uses an Auth0 subject allowlist and expiring server-side sessions. The MCP endpoint independently verifies the Auth0 signing key, issuer, audience, scope and owner subject. Keep the web client secret, API credentials, GitHub token, Codex login, backups and candidate files outside Git. Revoke and rotate any credential accidentally committed, even after removing it from the current tree.

Only import résumé repositories you trust. The renderer disables shell escape and restricts TeX file access, but TeX inputs are executable document code. Treat this app as single-owner software and do not extend compilation to public uploads. The worker sends posting content, résumé text and experience data to the signed-in Codex account only when the owner requests an assessment or edit. Review all proposed changes before compiling.
