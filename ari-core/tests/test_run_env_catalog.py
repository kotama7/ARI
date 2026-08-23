"""Node-aware heterogeneous environment catalog (multi-node HPC).

ARI changes behaviour by launch node:
  - login  -> recursively srun-probe each ARI_PROBE_PARTITIONS partition
  - compute/local -> report only the local node's env
Cluster-agnostic: the probe dumps raw `module avail`/`nvidia-smi` as data; no
compiler/module name is hardcoded. Validated end-to-end on the real cluster
(login x86_64 probed an aarch64 A64FX partition — a genuinely heterogeneous node).
"""
import ari.agent.run_env as re_mod
from ari.agent.run_env import (
    _parse_probe_output,
    build_env_catalog,
    detect_node_role,
)

_SAMPLE = """###ARCH###
aarch64
###CPU###
A64FX
###THREADS###
48
###MEM_KB###
33554432
###COMPILERS###
gcc: gcc (GCC) 11.5.0
mpicc: gcc (GCC) 11.5.0
nvcc: Cuda compilation tools, release 12.4
###GPU###
NVIDIA A100-SXM4-80GB, 81920 MiB
###ENV_PRESENT###
MODULEPATH
CUDA_HOME
OMP_NUM_THREADS
###MODULES###
--- /apps/modulefiles ---
nvhpc/24.3
###END###"""


def test_parse_probe_output():
    d = _parse_probe_output(_SAMPLE)
    assert d["arch"] == "aarch64"
    assert d["cpu_model"] == "A64FX"
    assert d["threads"] == 48
    assert d["mem_total_kb"] == 33554432
    assert set(d["compilers"]) == {"gcc", "mpicc", "nvcc"}
    assert d["gpus"] == ["NVIDIA A100-SXM4-80GB, 81920 MiB"]
    assert d["env_present"] == ["MODULEPATH", "CUDA_HOME", "OMP_NUM_THREADS"]
    assert "nvhpc/24.3" in d["modules_avail"]


def test_env_present_is_names_only_and_excludes_secrets(monkeypatch):
    """SECURITY: the probe reports only the NAMES of set allowlisted toolchain
    vars — never a value (would leak API keys / usernames in PATH) and never a
    non-allowlisted name (would surface *_API_KEY). The agent echoes values on
    demand."""
    monkeypatch.setenv("ARI_FAKE_API_KEY", "sk-SECRETVALUE123")
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.setenv("MODULEPATH", "/home/users/alice/apps")
    e = re_mod.local_env()
    present = e.get("env_present", [])
    assert "OMP_NUM_THREADS" in present and "MODULEPATH" in present  # allowlisted
    assert "ARI_FAKE_API_KEY" not in present                        # secret NAME hidden
    import json
    blob = json.dumps(e)
    assert "SECRETVALUE123" not in blob and "sk-" not in blob       # no VALUE dumped
    assert "/home/users/alice" not in blob                          # no username path


def test_squeeze_strips_padding_but_keeps_single_spaces():
    """Layout padding in a raw dump is collapsed, but SINGLE spaces survive —
    they separate the ISA tokens on the lscpu ``Flags:`` line that the agent
    mines for AVX-512. Blank lines and trailing spaces go."""
    from ari.agent.run_env import _squeeze
    raw = ("Architecture:                    x86_64\n"
           "\n"
           "Flags:   fpu vme avx2 avx512f avx512dq   \n"
           "   \n"
           "CPU(s):                          64\n")
    out = _squeeze(raw)
    assert "Architecture: x86_64" in out            # 26-space padding collapsed
    assert "CPU(s): 64" in out
    assert "\n\n" not in out                         # blank lines dropped
    assert not any(ln != ln.rstrip() for ln in out.splitlines())  # no trailing ws
    # the flags stay individually parseable — this is the load-bearing property
    flags = next(ln for ln in out.splitlines() if ln.startswith("Flags:")).split()
    assert "avx512f" in flags and "avx2" in flags and "avx512dq" in flags


def test_squeeze_applied_to_dumps_before_the_cap():
    """The squeeze runs BEFORE the size caps, so more real content survives a
    truncation (and the payload shrinks ~20%)."""
    from ari.agent.run_env import _parse_probe_output
    pad = " " * 30
    sample = ("###ARCH###\nx86_64\n"
              "###CPU_DETAIL###\n" + "".join(f"Field{i}:{pad}value{i}\n\n" for i in range(20)) +
              "###MODULES###\nmod/1.0" + pad + "mod/2.0\n"
              "###END###")
    d = _parse_probe_output(sample)
    assert "Field0: value0" in d["cpu_detail"]        # padding collapsed
    assert "\n\n" not in d["cpu_detail"]              # blank lines dropped
    assert d["modules_avail"] == "mod/1.0 mod/2.0"    # both modules survive, squeezed
    # the squeezed dump is materially smaller than the raw one
    assert len(d["cpu_detail"]) < len(pad) * 20


def test_parse_probe_output_masks_home_username(monkeypatch):
    """SECURITY: a probe value that carries the user's home path (e.g. a broken
    conda mpicc wrapper echoing its full path) is collapsed to ``~`` so the env
    catalog never leaks a username. Covers BOTH the $HOME mount and an alternate
    mount of the same home (…/<user>/…)."""
    import json
    monkeypatch.setenv("HOME", "/home/users/alice")
    monkeypatch.setenv("USER", "alice")
    sample = (
        "###ARCH###\nx86_64\n"
        "###COMPILERS###\n"
        "gcc: gcc (GCC) 11.5.0\n"
        "mpicc: /home/users/alice/miniconda3/bin/mpicc: line 345: cc not found\n"
        "###MODULES###\n"
        "/scratch/fs0/home/users/alice/apps/modulefiles\n"   # alternate mount
        "###END###"
    )
    d = _parse_probe_output(sample)
    blob = json.dumps(d)
    assert "alice" not in blob                                  # no username anywhere
    assert "~/miniconda3/bin/mpicc" in d["compilers"]["mpicc"]  # $HOME mount -> ~
    assert "~/apps/modulefiles" in d["modules_avail"]           # alt mount -> ~


def test_parse_probe_output_incomplete_returns_empty():
    # No ###END### marker => truncated/failed probe => empty (not partial junk).
    assert _parse_probe_output("###ARCH###\nx86_64\n") == {}
    assert _parse_probe_output("") == {}


def test_detect_node_role_compute(monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    assert detect_node_role() == "compute"


def test_detect_node_role_login(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    monkeypatch.setattr(re_mod.shutil if hasattr(re_mod, "shutil") else __import__("shutil"),
                        "which", lambda n: "/usr/bin/srun" if n in ("srun", "sinfo") else None)
    assert detect_node_role() == "login"


def test_detect_node_role_local(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert detect_node_role() == "local"


def test_build_catalog_compute_is_local_only(monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "999")
    monkeypatch.setenv("SLURM_JOB_PARTITION", "gpu")
    monkeypatch.setattr(re_mod, "local_env", lambda: {"arch": "x86_64"})
    c = build_env_catalog()
    assert c["role"] == "compute"
    assert list(c["nodes"]) == ["gpu"]          # only this node, labelled by partition
    assert c["nodes"]["gpu"] == {"arch": "x86_64"}


def test_build_catalog_login_probes_each_partition(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/srun")
    monkeypatch.setattr(re_mod, "local_env", lambda: {"arch": "x86_64", "role_note": "login"})
    monkeypatch.setenv("ARI_PROBE_PARTITIONS", "cpu, gpu ,arm")
    monkeypatch.setenv("ARI_PROBE_TIMEOUT_S", "30")
    # mock the srun probe: gpu reachable, others skipped
    def _fake_probe(part, timeout_s):
        assert timeout_s == 30
        return {"arch": "aarch64" if part == "arm" else "x86_64"} if part in ("gpu", "arm") else None
    monkeypatch.setattr(re_mod, "probe_partition_env", _fake_probe)
    c = build_env_catalog()
    assert c["role"] == "login"
    assert c["probed_partitions"] == ["cpu", "gpu", "arm"]
    assert c["nodes"]["local (login node)"]["arch"] == "x86_64"  # ALWAYS the login node itself
    assert c["nodes"]["cpu"].get("status")          # skipped
    assert c["nodes"]["gpu"] == {"arch": "x86_64"}
    assert c["nodes"]["arm"] == {"arch": "aarch64"}  # heterogeneous capture


def test_skipped_partition_is_not_cached(monkeypatch, tmp_path):
    """A ``status: skipped`` entry is a TRANSIENT failure (queue wait / busy).
    The cache has no TTL and is returned verbatim, so persisting a placeholder
    would keep that partition dead for the whole run. Nothing is cached until
    every node was really probed."""
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/srun")
    monkeypatch.setattr(re_mod, "local_env", lambda: {"arch": "x86_64"})
    monkeypatch.setenv("ARI_PROBE_PARTITIONS", "cpu,gpu")
    # gpu reachable, cpu times out this round
    monkeypatch.setattr(re_mod, "probe_partition_env",
                        lambda p, t: {"arch": "x86_64"} if p == "gpu" else None)
    c = re_mod.build_env_catalog(checkpoint_dir=tmp_path)
    assert c["nodes"]["cpu"].get("status")            # surfaced to the caller
    assert not (tmp_path / "heterogeneous_env.json").exists(), \
        "a catalog containing a skipped node must NOT be cached"

    # once every partition probes cleanly, the catalog IS cached
    monkeypatch.setattr(re_mod, "probe_partition_env", lambda p, t: {"arch": "x86_64"})
    re_mod.build_env_catalog(checkpoint_dir=tmp_path)
    assert (tmp_path / "heterogeneous_env.json").exists()


def test_catalog_is_cached_even_with_no_partitions(monkeypatch, tmp_path):
    """Regression: the cache was gated on ``and parts``, so a login node with no
    configured partitions (the common case) re-ran the local probe on every call
    and never cached. The cache saves the PROBE, not the payload."""
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    monkeypatch.delenv("ARI_PROBE_PARTITIONS", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/srun")
    _calls = []

    def _probe_once():
        _calls.append(1)
        return {"arch": "x86_64"}

    monkeypatch.setattr(re_mod, "local_env", _probe_once)
    c1 = re_mod.build_env_catalog(checkpoint_dir=tmp_path)
    assert (tmp_path / "heterogeneous_env.json").exists()
    c2 = re_mod.build_env_catalog(checkpoint_dir=tmp_path)   # cache hit
    assert len(_calls) == 1, "second call must read the cache, not re-probe"
    assert c2["nodes"] == c1["nodes"]


def test_build_catalog_login_no_partitions_still_returns_local(monkeypatch):
    """Regression: on a login node with no ARI_PROBE_PARTITIONS, the catalog is
    NOT empty — it still reports the login node's own env (the agent may run
    here directly)."""
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    monkeypatch.delenv("SLURM_JOB_PARTITION", raising=False)
    monkeypatch.delenv("ARI_PROBE_PARTITIONS", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/srun")
    monkeypatch.setattr(re_mod, "local_env", lambda: {"arch": "x86_64", "compilers": {"gcc": "11.5"}})
    c = build_env_catalog()
    assert c["role"] == "login"
    assert c["probed_partitions"] == []
    assert c["nodes"]["local (login node)"] == {"arch": "x86_64", "compilers": {"gcc": "11.5"}}
    assert len(c["nodes"]) == 1  # non-empty even with no partitions
