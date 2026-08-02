"""Read-only migration shims for older ARI formats.

``checkpoint`` normalizes historical checkpoint paper and replay inputs while
digesting every consumed file. ``skill_manifest`` converts unversioned package
metadata in memory. Neither module is a runtime registration path; production
discovery accepts canonical manifests only.

The ``v05_to_v07`` package contains the older memory and node-report migration
helpers retained for supported checkpoints.
"""
