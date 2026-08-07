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
    from ari.assurance.drivers.upstream import UpstreamCLIDriver

    drivers = (
        NativeHPCDriver(),
        InspectDriver(),
        HarborDriver(),
        PaperBenchDriver(),
        UpstreamCLIDriver(),
    )
    return {driver.revision: driver for driver in drivers}


__all__ = [
    "builtin_driver_map",
]
