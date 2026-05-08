"""Migration shims for older ARI checkpoint formats (Phase 5).

Sub-packages here host code that ARI keeps around purely so existing
checkpoints created on older releases stay readable.  The plan
(REFACTORING.md §8) is to keep new feature code free of v0.5 / v0.6
branching by funnelling that branching through this package and
shipping thin re-exports at the historical import paths.
"""
