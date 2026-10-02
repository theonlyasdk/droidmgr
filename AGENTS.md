Guidance for AI coding agents working in this repository.

ENVIRONMENT: POWERSHELL, NOT BASH

This is Windows PowerShell 5.1. Every shell command you run goes through PowerShell.
Write PowerShell. Never write bash, sh, zsh, or cmd syntax.

  read a file -> Get-Content README.md
  search file contents -> Select-String -Path src\*.py -Pattern 'scrcpy'
  find files by name -> Get-ChildItem -Path src -Recurse -Filter '*.py'
  list, incl. hidden -> Get-ChildItem -Force
  first/last N lines -> Get-Content droidmgr.py | Select-Object -First 20
  delete -> Remove-Item -Recurse -Force dist
  create a directory -> New-Item -ItemType Directory -Force -Path build
  locate an executable -> Get-Command python
  chain commands -> $ok = ...; if ($ok) { ... }

Bash-ism and its PowerShell replacement. Do not mix these up.

  ls -la, ls -> Get-ChildItem -Force
  cat file -> Get-Content file
  head -n 20 -> Get-Content file | Select-Object -First 20
  tail -n 20 -> Get-Content file | Select-Object -Last 20
  grep -r foo . -> Select-String -Path . -Pattern foo -Recurse
  find . -name '*.py' -> Get-ChildItem -Recurse -Filter *.py
  rm -rf dir -> Remove-Item -Recurse -Force dir
  cp a b / mv a b -> Copy-Item a b / Move-Item a b
  mkdir -p dir -> New-Item -ItemType Directory -Force dir
  touch f -> New-Item -ItemType File f
  which x / command -v x -> Get-Command x
  echo hi > f -> 'hi' | Set-Content f
  cmd1 && cmd2 -> cmd1; if ($?) { cmd2 }

PowerShell 5.1 has no && and no ||. They were added in PowerShell 7.

Use the edit and write tools for file changes. Do not hand-roll file writes with shell
redirects or Set-Content; they mangle encoding and line endings.

Python: the interpreter is python (Python 3.14 at
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe).
There is no python3 on PATH. README.md and tools/README.md say python3; those docs are
wrong for this machine. Always invoke python.

REPOSITORY FACTS

A tkinter GUI for Android device management and scrcpy. Non-production software.

  droidmgr.py -> entry point.
  src/core/ -> non-UI logic: adb_manager.py, device_manager.py, scrcpy_manager.py,
               apk_icon.py, config_manager.py, dependency_manager.py, audit_logger.py
  src/ui/ -> tkinter widgets: main_window.py, dialogs, file_manager.py, dpi.py
  tools/ -> build.py (PyInstaller) and package.py. build.py writes to build/ and dist/.
  requirements.txt -> lists only tkinter. There are no third-party dependencies.
  .agent/ -> working notes: todo.md, app-analysis.md, production-readiness.md,
             android-app-icon-extraction.md. These are background, not requirements. Read a
             file only when the task is about that file's topic.

SPEED RULES

These exist to keep iteration fast. They are deliberate. Follow them without asking.

1. A trivial request gets a trivial edit.

Rename a variable, fix a typo, change a label, add a log line, adjust a default, update a
doc line. Edit the file and report what changed. That is the whole task.

Do not, for a trivial request:

  - survey or audit the codebase
  - read neighbouring modules "for context" or "to match style"; match the style by
    reading the few lines you are editing
  - plan out loud, list your approach, or restate the request before starting
  - hunt for other places the same issue occurs unless asked
  - refactor, tidy, or improve anything you were not asked to change
  - ask for confirmation on a change that is easy to reverse

Stop when the requested change is made. Do not keep working "while you're in there."

2. Do not run tests.

This repository has no test suite: no tests/, no conftest.py, no test runner config.
Nothing exists to run.

Never run tests, and never try to create, configure, or run a test runner. If a task seems
to need test coverage, say so in your summary and move on. Do not build or package the app
to check your work either: tools/build.py invokes PyInstaller and costs 30-60+ seconds
per run.

3. Smoke check instead. It is not a test.

Python compiles to bytecode before it runs, so a cheap check is meaningful: it catches
syntax errors and bad imports, which are the two failures a small edit actually causes.
It verifies nothing about behaviour. Logic and runtime errors still surface when the app
runs.

To check a changed ui module, import it. About 135 ms.

  python -c "import sys; sys.path.insert(0,'src'); import ui.main_window; print('OK')"

Swap ui.main_window for the module you changed. The sys.path.insert is required:
droidmgr.py line 22 is the only thing putting src/ on the path, so bare imports such as
from core import ... fail without it.

For syntax only, with no path setup and no side effects. About 50 ms.

  python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" src\ui\main_window.py

Prefer this over python -m py_compile, which also writes a .pyc into __pycache__.

If a change is not Python, skip checking. The edit tool already fails loudly when the
target text is absent or ambiguous, so reading the file back is enough.

Do not launch the GUI to check for runtime errors. It needs a connected device and it blocks.

4. One command, not a pipeline.

Issue the single command that answers the question. Do not chain exploratory commands to
"get a fuller picture." If a command's output is not what you expected, that is usually the
answer you needed.

Keep output small: pipe to Select-Object -First N, and use -Filter rather than listing whole
trees. Prefer Select-String over reading a whole large file.

5. Never block on questions.

Do not ask the user to pick between implementation options, confirm a plan, or approve a
straightforward edit. Make the reasonable call, implement it, and state the assumption in one
line at the end. Ask only when the answer would change files in a way that is expensive to
undo.

6. Batch, then report.

Independent tool calls go in a single message rather than one at a time. Do not narrate
progress between them.

End with a short summary: what changed, in which files, plus anything you deliberately left
alone.

WHEN THESE RULES DO NOT APPLY

If the task is large, architectural, ambiguous, or explicitly asks for tests or a build,
those requests override the speed rules above. For anything beyond a straightforward
single-file edit, read the relevant files properly first. Speed comes from not doing
unnecessary work, not from doing necessary work badly.