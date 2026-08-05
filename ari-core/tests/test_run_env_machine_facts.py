"""The machine facts an audit-by-name will miss, and the ones it must not leak.

WHY THIS FILE EXISTS. Twice in one day the same mistake produced a confident
wrong answer: something was searched for by NAME, was not found under that name,
and was reported absent. It was present. The vendor compiler and both of its
profilers were sitting in one `/opt` directory that no module listed, and an
audit that searched `module avail` concluded the machine had no profiler. It had
two. Separately, one environment variable was moving the same frozen source by
5.9x, and nothing in `module avail`, `lscpu`, or any compiler version string
mentions it.

So the catalogue enumerates directories that LOOK like toolchain installs and
reports what is executable in them, and it reports the page/NUMA state directly.
Both are handed to the agent as data. The failure mode is quiet in both
directions and both directions are pinned here:

  TOO NARROW -- the capture returns nothing, the agent never learns the vendor
  toolchain exists, and every run silently proceeds on the default compiler while
  the catalogue looks well-formed.

  TOO WIDE -- a value that should never leave the machine ends up in a catalogue
  that is written into a node's prompt and its trace. The presence-only design
  for environment variables exists for exactly this: a name tells the agent what
  to `echo` for itself, a value dump would carry API keys and the usernames
  embedded in `PATH` and `LD_LIBRARY_PATH` into every node.

The third property is that no vendor name is hardcoded, which is what keeps this
correct on a machine whose vendor is someone else's.
"""
import pytest

from ari.agent import run_env


# ── enumerating toolchains by shape, not by name ────────────────────────────
def test_a_toolchain_tree_is_found_without_knowing_any_vendor_name(tmp_path, monkeypatch):
    """The whole point: found because it looks like a toolchain, not because we
    knew what to grep for."""
    import glob as real_glob
    tree = tmp_path / "opt" / "SomeVendorTree" / "bin"
    tree.mkdir(parents=True)
    for name in ("nonstandard-cc", "nonstandard-prof", "readme.txt"):
        f = tree / name
        f.write_text("#!/bin/sh\n")
        if not name.endswith(".txt"):
            f.chmod(0o755)

    monkeypatch.setattr(real_glob, "glob",
                        lambda pat: [str(tree)] if pat.endswith("/bin") else [])

    out = run_env._capture_toolchain_dirs()
    listed = {k: v for k, v in out.items() if "SomeVendorTree" in k}
    assert listed, f"a toolchain tree with executables in it was not enumerated: {out}"
    names = next(iter(listed.values()))
    assert "nonstandard-cc" in names and "nonstandard-prof" in names, (
        "the executables in the tree are the answer to 'what compilers and "
        "profilers does this machine have'; missing them is how an audit "
        "concludes a machine has no profiler when it has two")
    assert "readme.txt" not in names, "non-executables are not toolchain entries"


def test_no_vendor_or_tool_name_is_hardcoded_in_the_capture():
    """A hardcoded name makes ARI correct on one machine and wrong elsewhere."""
    import inspect
    src = inspect.getsource(run_env._capture_toolchain_dirs)
    body = src.split('"""', 2)[-1]      # the docstring may cite what was measured
    for name in ("fcc", "fapp", "fipp", "FJSV", "nvhpc", "icc", "xlc", "cray"):
        assert name not in body.lower().replace("_", ""), (
            f"'{name}' is hardcoded in the capture body; the enumeration must "
            f"work by shape so it stays correct on another vendor's machine")


def test_the_capture_is_bounded(tmp_path, monkeypatch):
    """It goes into a prompt, so an unbounded listing is a real cost."""
    import glob as real_glob
    d = tmp_path / "bin"
    d.mkdir()
    for i in range(200):
        f = d / f"tool{i:03d}"
        f.write_text("x")
        f.chmod(0o755)
    monkeypatch.setattr(real_glob, "glob",
                        lambda pat: [str(d)] if pat.endswith("/bin") else [])
    out = run_env._capture_toolchain_dirs(max_dirs=2, max_each=5)
    assert len(out) <= 2
    assert all(len(v) <= 5 for v in out.values())


def test_an_unreadable_directory_does_not_break_the_probe(tmp_path, monkeypatch):
    """Environment capture must never be the reason a run fails to start."""
    import glob as real_glob
    monkeypatch.setattr(real_glob, "glob",
                        lambda pat: ["/nonexistent-toolchain-tree/bin"])
    assert run_env._capture_toolchain_dirs() == {}


# ── the page/NUMA state that is worth 5.9x ──────────────────────────────────
def test_the_memory_system_is_reported_and_is_a_mapping():
    out = run_env._capture_memory_system()
    assert isinstance(out, dict)
    for key in ("transparent_hugepage", "numa_balancing", "large_page_library"):
        assert key in out, (
            f"{key} is part of what decides whether two measurements are "
            f"comparable; absent from the record it cannot be checked later")


def test_a_large_page_library_is_found_by_shape(tmp_path, monkeypatch):
    """Its presence is what makes one environment variable worth 5.9x."""
    import glob as real_glob
    lib = tmp_path / "opt" / "vendor" / "mmm" / "lib64" / "libmpg.so.1"
    lib.parent.mkdir(parents=True)
    lib.write_text("")
    monkeypatch.setattr(real_glob, "glob",
                        lambda pat: [str(lib)] if "libmpg" in pat else [])
    assert "libmpg" in (run_env._capture_memory_system()["large_page_library"] or "")


def test_the_probe_survives_a_machine_without_any_of_it(monkeypatch):
    """Not every machine has /proc/meminfo or a large-page library."""
    import glob as real_glob
    monkeypatch.setattr(real_glob, "glob", lambda pat: [])
    monkeypatch.setattr(run_env.Path, "is_file", lambda self: False)
    out = run_env._capture_memory_system()
    assert out.get("large_page_library") is None


# ── both reach the agent ────────────────────────────────────────────────────
@pytest.mark.parametrize("fn", ["_capture_toolchain_dirs", "_capture_memory_system"])
def test_the_capture_is_wired_into_capture_env(fn):
    """A probe nobody calls leaves the agent exactly as uninformed as before."""
    import inspect
    assert fn in inspect.getsource(run_env.capture_env), (
        f"{fn} is not called from capture_env, so nothing it learns reaches a "
        f"node")


# ── presence, never value ───────────────────────────────────────────────────
def test_the_variable_worth_5_9x_is_on_the_allowlist():
    """Its presence has to be visible or the axis is invisible to the agent."""
    assert "XOS_MMM_L_PAGING_POLICY" in run_env._ENV_ALLOWLIST


def test_the_probe_emits_variable_names_and_never_their_values():
    """A value dump would carry API keys and the username inside PATH."""
    import inspect
    src = inspect.getsource(run_env)
    assert 'echo "$v"' in src, (
        "the allowlist loop must echo the NAME. Echoing the value would put "
        "credentials and the operator's home path into every node's prompt and "
        "trace; the agent echoes the specific value it needs on demand instead.")
    assert 'echo "$_val"' not in src


@pytest.mark.parametrize("var", [v for v in run_env._ENV_ALLOWLIST])
def test_no_allowlisted_name_is_itself_a_secret(var):
    """The names ARE published, so a name must not identify a credential."""
    assert not any(s in var.upper() for s in
                   ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")), (
        f"{var} is emitted by name into the catalogue; a name like this tells a "
        f"reader a credential exists and what it is called")


def test_the_operator_home_path_is_masked_out_of_the_catalogue(tmp_path, monkeypatch):
    """Paths go into the prompt; a home path identifies the operator."""
    import glob as real_glob
    home = str(tmp_path / "someuser")
    d = tmp_path / "someuser" / "toolchain" / "bin"
    d.mkdir(parents=True)
    (d / "cc").write_text("x")
    (d / "cc").chmod(0o755)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setattr(real_glob, "glob",
                        lambda pat: [str(d)] if pat.endswith("/bin") else [])
    out = run_env._capture_toolchain_dirs()
    assert out, "nothing was captured, so the masking assertion below is vacuous"
    assert not any(home in k for k in out), (
        f"an operator home path reached the catalogue: {list(out)}")
    assert any(k.startswith("~") for k in out), (
        f"the home prefix must be collapsed to ~, not merely absent: {list(out)}")
