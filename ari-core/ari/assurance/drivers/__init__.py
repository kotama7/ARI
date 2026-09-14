"""Lazy reviewed-driver construction for an immutable Harness lock.

The package initializer intentionally imports no driver implementation.  In
particular, the untrusted native candidate host must not load oracle modules
merely by importing ``ari.assurance.drivers.shared_library``.
"""


def builtin_driver_map() -> dict[str, object]:
    """Runtime driver map; catalog admission still controls reachability."""

    from ari.assurance.drivers.harbor import HarborDriver
    from ari.assurance.drivers.inspect import InspectDriver
    from ari.assurance.drivers.native import NativeHPCDriver
    from ari.assurance.drivers.paperbench import PaperBenchDriver
    from ari.assurance.drivers.perf import NativePerfDriver
    from ari.assurance.drivers.problem_correctness import ProblemCorrectnessDriver
    from ari.assurance.drivers.upstream import UpstreamCLIDriver

    drivers = (
        NativeHPCDriver(),
        # Decides performance-regression, the property the vocabulary reserved
        # and six knowledge-skill import profiles require. No manifest names it yet.
        NativePerfDriver(),
        # Decides numerical-equivalence and interface-conformance for a candidate
        # submitted to a PINNED PROBLEM, against that problem's own header rather
        # than the ARI-native ABI. Both NativeHPCDriver and this one name the
        # contract ``gemm-c-abi/v1``; they are contracts with different things,
        # and a run that reached the wrong one read 33/33 missing-symbol failures
        # as a verdict about its candidate.
        ProblemCorrectnessDriver(),
        InspectDriver(),
        HarborDriver(),
        PaperBenchDriver(),
        UpstreamCLIDriver(),
    )
    return {driver.revision: driver for driver in drivers}


__all__ = [
    "builtin_driver_map",
]
