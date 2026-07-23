# Git workflow

## One-time setup

1. Run init_git_repository.bat.
2. Review git status.
3. Set your Git identity if this computer does not already have one.
4. Run verify_project.bat.
5. Create the first commit only after the tests pass.

## Every safe update

1. Create a feature branch with git switch -c feature/short-description.
2. Make one focused change.
3. Run verify_project.bat.
4. Review git status and git diff.
5. Commit only intended files.
6. Merge only after automated tests and a Windows manual test pass.

Do not commit node_modules, .wrangler, .dev.vars, online_sync.json, stats
files, or generated ZIP releases.

## Release rule

Tag only a build that has passed the tests, a Windows dashboard test, and a
checksum verification. Keep the tagged source and release notes together.
