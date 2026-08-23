# Local reproduction bundle

This directory identifies the current Constitutional ARI-RQGM working tree
by content, even when it has not yet been committed. It is not a public,
immutable release and must not be cited as a DOI, tag, or archival artifact.

Regenerate the bundle from the repository root:

```bash
python scripts/reproduce_constitutional_rqgm.py
python scripts/reproduce_constitutional_rqgm.py --run focused
python scripts/reproduce_constitutional_rqgm.py --run all
```

The manifest records the Git revision and dirty-tree flag, a SHA-256 digest
over every file under `ari-core/ari` and `ari-core/tests` plus the selected
build and reproduction inputs, the dependency-lock digest, interpreter
details, exact pytest arguments, and hashes of every generated list and log.
`focused-tests.txt` and `full-tests.txt` are the machine-readable collected
test identifiers. `authority-matrix.json` expands the fixed deny-by-default
table into every role × tier × operation × resource decision. A test run adds
`focused-run.log` and/or `full-run.log` and records their result in the
manifest.

Every location recorded here identifies the work, never the machine that
produced it. Absolute paths arrive from three directions the generator does
not control — the interpreter it was launched with, `pip freeze`'s
editable-install lines, and pytest's own output — so they are rewritten on the
way in, before anything is written and therefore before anything is hashed: a
path inside this checkout becomes repo-relative, a module inside an
environment becomes `<env>/site-packages/...`, and anything else becomes
`<outside-repository>`. The generator then refuses to leave a bundle that
still names a home directory, so a leak form nobody anticipated fails the
regeneration instead of being published.

Publication still requires a clean tagged commit, a permanent archive,
locked execution image, and independently accessible CI logs.
