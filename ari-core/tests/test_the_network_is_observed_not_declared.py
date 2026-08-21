"""The network condition a launch ran under, recorded rather than restated.

WHAT WAS THERE BEFORE. ``network_isolation`` in a registration bundle read
"proved" whenever every execution's request had said ``network: deny``, and
every layer beneath it restated that same declaration: ``execution.py`` computes
``network_report`` as "isolated" if the request denied, so the runner's check
that the two agree compares a declaration with itself. The executor does pass
``--network none`` and the runtime does enforce it -- but no record anywhere was
of the CONDITION. A run that was not isolated could not have said so.

WHAT THESE HOLD. That ``network_record`` answers differently in the two cases,
because a record that cannot distinguish them is a restatement with extra steps.
One of them runs the probe inside a real empty network namespace, so the
positive case is observed and not mocked.

MEASURED while writing this, and the reason the probe reads /proc and not /sys:
inside ``unshare -rn`` the connect probe answered ENETUNREACH while
``/sys/class/net`` still listed all ten of the host's interfaces. sysfs shows
whatever sysfs was mounted; procfs's net directory is per-namespace by
construction. A probe reading sysfs would have called an isolated namespace open.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ari.assurance.native_perf_common import SANDBOX_RECORD_KEYS, sandbox_record
from ari.assurance.sandbox import network_record

ARI_CORE = Path(__file__).resolve().parents[1]


def test_the_record_reports_the_condition_it_is_in() -> None:
    """Whatever this host is, the record has to be about it rather than typed."""
    record = network_record()
    assert set(record) >= {"network_isolation", "network_probe",
                           "interfaces_beyond_loopback"}
    assert isinstance(record["network_isolation"], bool)
    # The two facts must agree with the verdict, in both directions.
    if record["network_isolation"]:
        assert record["interfaces_beyond_loopback"] == 0
        assert record["network_probe"] in {"ENETUNREACH", "EHOSTUNREACH", "ENETDOWN"}
    else:
        assert (record["interfaces_beyond_loopback"] != 0
                or record["network_probe"] not in
                {"ENETUNREACH", "EHOSTUNREACH", "ENETDOWN"})


def test_silence_is_not_isolation() -> None:
    """A timeout means a packet left and nobody answered, which is a firewall or
    a quiet network -- not an absent one. Reading it as isolation is how a probe
    turns into the declaration it replaced."""
    import ari.assurance.sandbox as sandbox

    assert "timeout" not in {"ENETUNREACH", "EHOSTUNREACH", "ENETDOWN"}
    source = (Path(sandbox.__file__)).read_text(encoding="utf-8")
    assert 'probe = "timeout"' in source
    assert "unreachable = probe in {" in source


def test_every_reported_key_is_publishable() -> None:
    """The record goes into a digested, published report, so what it may carry
    is an allowlist -- and the observation must not have widened it by
    accident."""
    for key in network_record():
        assert key in SANDBOX_RECORD_KEYS, (
            f"{key!r} reaches a published report without being on the allowlist")
    assert "interfaces" not in network_record(), (
        "interface names are host configuration; only the count is reported")


@pytest.mark.skipif(shutil.which("unshare") is None,
                    reason="no unshare(1) to build an empty network namespace")
def test_an_empty_namespace_is_observed_as_isolated() -> None:
    """THE POSITIVE CASE, observed rather than mocked.

    Skipped where unprivileged user namespaces are unavailable -- reported as a
    skip and not as a pass, because a test that silently stops checking the one
    case it exists for is the defect this file is about.
    """
    probe = subprocess.run(
        ["unshare", "-rn", sys.executable, "-c",
         "import sys, json; sys.path.insert(0, %r);"
         " from ari.assurance.sandbox import network_record;"
         " print(json.dumps(network_record()))" % str(ARI_CORE)],
        capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        pytest.skip(f"could not enter a network namespace: "
                    f"{probe.stderr.strip()[-160:]}")
    record = json.loads(probe.stdout.strip().splitlines()[-1])
    assert record["network_isolation"] is True, record
    assert record["interfaces_beyond_loopback"] == 0, record
    assert record["network_probe"] == "ENETUNREACH", record
    assert record["network_mechanism"] == "network-namespace"


def test_the_publishable_view_keeps_the_observation() -> None:
    """sandbox_record filters by allowlist; the network keys must survive it."""
    kept = sandbox_record({**network_record(), "writable_root": "/tmp/x"})
    assert "writable_root" not in kept
    assert "network_isolation" in kept and "network_probe" in kept
