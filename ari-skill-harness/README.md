# ARI Harness query Provider

This default-off MCP package exposes read-only Harness catalog, Verification
Contract, and Attestation queries plus non-authoritative auxiliary-verification
requests. It cannot register/promote/revoke Harnesses, choose or rewrite a
Harness Lock, change a tolerance/oracle/dataset/container, execute the Fixed
Verifier, or force a verdict.

Authoritative resolution and verification remain inside `ari.assurance` and
the trusted RQGM runtime, outside agent tool choice.
