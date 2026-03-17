"""Singularity container operations: build images and run commands via SLURM."""

from __future__ import annotations

from src.slurm import SlurmClient


async def build(client: SlurmClient, arguments: dict) -> dict:
    """Submit a SLURM job that builds a Singularity image from a definition file.

    Returns dict with job_id, output_path, status.
    """
    definition_file = arguments["definition_file"]
    output_path = arguments["output_path"]
    partition = arguments.get("partition", "default")

    # Write the definition content and build the SIF
    script = (
        f"cat << 'DEFEOF' > /tmp/singularity_build_$$.def\n"
        f"{definition_file}\n"
        f"DEFEOF\n"
        f"singularity build {output_path} /tmp/singularity_build_$$.def\n"
        f"rm -f /tmp/singularity_build_$$.def"
    )

    result = await client.submit(
        script=script,
        job_name="singularity_build",
        partition=partition,
        nodes=1,
        walltime="02:00:00",
    )

    return {
        "job_id": result["job_id"],
        "output_path": output_path,
        "status": result["status"],
    }


async def run(client: SlurmClient, arguments: dict) -> dict:
    """Submit a SLURM job that runs a command inside a Singularity container.

    Returns dict with job_id, status.
    """
    image_path = arguments["image_path"]
    command = arguments["command"]
    work_dir = arguments.get("work_dir", ".")
    partition = arguments.get("partition", "default")
    nodes = arguments.get("nodes", 1)
    walltime = arguments.get("walltime", "01:00:00")

    script = f"cd {work_dir}\nsingularity exec {image_path} {command}"

    result = await client.submit(
        script=script,
        job_name="singularity_run",
        partition=partition,
        nodes=nodes,
        walltime=walltime,
    )

    return {
        "job_id": result["job_id"],
        "status": result["status"],
    }


async def pull(client: SlurmClient, arguments: dict) -> dict:
    """Pull a Singularity image from Docker Hub or Sylabs Cloud.

    Returns dict with job_id, output_path, status.
    """
    source = arguments["source"]          # e.g. "docker://nvidia/cuda:12.0-base"
    output_path = str(__import__("pathlib").Path(arguments["output_path"]).expanduser())
    partition = arguments.get("partition", "default")

    script = (
        f"singularity pull --force {output_path} {source} && "
        f"echo PULL_OK: {output_path}"
    )

    result = await client.submit(
        script=script,
        job_name="singularity_pull",
        partition=partition,
        nodes=1,
        walltime="01:00:00",
    )

    return {
        "job_id": result["job_id"],
        "output_path": output_path,
        "source": source,
        "status": result["status"],
    }


async def build_fakeroot(client: SlurmClient, arguments: dict) -> dict:
    """Build a Singularity image on HPC using fakeroot.

    No root privileges required. However, fakeroot must be enabled by the HPC administrator.
    Returns dict with job_id, output_path, status.
    """
    definition_content = arguments["definition_content"]
    output_path = arguments["output_path"]
    partition = arguments.get("partition", "default")
    walltime = arguments.get("walltime", "02:00:00")

    # Write the definition file to a temp file and build
    script = (
        f"TMPDEF=$(mktemp /tmp/singularity_XXXXXX.def)\n"
        f"cat << \'DEFEOF\' > $TMPDEF\n"
        f"{definition_content}\n"
        f"DEFEOF\n"
        f"singularity build --fakeroot {output_path} $TMPDEF\n"
        f"rm -f $TMPDEF\n"
        f"echo BUILD_OK: {output_path}"
    )

    result = await client.submit(
        script=script,
        job_name="singularity_build_fakeroot",
        partition=partition,
        nodes=1,
        walltime=walltime,
    )

    return {
        "job_id": result["job_id"],
        "output_path": output_path,
        "status": result["status"],
    }


async def run_gpu(client: SlurmClient, arguments: dict) -> dict:
    """Run a Singularity container with GPU access enabled (--nv flag).

    Returns dict with job_id, status.
    """
    image_path = arguments["image_path"]
    command = arguments["command"]
    work_dir = arguments.get("work_dir", ".")
    partition = arguments.get("partition", "default")
    nodes = arguments.get("nodes", 1)
    cpus = arguments.get("cpus_per_task", 8)
    gres = arguments.get("gres", "gpu:1")
    walltime = arguments.get("walltime", "01:00:00")
    bind_paths = arguments.get("bind_paths", [])  # list of "host:container" strings

    bind_opt = ""
    if bind_paths:
        bind_opt = "--bind " + ",".join(bind_paths) + " "

    script = (
        f"cd {work_dir}\n"
        f"singularity exec --nv {bind_opt}{image_path} {command}"
    )

    result = await client.submit(
        script=script,
        job_name="singularity_gpu",
        partition=partition,
        nodes=nodes,
        cpus_per_task=cpus,
        gres=gres,
        walltime=walltime,
    )

    return {
        "job_id": result["job_id"],
        "status": result["status"],
    }
