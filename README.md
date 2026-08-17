# GOG Manager

Desktopowy menedżer biblioteki **GOG** (Windows, Python + [pywebview]): logowanie
do konta GOG, przeglądanie biblioteki, pobieranie **offline-instalatorów** i
zależności (redist), instalacja/uruchamianie gier oraz pobieranie grafik
(okładki, hero, logo — GOG / SteamGridDB). Interfejs to lekki HTML (`assets/`)
w oknie natywnym.

> Wcześniej repozytorium zawierało prototyp w C#/.NET (WinUI, frontend dla
> `lgogdownloader` w WSL). Został zastąpiony działającą, samodzielną wersją
> w Pythonie (pobiera bezpośrednio z GOG, bez WSL).

## Wymagania

**Runtime (zewnętrzne):**
- **Microsoft Edge WebView2 Runtime** — backend GUI dla pywebview na Windows.
  Na Windows 11 i większości Windows 10 jest już zainstalowany; w razie potrzeby:
  <https://developer.microsoft.com/microsoft-edge/webview2/>.
- **Konto GOG** — logowanie odbywa się w aplikacji (OAuth GOG); pobierane są
  oficjalne offline-instalatory GOG.

**Python:**
- **Python 3.10+** (Windows)
- **pywebview** — okno natywne + most JS↔Python (wymagane)
- *(opcjonalnie)* **zstandard** — szybsza (de)kompresja cache; przy braku
  używany jest `lzma`/`zlib` z biblioteki standardowej

```bash
pip install -r requirements.txt
```

## Uruchomienie (ze źródeł)

```bash
python app.py
```

Stan aplikacji (tokeny, cache, ustawienia) powstaje obok pliku/`.exe`
(`_gog_cache/`, `settings.json`). Pobrane instalatory trafiają do katalogu
`GOGinstall/` (konfigurowalne w ustawieniach).

## Wersja portable (.exe)

Gotowe `GOGManager.exe` jest dołączane do [Releases](../../releases).
Zbudowanie samodzielnie (PyInstaller):

```bash
pip install pyinstaller pywebview
pyinstaller GOGManager.spec
# wynik: dist/GOGManager.exe
```

Licencja: **GPL-2.0** (patrz [LICENSE](LICENSE)).
