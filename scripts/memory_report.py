"""Report resident memory of a running Bastion (API, console, tools server). Standard library only.

    python scripts/memory_report.py            # table of processes and the total, in MB
    python scripts/memory_report.py --max 450  # exit 1 if the total exceeds the limit
    python scripts/memory_report.py --min-processes 4  # exit 1 if a process has died

Inside a container it also reads the cgroup's own figures (current and peak), which are what
the platform's OOM killer looks at.
"""

import subprocess
import sys
from pathlib import Path

MARKERS = ("streamlit run", "uvicorn bastion", "demo.tools_server", "honcho", "headless_shell")


def _from_proc() -> list[tuple[int, float, str]]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
            status = (entry / "status").read_text()
        except OSError:
            continue
        rss = next((line.split()[1] for line in status.splitlines() if "VmRSS" in line), None)
        if rss:
            found.append((int(entry.name), int(rss) / 1024, args))
    return found


def _from_ps() -> list[tuple[int, float, str]]:
    out = subprocess.run(  # noqa: S603 - fixed arguments
        ["ps", "-eo", "pid=,rss=,args="],
        capture_output=True,
        text=True,
        check=True,  # noqa: S607
    ).stdout
    rows = (line.strip().split(None, 2) for line in out.splitlines())
    return [(int(pid), int(rss) / 1024, args) for pid, rss, args in rows]


def processes() -> list[tuple[int, float, str]]:
    rows = _from_proc() if Path("/proc/self/status").exists() else _from_ps()
    return [
        row for row in rows
        if any(marker in row[2] for marker in MARKERS) and "memory_report" not in row[2]
    ]  # fmt: skip


def cgroup(name: str) -> float | None:
    for path in (f"/sys/fs/cgroup/{name}", f"/sys/fs/cgroup/memory/{name}"):
        try:
            return int(Path(path).read_text().strip()) / (1024 * 1024)
        except (OSError, ValueError):
            continue
    return None


def main() -> int:
    limit = float(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    rows = processes()
    total = sum(rss for _, rss, _ in rows)
    for pid, rss, args in sorted(rows, key=lambda row: -row[1]):
        print(f"{rss:8.1f} MB  pid {pid:<7} {args[:90]}")
    print(f"{total:8.1f} MB  total resident memory of {len(rows)} processes")
    current, peak = cgroup("memory.current"), cgroup("memory.peak")
    if current is not None:
        print(f"{current:8.1f} MB  container memory now (cgroup, includes page cache)")
    if peak is not None:
        print(f"{peak:8.1f} MB  container memory peak (cgroup)")
    if "--min-processes" in sys.argv:
        wanted = int(sys.argv[sys.argv.index("--min-processes") + 1])
        if len(rows) < wanted:
            print(f"PROCESS MISSING: {len(rows)} running, expected {wanted}", file=sys.stderr)
            return 1
    if limit is not None and total > limit:
        print(f"OVER LIMIT: {total:.0f} MB > {limit:.0f} MB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
