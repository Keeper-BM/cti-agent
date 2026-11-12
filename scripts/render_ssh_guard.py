"""Render a standalone forced-command guard for a dedicated Ubuntu SSH account."""

import argparse

from backend.collectors.ssh_protocol import COLLECTOR_VERSION, COMMANDS


def render_guard(*, include_file_verification: bool = False) -> str:
    allowed = list(COMMANDS.values())
    if include_file_verification:
        from backend.verification.service import HASHER

        allowed.append(HASHER)
    return (
        "#!/usr/bin/python3 -I\n"
        f'"""Generated CTI SSH guard: {COLLECTOR_VERSION}. Install as root; do not edit."""\n'
        "import os\n"
        "import shlex\n"
        "import sys\n\n"
        f"ALLOWED = {tuple(allowed)!r}\n\n"
        'command = os.environ.get("SSH_ORIGINAL_COMMAND", "")\n'
        "if command not in ALLOWED:\n"
        '    print("Only fixed CTI read commands are allowed", file=sys.stderr)\n'
        "    sys.exit(126)\n"
        "args = shlex.split(command)\n"
        "os.execve(args[0], args, {})\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-file-verification",
        action="store_true",
        help="Also allow the exact bundled file-verification program; no sudo rule is installed",
    )
    args = parser.parse_args()
    print(render_guard(include_file_verification=args.include_file_verification), end="")


if __name__ == "__main__":
    main()
