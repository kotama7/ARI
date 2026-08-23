"""The environment probe must descend a HIERARCHICAL module tree.

A single `module avail` lists only what the current MODULEPATH exposes. Where the
top level is a set of entry modules and the real toolchains appear only after one
is loaded, a flat listing can show no compiler at all while several are
installed — and the agent then plans against a toolchain it believes does not
exist. `module spider` would flatten it in one call but is Lmod-only.

No site-specific module, partition or host name appears in this file: the
fixtures below are synthetic, and the assertions are about the MECHANISM.
"""
import re

from ari.agent.run_env import _ENV_ALLOWLIST  # noqa: F401  (import sanity)
from ari.agent import run_env


def _probe_script() -> str:
    src = [v for k, v in vars(run_env).items()
           if isinstance(v, str) and "###MODULES###" in v]
    assert src, "the probe script is no longer discoverable in run_env"
    return src[0]


def test_probe_descends_into_loaded_modules():
    s = _probe_script()
    assert "module load" in s, "the probe never loads an entry module"
    assert "comm -13" in s, "the probe does not diff against the flat listing"


def test_probe_loads_only_in_a_subshell():
    """Loading for real would change the toolchain seen by everything after it.

    The probe describes the node; it must not reconfigure it.
    """
    s = _probe_script()
    m = re.search(r"\(module load [^)]*\)", s)
    assert m, "module load is not wrapped in a subshell"


def test_probe_skips_the_modules_packages_own_pseudo_modules():
    """dot/null/modules/... are Environment Modules internals, not site names.

    They reveal nothing when loaded and each one otherwise emits an empty
    section, crowding out the sections that carry the actual toolchains.
    """
    s = _probe_script()
    for internal in ("dot", "null", "modules", "module-info"):
        assert internal in s, f"{internal} is not filtered out"


def test_probe_filters_the_avail_legend():
    """`Key:` and the dashed rules are avail's legend, not module names."""
    s = _probe_script()
    assert "Key" in s and "_legend" in s


def test_catalog_cap_leaves_room_for_the_second_tier():
    """The second tier is where the compilers are; it must not be the part cut."""
    src = open(run_env.__file__).read()
    m = re.search(r'env\["modules_avail"\] = mod\[:(\d+)\]', src)
    assert m, "the modules_avail cap moved"
    assert int(m.group(1)) >= 16000, (
        "the cap is too small for a hierarchical tree: the flat listing alone "
        "can fill 8000 chars, which is exactly how the toolchain sections came "
        "to be truncated away")
