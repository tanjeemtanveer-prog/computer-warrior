@echo off
setlocal
where git >nul 2>nul
if errorlevel 1 (
  echo Git for Windows is required. Install it, reopen PowerShell or Command Prompt, then run this file again.
  exit /b 1
)
if not exist ".git" (
  git init
  if errorlevel 1 exit /b 1
)
echo.
echo Repository is ready. Review GIT_WORKFLOW.md and RELEASE_AND_DEPLOYMENT_PLAN.md before your first commit.
echo.
git status --short
endlocal
