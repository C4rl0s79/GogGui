# GOGGUI

GOGGUI is a Windows-first graphical frontend for `lgogdownloader` running in WSL.

## Goals
- Native-feeling Windows GUI for browsing a GOG library.
- Use `lgogdownloader` in WSL as the backend.
- Store persistent metadata and artwork cache outside the download folders.
- Support optional GUI login via `lgogdownloader --gui-login` when available.
- Keep XML verification data in a separate cache tree.

## Planned stack
- Frontend: C# + WinUI 3
- Backend integration: `wsl.exe` process execution
- Metadata source: local JSON and artwork files produced by `lgogdownloader`
- Persistent app config: JSON in app-local data folder

## Proposed structure
- `src/GOGGUI.App/` - WinUI application
- `src/GOGGUI.Core/` - models, services, config, process wrapper
- `docs/` - architecture notes and command flows

## MVP
- First-run setup wizard
- Login status check and optional GUI login
- Library scan from configured download folder
- Metadata cache in `cache/games`
- XML cache in `xml/games`
- Game details page
- Download/update actions through `wsl.exe`

## Notes
This scaffold is an initial starting point. Creating the remote GitHub repository itself must be done from a GitHub-authenticated environment.
