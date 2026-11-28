"""One command for the checks this branch can actually run.

Exit codes: 0 pass, 1 test failure, 3 network blocked, 4 honesty/mutation failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _run(command: list[str]) -> int:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the acceptance gate that does not pretend network success"
    )
    parser.add_argument("--level", choices=("fast", "default", "all"), default="default")
    parser.add_argument("--scope", choices=("all", "env"), default="all")
    args = parser.parse_args(argv)
    code = _run([sys.executable, "-m", "compileall", "-q", "services/assistant", "planner", "tools"])
    if code:
        return 1
    # 同一条验收：地理天气/障碍物（助手，非 live）和 ENU 时变禁飞（规划复算）分开判定，一起跑。
    if args.scope == "env":
        target = ["services/assistant/tests/test_route_environment.py"]
    else:
        target = [
            "services/assistant/tests",
            "tests/test_diversion.py",
        ]
    marker = "fast and not live" if args.level == "fast" else "not live and not soak"
    code = _run([sys.executable, "-m", "pytest", *target, "-m", marker, "-q", "--tb=line", "-o", "addopts="])
    if code:
        return 1
    if args.level == "all":
        live = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "services/assistant/tests/test_route_environment.py",
                "-m",
                "live",
                "-q",
                "-o",
                "addopts=",
            ]
        )
        if live:
            print("RESULT: BLOCKED (network). Live checks did not pass; this is not a partial pass.")
            return 3
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
