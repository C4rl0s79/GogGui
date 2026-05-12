# Architecture

## Overview
GOGGUI is a Windows desktop application that uses `lgogdownloader` inside WSL as a backend engine.

## Main responsibilities
- Configure and validate the WSL distro and library directory.
- Check login status with `lgogdownloader --check-login-status`.
- Trigger `--login` or `--gui-login`.
- Scan the library directory for local game metadata.
- Copy metadata and artwork to a persistent app cache.
- Copy XML verification files to a dedicated XML cache.
- Execute download, update, and repair actions.

## Suggested solution layout
- `GOGGUI.App`: WinUI views and view models.
- `GOGGUI.Core`: models, services, parsers, process execution, cache synchronization.

## Primary services
- `AppSettingsService`
- `WslProcessService`
- `LgogService`
- `LibraryScanService`
- `CacheSyncService`
- `XmlCacheService`
- `DownloadQueueService`

## First-run flow
1. Ask for WSL distro.
2. Ask for Windows download directory.
3. Derive WSL path from Windows path.
4. Save app settings.
5. Configure `lgogdownloader` directory and XML directory.
6. Check login status.
7. Prompt for login if needed.
8. Run initial library scan and build cache.

## Cache layout
- `cache/games/<slug>/product.json`
- `cache/games/<slug>/details.json`
- `cache/games/<slug>/icon.png`
- `cache/games/<slug>/logo.jpg`
- `cache/games/<slug>/state.json`
- `xml/games/<slug>/*.xml`

## Status model
- `MetadataOnly`
- `Missing`
- `Partial`
- `Complete`
- `Downloading`
- `Queued`
- `Error`
