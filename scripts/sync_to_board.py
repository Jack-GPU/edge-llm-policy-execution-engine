#!/usr/bin/env python3
"""把仓库同步到板上 /root/control_agent（不含大模型，模型需单独传）。"""

from __future__ import annotations

import argparse
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/root/control_agent"
INCLUDE = [
    "cpp",
    "python",
    "configs",
    "schemas",
    "data/eval",
    "docs",
    "third_party/rkllm/include",
    "third_party/rkllm/lib",
    "README.md",
    "requirements.txt",
]


def ensure(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    cur = ""
    for p in remote_dir.strip("/").split("/"):
        cur += "/" + p
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.2.11")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="orangepi")
    args = ap.parse_args()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, username=args.user, password=args.password, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    ensure(sftp, REMOTE)
    for item in INCLUDE:
        local = ROOT / item
        if local.is_file():
            ensure(sftp, str(Path(REMOTE, item).parent))
            sftp.put(str(local), f"{REMOTE}/{item}")
            print("file", item)
            continue
        for path in local.rglob("*"):
            if path.is_dir():
                continue
            if path.name.endswith(".rkllm"):
                continue
            rel = path.relative_to(ROOT)
            remote = f"{REMOTE}/{rel.as_posix()}"
            ensure(sftp, str(Path(remote).parent))
            sftp.put(str(path), remote)
            print("put", rel)
    sftp.close()
    c.close()
    print("done")


if __name__ == "__main__":
    main()
