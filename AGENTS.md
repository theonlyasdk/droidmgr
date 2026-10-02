Guidance for AI coding agents working in this repository.

ENVIRONMENT: POWERSHELL, NOT BASH

This is Windows PowerShell 5.1. Write PowerShell. Never write bash, sh, zsh, or cmd syntax.

  task              bash            -> PowerShell
  read a file       cat file        -> Get-Content file
  search contents   grep -r foo .   -> Select-String -Path . -Pattern foo -Recurse
  find by name      find . -name x  -> Get-ChildItem -Recurse -Filter x
  list, incl hidden ls -la          -> Get-ChildItem -Force
  first N lines     head -n 20      -> Get-Content file | Select-Object -First 20
  last N lines      tail -n 20      -> Get-Content file | Select-Object -Last 20
  delete            rm -rf dir      -> Remove-Item -Recurse -Force dir
  create dir        mkdir -p dir    -> New-Item -ItemType Directory -Force dir
  create file       touch f         -> New-Item -ItemType File f
  copy / move       cp a b / mv a b -> Copy-Item a b / Move-Item a b
  locate executable which x         -> Get-Command x
  write a file      echo hi > f     -> 'hi' | Set-Content f
  chain on success  cmd1 && cmd2    -> cmd1; if ($?) { cmd2 }

Never write && or ||. They arrived in PowerShell 7 and fail confusingly in 5.1.

Use the edit and write tools for file changes. Do not hand-roll file writes with shell
redirects or Set-Content; they mangle encoding and line endings.

Python: use python (3.14). There is no python3 on PATH. README.md and tools/README.md say
python3; they are wrong here.

REPOSITORY FACTS

A tkinter GUI for Android device management and scrcpy. Non-production software.

  droidmgr.py -> entry point. Only it puts src/ on sys.path (line 22).
  src/core/ -> non-UI logic: adb_manager.py, device_manager.py, scrcpy_manager.py,
               apk_icon.py, config_manager.py, dependency_manager.py, audit_logger.py
  src/ui/ -> tkinter widgets and dialogs; main_window.py, file_manager.py, dpi.py.
  tools/ -> build.py (PyInstaller) and package.py. build.py writes to build/ and dist/.
  requirements.txt -> lists only tkinter. There are no third-party dependencies.
  .agent/ -> working notes, background not requirements. Read one only if the task is
             about its topic.

Modules use bare imports like from core import ..., which resolve only via droidmgr.py.

SPEED RULES

These are deliberate. Follow them without asking.

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

Stop when the requested change is made; do not keep working "while you're in there."

Use the edit tool, not a script. Do not write a throwaway Python or PowerShell script to
rename a variable, add a log line, fix a typo, or change a default. Name the exact before
and after strings and call edit; when every occurrence in one file must change, pass
replaceAll. A script costs more turns than the edit it replaces, and it can be wrong in ways
the edit tool cannot.

The test for whether a script is justified: does the result depend on computation over input
you have not read, or is it a known set of text replacements? Known text means edit. Use a
script when it depends on computation: bulk edits spanning many files, generated or computed
content, reshaping data, or the build and packaging steps in tools/. A script that will be
reused belongs in tools/; never leave a throwaway script in the repo root.

2. Do not run tests.

This repository has no test suite: no tests/, no conftest.py, no test runner config.

Never run tests, and never create, configure, or run a test runner. If a task seems to need
coverage, say so in your summary and move on. Do not build or package the app either:
tools/build.py runs PyInstaller at 30-60+ seconds per invocation.

3. Smoke check instead. It is not a test.

Python compiles before it runs, so checking is worth it. This catches syntax errors and
bad imports, the two failures a small edit actually causes. It verifies nothing about
behaviour; logic and runtime errors surface only when the app runs.

To check a changed ui module, import it. About 135 ms.

  python -c "import sys; sys.path.insert(0,'src'); import ui.main_window; print('OK')"

Swap ui.main_window for your module. The sys.path.insert is required, for the reason above.
For syntax only, with no path setup and no side effects. About 50 ms.

  python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" src\ui\main_window.py

Prefer this over python -m py_compile, which also writes a .pyc into __pycache__.

If a change is not Python, skip checking. The edit tool already fails loudly when the
target text is absent or ambiguous, so reading the file back is enough.

Do not launch the GUI to check for runtime errors. It needs a connected device and it blocks.

4. One command, not a pipeline.

Issue the single command that answers the question. Do not chain exploratory commands to
"get a fuller picture." Unexpected output is usually the answer you were looking for; do
not spend a second command getting more.

Keep output small: pipe to Select-Object -First N, prefer -Filter over listing whole trees,
and prefer Select-String over reading a large file whole.

5. Never block on questions.

Do not ask the user to choose between options, confirm a plan, or approve a straightforward
edit. Make the reasonable call, implement it, and state the assumption in one line at the
end. Ask only when the answer would change files expensively to undo.

6. Batch, then report.

Independent tool calls go in a single message rather than one at a time. Do not narrate
progress between them.

End with a short summary: what changed, in which files, plus anything you deliberately left
alone.

WHEN THESE RULES DO NOT APPLY

If the task is large, architectural, or explicitly asks for tests or a build, that overrides
the speed rules above. Beyond a straightforward single-file edit, read the relevant files
properly first. Speed means not doing unnecessary work, not doing necessary work badly.