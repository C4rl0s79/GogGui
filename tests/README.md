# Testy regresyjne

Testy jednostkowe krytycznych, destrukcyjnych i platformowych ścieżek GOG Managera.
Bez sieci, bez logowania GOG, bez dotykania realnych katalogów użytkownika
(operacje na plikach idą do katalogów tymczasowych; globalne `BASE`/`GOG_GAMES`
są podmieniane i przywracane w `setUp/tearDown`).

## Uruchomienie

```bash
python -m unittest discover -s tests -t .
```

(albo `python -m pytest tests/`)

## Zakres

| Plik | Obszar |
|------|--------|
| `test_depot_conflicts.py` | kolizje plików między depotami językowymi (język główny), wybór pliku uruchamiania (gra zamiast launchera), `setIni` z `.script` |
| `test_depot_download.py` | wspólny pobieracz depotów (sieć podstawiona) — składanie plików i SFC, zapis stanu tylko po plikach chunkowanych, wznawianie, SFC osobno dla każdego depotu, `_parse_dlc_ids` |
| `test_depot_state.py` | wznawianie instalacji z depotu — marker `_goginstall_state.json` (round-trip, mismatch builda, zapis „z góry") |
| `test_orphans.py` | **destrukcyjny** updater — `_cleanup_orphans` kasuje tylko osierocone pliki, chroni oczekiwane i rozpakowane podkatalogi, działa wyłącznie pod `BASE` |
| `test_scan.py` | wykrywanie instalacji/DLC — instalacja w toku (marker) nie liczy się jako ukończona; `_installed_dlc_ids` po `goggame-{id}.info` |
| `test_paths.py` | ścieżki per-platforma — `_ensure_content_dir` (tworzenie celu vs fallback), `_MY_OS`, endpoint buildów nie-zahardkodowany |
| `test_archive.py` | **lokalne archiwum depotów** (syntetyczny GOG: atrapy API/CDN/buildów) — opcja wyłączona = stare działanie; migracja bez zmiany wersji; ścisła kolejność gra A pobrana→zweryfikowana→posprzątana→dopiero B; błąd weryfikacji/pobierania nie usuwa instalatorów; błąd sprzątania wstrzymuje kolejkę i wznawia tylko sprzątanie; wznowienie po awarii w pobieraniu/weryfikacji/sprzątaniu/instalacji; extras zachowane; przypisanie EXE/BIN/DLC, pliki niejednoznaczne; PL+EN, depoty neutralne, język spoza buildu; DLC z plikami i bez; zależności (brak / obecna); instalacja przy zablokowanej sieci; brakujący/uszkodzony chunk + naprawa; brak miejsca; path traversal; GC współdzielonych chunków; brak sekretów w archiwum |
| `test_langs.py` | dobór języków/plików — `_norm_lang`, `_lang_match`, tag builda, `_update_selection_rows` (OS/język/owned/heavy, extras-only) |

## Nieobjęte (celowo)

Migracja sekretów (DPAPI/TPM) wymaga backendu kryptograficznego i izolacji od
realnego magazynu sekretów użytkownika — nie testowane tutaj, by testy pozostały
przenośne i bezpieczne.
