---
sources:
  - path: CONTRIBUTING.md
    role: doc
  - path: CHANGELOG.md
    role: doc
  - path: LICENSE
    role: doc
  - path: SECURITY.md
    role: doc
  - path: ari-skill-transform/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# About ARI

Project meta — the policies and references that govern the project as a whole,
rather than any single feature.

## Policies & references

| Document | What it covers |
|---|---|
| [Release & versioning policy](release_policy.md) | SemVer interpretation, the public surface, support windows, deprecation lifecycle, and the release checklist (including the docs gates). |
| [Compatibility & support](compatibility.md) | Supported Python, the Letta memory backend, and LLM backends. |
| [Contributing](../../CONTRIBUTING.md) | Software-engineering discipline, the layered architecture, the public-API rule, and the deprecation process. |
| [Changelog](../../CHANGELOG.md) | Per-release notes (Added / Changed / Fixed / Deprecated / Removed / Security). |
| [Security policy](../../SECURITY.md) | How to report a vulnerability and which versions receive fixes. |

## Licensing

The repository itself ships a root [`LICENSE`](../../LICENSE) — the MIT
License, "Copyright (c) 2026 ARI contributors".

Published artifacts are licensed **separately, per artifact**. When you publish
an Experiment Artifact Repository (EAR), its `ear/publish.yaml` declares an SPDX
`license` (MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0, including the
`-only` / `-or-later` spellings / CC-BY-4.0) and `generate_ear` writes the
matching `LICENSE` into the bundle — but only when the bundle does not already
carry one, and an SPDX id outside that set produces no `LICENSE` file at all.
See
[Configuration → EAR Curation](../reference/configuration.md#ear-curation-ear-publish-yaml-—-v0-7-0).

---

See also: [Documentation index](../README.md) ·
[Release policy](release_policy.md) · [Compatibility](compatibility.md)
