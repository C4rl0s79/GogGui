# GOGGUI Copilot Instructions

## Project overview
GOGGUI is a Windows-first graphical frontend for `lgogdownloader` running in WSL.
The application provides a native-feeling Windows GUI for browsing a GOG library while using `wsl.exe` process execution as the backend bridge to `lgogdownloader`.

## Primary goals
- Preserve a native Windows desktop UX.
- Use `lgogdownloader` in WSL as the backend, not a reimplementation of downloader logic.
- Keep persistent metadata and artwork cache outside download folders.
- Keep XML verification data in a separate cache tree.
- Support optional GUI login via `lgogdownloader --gui-login` when available.

## Architecture assumptions
- Frontend: C# + WinUI 3.
- Core/backend integration: `wsl.exe` process execution.
- Metadata source: local JSON and artwork files produced by `lgogdownloader`.
- Persistent app config: JSON stored in the app-local data folder.
- Proposed structure:
  - `src/GOGGUI.App/` - WinUI application
  - `src/GOGGUI.Core/` - models, services, config, process wrapper
  - `docs/` - architecture notes and command flows

## MVP scope
- First-run setup wizard.
- Login status check and optional GUI login.
- Library scan from configured download folder.
- Metadata cache in `cache/games`.
- XML cache in `xml/games`.
- Game details page.
- Download/update actions through `wsl.exe`.

## Coding expectations
- Prefer minimal, targeted changes over broad refactors.
- Preserve the existing project structure unless a change is necessary to fix a real problem.
- Keep UI logic in the app layer and backend/process/config logic in the core layer.
- Do not hardcode machine-specific paths.
- Do not move cache or metadata into game download folders unless explicitly requested.
- Keep WSL integration explicit and debuggable.
- Prefer changes that improve reliability, startup behavior, diagnostics, and error visibility.

## Current investigation priority
The project currently builds in CI and produces a binary, but the application cannot be launched successfully.
When working on this repository, prioritize finding and fixing runtime startup issues over adding new features.

## Debugging instructions
When investigating startup failures:
- First identify whether the failure happens before the main window is shown, during app bootstrap, during dependency initialization, or during first view construction.
- Focus on WinUI app startup, bootstrap configuration, dependency injection, `InitializeComponent`, packaging/unpackaged mode assumptions, and `wsl.exe` process launch side effects.
- Look for exceptions that may be swallowed during startup.
- Prefer adding temporary diagnostics, structured logging, and safe exception reporting if needed.
- Suggest the smallest safe fix that makes the app launch reliably.
- After proposing a fix, explain the likely root cause in plain language.

## Validation expectations
For code changes:
- Review the startup flow end-to-end.
- Check for regressions in app launch, navigation, dependency injection, and WSL process invocation.
- If you change startup or bootstrapping logic, explain why the previous behavior could prevent launch.
- Prefer solutions that work both locally and in CI-produced binaries when possible.

## Response style
- Be concrete and repository-aware.
- When suggesting changes, mention the likely files and classes involved.
- If information is missing, say what should be inspected next instead of guessing.
- For runtime issues, prioritize root-cause analysis over speculative refactors.