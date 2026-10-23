# Threat model (top 5)

| Threat | Mitigation |
|---|---|
| PR code forges results or reads AWS data | Probe tasks have no task role; results travel via the runner's own log stream |
| Network exposure of probe tasks | Security group: zero inbound, outbound 443 only |
| Static AWS keys in CI | GitHub OIDC, trust policy scoped to the repository |
| Runaway cost | Task timeouts, max_probes, per-PR concurrency, SSM kill switch, reaper, budget alert |
| Forked PRs running untrusted code with secrets | Gate runs only for same-repository PRs |
