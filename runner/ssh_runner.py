"""
ssh_runner.py — Connects to a client server via SSH, deploys the analyzer,
runs it, and retrieves the JSON report.

Dependencies: paramiko
"""

import json
import os
import tarfile
import tempfile
from pathlib import Path

import paramiko


PROJECT_ROOT = Path(__file__).parent.parent
ANALYZER_DIR = PROJECT_ROOT / "analyzer"
DATA_DIR = PROJECT_ROOT / "data"
REMOTE_WORK_DIR = "/tmp/etendo_migration_agent"


def _pack_analyzer(tmp_dir: str) -> str:
    """Creates a tar.gz of the analyzer directory, analyze.py entry point, and data/."""
    tar_path = os.path.join(tmp_dir, "analyzer.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(ANALYZER_DIR, arcname="analyzer")
        tar.add(PROJECT_ROOT / "analyze.py", arcname="analyze.py")
        if DATA_DIR.exists():
            tar.add(DATA_DIR, arcname="data")
    return tar_path


def run_on_host(
    hostname: str,
    etendo_root: str,
    username: str,
    client_name: str = None,
    password: str = None,
    key_path: str = None,
    port: int = 22,
    output_dir: str = None,
) -> dict:
    """
    Deploys and runs the analyzer on a remote host.

    Args:
        hostname:     IP or FQDN of the client server.
        etendo_root:  Absolute path to the Etendo installation on the remote.
        username:     SSH username.
        password:     SSH password (optional if key_path is provided).
        key_path:     Path to the private key file (optional).
        port:         SSH port (default 22).
        output_dir:   Local directory to save the JSON report. Defaults to
                      the project's output/ directory.

    Returns:
        Parsed JSON report as a dict.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {"hostname": hostname, "port": port, "username": username}
    if key_path:
        connect_kwargs["key_filename"] = key_path
    if password:
        connect_kwargs["password"] = password

    client.connect(**connect_kwargs)
    sftp = client.open_sftp()

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = _pack_analyzer(tmp)

        # Upload
        sftp.mkdir(REMOTE_WORK_DIR)
        remote_tar = f"{REMOTE_WORK_DIR}/analyzer.tar.gz"
        sftp.put(tar_path, remote_tar)

    # Extract and run
    commands = [
        f"cd {REMOTE_WORK_DIR} && tar xzf analyzer.tar.gz",
        f"python3 {REMOTE_WORK_DIR}/analyze.py "
        f"--path {etendo_root} --output {REMOTE_WORK_DIR}/report.json"
        + (f" --client \"{client_name}\"" if client_name else ""),
    ]
    for cmd in commands:
        _, stdout, stderr = client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            raise RuntimeError(f"Remote command failed ({exit_status}): {cmd}\n{error}")

    # Retrieve report
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_report:
        sftp.get(f"{REMOTE_WORK_DIR}/report.json", tmp_report.name)
        tmp_report_path = tmp_report.name

    with open(tmp_report_path) as f:
        report = json.load(f)

    # Save locally
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "output"
    os.makedirs(output_dir, exist_ok=True)
    safe_host = hostname.replace(".", "_").replace(":", "_")
    local_path = os.path.join(output_dir, f"{safe_host}.json")
    with open(local_path, "w") as f:
        json.dump(report, f, indent=2)

    # Cleanup remote
    client.exec_command(f"rm -rf {REMOTE_WORK_DIR}")
    sftp.close()
    client.close()

    print(f"Report saved to {local_path}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Etendo migration analyzer via SSH")
    parser.add_argument("hostname")
    parser.add_argument("etendo_root")
    parser.add_argument("--user", required=True)
    parser.add_argument("--client", help="Client name for the report")
    parser.add_argument("--password")
    parser.add_argument("--key", help="Path to SSH private key")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    report = run_on_host(
        hostname=args.hostname,
        etendo_root=args.etendo_root,
        username=args.user,
        client_name=args.client,
        password=args.password,
        key_path=args.key,
        port=args.port,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2))
