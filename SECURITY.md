# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public
issue or pull request for them.

Use GitHub's private vulnerability reporting: on the repository's **Security**
tab, choose **Report a vulnerability**. This opens a private advisory visible
only to the maintainers.

Please include:

- a description of the issue and its impact,
- the version / commit you observed it on,
- minimal steps to reproduce, and
- any suggested remediation.

We aim to acknowledge a report within a few working days and to keep you updated
as we investigate. Please give us a reasonable window to release a fix before
any public disclosure.

## Supported versions

Security and critical fixes follow the project's support policy: the latest
minor is actively maintained, and the previous minor receives security and
critical bug fixes for six months after the next minor ships. Older minors are
out of support. See
[`docs/about/release_policy.md`](docs/about/release_policy.md) for the full
policy and the public-surface definition.

## Operational notes for users

ARI executes LLM-generated code and runs real experiments on your hardware
(locally, or via SLURM/containers). Treat that the way you would any code
execution system:

- **Credentials** live in `.env` files or environment variables, never in
  `settings.json`. Keep `.env` out of version control and out of published
  artifacts — EAR curation enforces a deny list (`.env*`, `secrets/**`,
  `*.pem`, `*.key`, `id_rsa`, `id_ed25519`) so secrets are not bundled.
- **Checkpoints from untrusted sources** may contain arbitrary `reproduce.sh`
  and experiment code. Reproducibility runs are sandboxed
  (docker / apptainer / singularity / SLURM), but review a checkpoint before
  running it on infrastructure you care about.
- **The dashboard** binds to `127.0.0.1` and is unauthenticated by design. Do
  not expose it directly to a network; put it behind a reverse proxy with
  authentication if you must.

## Scope

This policy covers `ari-core` and the bundled `ari-skill-*` packages. Vendored
third-party code (e.g. `vendor/paperbench`, VirSci) should be reported upstream
when the issue originates there, though we are happy to help coordinate.
