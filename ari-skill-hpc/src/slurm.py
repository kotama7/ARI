"""SLURM operations: submit, status, cancel jobs via local subprocess or remote SSH."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass, field


@dataclass
class RemoteConfig:
    """SSH connection configuration for remote mode."""

    hostname: str
    username: str
    port: int = 22
    key_filename: str | None = None
    password: str | None = None


@dataclass
class SlurmClient:
    """
    SLURM client supporting both local (subprocess) and remote (SSH/paramiko) execution.

    mode="local" -> runs sbatch/squeue/scancel directly via subprocess
    mode="remote" -> runs via paramiko SSH
    """

    mode: str = "local"
    remote_config: RemoteConfig | None = None
    _ssh_client: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode == "remote" and self.remote_config is None:
            raise ValueError("remote_config is required for remote mode")

    # ── command execution ──────────────────────────────────────────

    async def _run(self, cmd: str) -> tuple[str, str, int]:
        """Run a shell command and return (stdout, stderr, returncode)."""
        if self.mode == "local":
            return await self._run_local(cmd)
        return await self._run_remote(cmd)

    async def _run_local(self, cmd: str) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode().strip(), stderr.decode().strip(), proc.returncode or 0

    async def _run_remote(self, cmd: str) -> tuple[str, str, int]:
        import paramiko  # lazy import

        loop = asyncio.get_running_loop()

        def _exec() -> tuple[str, str, int]:
            if self._ssh_client is None:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                cfg = self.remote_config
                connect_kwargs: dict = {
                    "hostname": cfg.hostname,
                    "port": cfg.port,
                    "username": cfg.username,
                }
                if cfg.key_filename:
                    connect_kwargs["key_filename"] = cfg.key_filename
                if cfg.password:
                    connect_kwargs["password"] = cfg.password
                client.connect(**connect_kwargs)
                self._ssh_client = client

            _, o_stdout, o_stderr = self._ssh_client.exec_command(cmd)
            exit_status = o_stdout.channel.recv_exit_status()
            return (
                o_stdout.read().decode().strip(),
                o_stderr.read().decode().strip(),
                exit_status,
            )

        return await loop.run_in_executor(None, _exec)

    # ── public API ─────────────────────────────────────────────────

    async def submit(self, script: str, **kwargs: object) -> dict:
        """Submit a SLURM batch job.

        Returns dict with job_id, status, message.
        """
        # LLM may pass \n as a literal string → convert to actual newlines
        script = script.replace("\\n", "\n").replace("\\t", "\t")

        # Remove #SBATCH --account / -A if not applicable to this cluster
        import re as _re_acc
        script = _re_acc.sub(r"#SBATCH\s+(?:--account[=\s]|-A\s*)\S+[^\n]*\n?", "", script)

        # Strip LLM-generated #SBATCH --partition= lines from the script body.
        # The correct partition is always set via header_lines (from kwargs or auto-detect).
        # This avoids the bug where _fix_partition could write an empty partition
        # when SLURM_VALID_PARTITIONS / SLURM_DEFAULT_PARTITION are unset.
        import re as _re_part
        script = _re_part.sub(r"#SBATCH\s+--partition=\S*\n?", "", script)

        job_name = kwargs.get("job_name", "mcp_job")
        # Auto-determine partition
        import os as _os, subprocess as _sp
        env_default = _os.environ.get("SLURM_DEFAULT_PARTITION", "")
        _env_valid2 = _os.environ.get("SLURM_VALID_PARTITIONS", "")
        valid_partitions = set(_env_valid2.split(",")) if _env_valid2 else set()

        def _auto_partition() -> str:
            """Retrieve available partitions via sinfo and return the first one."""
            try:
                result = _sp.run(
                    ["sinfo", "--noheader", "--format=%P"],
                    capture_output=True, text=True, timeout=5
                )
                parts = [p.rstrip("*") for p in result.stdout.split() if p.strip()]
                if valid_partitions:
                    parts = [p for p in parts if p in valid_partitions]
                return parts[0] if parts else ""
            except Exception:
                return ""

        _sinfo_available = []
        try:
            import subprocess as _sp2
            _r = _sp2.run(["sinfo","--noheader","--format=%P"], capture_output=True, text=True, timeout=5)
            _sinfo_available = [p.rstrip("*") for p in _r.stdout.split() if p.strip()]
        except Exception:
            pass
        default_partition = env_default or (_sinfo_available[0] if _sinfo_available else "")
        partition = kwargs.get("partition", default_partition) or default_partition
        # Fallback to auto-detected value if LLM specified an invalid partition
        if _sinfo_available and partition not in _sinfo_available:
            partition = default_partition
        elif valid_partitions and partition not in valid_partitions:
            partition = default_partition
        nodes = kwargs.get("nodes", 1)
        walltime = kwargs.get("walltime", "01:00:00")
        account = kwargs.get("account")
        cpus_per_task = kwargs.get("cpus_per_task") or os.environ.get("ARI_SLURM_CPUS")
        memory_gb = kwargs.get("memory_gb") or os.environ.get("ARI_SLURM_MEM_GB")
        gres = kwargs.get("gres")  # e.g. "gpu:1"
        # Fallback: construct gres from ARI_SLURM_GPUS env var if not explicitly provided
        if not gres:
            _env_gpus = os.environ.get("ARI_SLURM_GPUS")
            if _env_gpus and int(_env_gpus) > 0:
                gres = f"gpu:{_env_gpus}"

        import os as _os
        log_dir = _os.environ.get("SLURM_LOG_DIR", "")
        header_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --partition={partition}",
            f"#SBATCH --nodes={nodes}",
            f"#SBATCH --time={walltime}",
        ]
        if cpus_per_task:
            header_lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")
        if memory_gb:
            header_lines.append(f"#SBATCH --mem={memory_gb}G")
        if gres:
            header_lines.append(f"#SBATCH --gres={gres}")
        if log_dir:
            header_lines.append(f"#SBATCH --output={log_dir}/slurm_job_%j.out")
            header_lines.append(f"#SBATCH --error={log_dir}/slurm_job_%j.out")
        # account flag may not be valid on all clusters; silently ignore if passed
        # if account: header_lines.append(f"#SBATCH --account={account}")
        work_dir = kwargs.get("work_dir")
        if work_dir:
            header_lines.append(f"#SBATCH -D {work_dir}")

        # Normalize all LLM-generated chdir variants to #SBATCH -D
        # LLM writes: --work-dir=, --workdir=, --chdir=, -D
        chdir_match = re.search(r"#SBATCH\s+(?:--work-dir=|--workdir=|--work_dir=|--chdir=|-D\s+)(\S+)", script)
        if chdir_match and not work_dir:
            work_dir = chdir_match.group(1)
        # Strip all LLM-generated dir directives (we add -D via header)
        script = re.sub(r"#SBATCH\s+(?:--work-dir|--workdir|--chdir)=\S+\n?", "", script)
        script = re.sub(r"#SBATCH\s+-D\s+\S+\n?", "", script)
        if work_dir and f"#SBATCH -D {work_dir}" not in "\n".join(header_lines):
            header_lines.append(f"#SBATCH -D {work_dir}")

        full_script = "\n".join(header_lines) + "\n\n" + script + "\n"


        if self.mode == "local":
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False
            ) as f:
                f.write(full_script)
                tmp_path = f.name
            try:
                stdout, stderr, rc = await self._run(f"sbatch {tmp_path}")
            finally:
                os.unlink(tmp_path)
        else:
            # For remote: write script to a temp path on the remote host
            remote_tmp = f"/tmp/mcp_sbatch_{os.getpid()}.sh"
            escaped = full_script.replace("'", "'\\''")
            await self._run(f"printf '%s' '{escaped}' > {remote_tmp}")
            stdout, stderr, rc = await self._run(f"sbatch {remote_tmp}")
            await self._run(f"rm -f {remote_tmp}")

        if rc != 0:
            return {
                "job_id": "",
                "status": "error",
                "message": f"sbatch failed (exit={rc}): {stderr or stdout}",
                "partition": partition,
            }

        # Parse job ID from "Submitted batch job 12345"
        match = re.search(r"(\d+)", stdout)
        job_id = match.group(1) if match else ""

        return {
            "job_id": job_id,
            "status": "submitted",
            "message": f"Job {job_id} submitted successfully",
        }

    async def status(self, job_id: str) -> dict:
        """Get job status via sacct.

        Returns dict with job_id, status, exit_code, start_time, end_time,
        stdout, stderr.
        """
        # Empty job_id returns immediate error (prevents LLM from polling indefinitely)
        if not job_id or not str(job_id).strip():
            return {
                "job_id": "",
                "status": "ERROR",
                "exit_code": None,
                "start_time": None,
                "end_time": None,
                "stdout": None,
                "stderr": None,
                "message": "job_id is empty — slurm_submit likely failed. Submit a corrected script.",
            }
        stdout, stderr, rc = await self._run(
            f"sacct -j {job_id} --noheader --parsable2 "
            f"--format=JobID,State,ExitCode,Start,End"
        )

        result: dict = {
            "job_id": job_id,
            "status": "UNKNOWN",
            "exit_code": None,
            "start_time": None,
            "end_time": None,
            "stdout": None,
            "stderr": None,
        }

        if rc != 0 or not stdout:
            # Fallback to squeue
            sq_out, _, sq_rc = await self._run(
                f"squeue -j {job_id} --noheader --format=%T"
            )
            if sq_rc == 0 and sq_out:
                result["status"] = sq_out.split("\n")[0].strip()
            return result

        # Parse first line from sacct
        lines = [l for l in stdout.split("\n") if l and not l.endswith(".batch") and not l.endswith(".extern")]
        if lines:
            parts = lines[0].split("|")
            if len(parts) >= 5:
                result["status"] = parts[1]
                # Exit code format: "0:0"
                exit_parts = parts[2].split(":")
                result["exit_code"] = int(exit_parts[0]) if exit_parts[0].isdigit() else None
                result["start_time"] = parts[3] if parts[3] != "Unknown" else None
                result["end_time"] = parts[4] if parts[4] != "Unknown" else None

        # Try to read stdout/stderr files
        if result["status"] in ("COMPLETED", "FAILED"):
            result["stdout"] = await self.get_stdout(job_id)
            result["stderr"] = await self.get_stderr(job_id)

        return result

    async def cancel(self, job_id: str) -> dict:
        """Cancel a SLURM job.

        Returns dict with success and message.
        """
        stdout, stderr, rc = await self._run(f"scancel {job_id}")
        if rc != 0:
            return {"success": False, "message": f"scancel failed: {stderr}"}
        return {"success": True, "message": f"Job {job_id} cancelled"}

    async def get_stdout(self, job_id: str) -> str | None:
        """Read stdout from the SLURM output file.
        
        Checks SLURM_LOG_DIR first (slurm_job_{job_id}.out or any *{job_id}*.out),
        then falls back to standard slurm-{job_id}.out.
        """
        import os as _os
        log_dir = _os.environ.get("SLURM_LOG_DIR", "")
        # Try all known output file patterns (generic + legacy)
        import os as _os2
        work_dir = _os2.environ.get("ARI_WORK_DIR", "")
        candidates = []
        if log_dir:
            candidates += [
                f"{log_dir}/slurm_job_{job_id}.out",
                f"{log_dir}/slurm-{job_id}.out",
            ]
        if work_dir:
            candidates += [
                f"{work_dir}/slurm-{job_id}.out",
                f"{work_dir}/slurm_job_{job_id}.out",
            ]
        candidates += [
            f"slurm_job_{job_id}.out",
            f"slurm-{job_id}.out",
        ]
        for pattern in candidates:
            stdout, _, rc = await self._run(f"cat {pattern} 2>/dev/null")
            if rc == 0 and stdout:
                return stdout
        # Generic fallback: find any file with job_id in name
        if log_dir:
            stdout, _, rc = await self._run(
                f"find {log_dir} -name '*{job_id}*.out' 2>/dev/null | head -1 | xargs cat 2>/dev/null"
            )
            if rc == 0 and stdout:
                return stdout
        return None

    async def get_stderr(self, job_id: str) -> str | None:
        """Read stderr from SLURM error file (searches same locations as get_stdout)."""
        import os as _os
        log_dir = _os.environ.get("SLURM_LOG_DIR", "")
        candidates = []
        if log_dir:
            candidates += [
                f"{log_dir}/slurm_job_{job_id}.err",
                f"{log_dir}/slurm-{job_id}.err",
            ]
        candidates += [
            f"slurm_job_{job_id}.err",
            f"slurm-{job_id}.err",
        ]
        for pattern in candidates:
            stdout, _, rc = await self._run(f"cat {pattern} 2>/dev/null")
            if rc == 0 and stdout:
                return stdout
        # Generic fallback: find any .err file with job_id
        if log_dir:
            stdout, _, rc = await self._run(
                f"find {log_dir} -name '*{job_id}*.err' 2>/dev/null | head -1 | xargs cat 2>/dev/null"
            )
            if rc == 0 and stdout:
                return stdout
        return None

    def close(self) -> None:
        """Close SSH connection if open."""
        if self._ssh_client is not None:
            self._ssh_client.close()
            self._ssh_client = None
