#!/usr/bin/env bash
set -euo pipefail
task_script="${BASH_SOURCE[0]}"
task_directory="${task_script%/*}"
if [[ "$task_directory" == "$task_script" ]]; then task_directory=.; fi
cd "$task_directory/.."
task_python="${WORKTIMER_PYTHON:-python}"
"$task_python" -c 'import sys; assert sys.version_info >= (3,14), "Build needs Python 3.14+"'
if [[ ! -x .packaging-venv/Scripts/python.exe ]]; then
  "$task_python" -m venv .packaging-venv
fi
.packaging-venv/Scripts/python.exe -m pip install --disable-pip-version-check -r requirements-dev.txt
.packaging-venv/Scripts/python.exe scripts/build.py "$@"
