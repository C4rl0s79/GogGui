# GOG Library Manager na Linuksie — zależności systemowe

`install.sh` stawia środowisko Pythona (`.venv`) i instaluje `pywebview`.
Tego, co poniżej, skrypt **nie** zainstaluje sam — wymaga `sudo` i różni się
między dystrybucjami.

## Minimum

| Co | Po co | Bez tego |
|---|---|---|
| Python 3.10+ z `venv` | całość | nic nie ruszy |
| PyGObject + WebKitGTK | okno aplikacji | brak GUI (albo użyj `--qt`) |
| `xdg-utils` | „Otwórz folder” | ta jedna funkcja |

## Instalacja

### Debian / Ubuntu / Linux Mint / Pop!\_OS

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 xdg-utils
```

Na starszych wydaniach (Ubuntu 22.04 i wcześniejsze) zamiast
`gir1.2-webkit2-4.1` jest `gir1.2-webkit2-4.0` — działa tak samo.

### Fedora / Nobara

```bash
sudo dnf install -y python3 python3-pip python3-gobject webkit2gtk4.1 xdg-utils
```

### Arch / Manjaro / EndeavourOS

```bash
sudo pacman -S --needed python python-pip python-gobject webkit2gtk-4.1 xdg-utils
```

### openSUSE

```bash
sudo zypper install python311 python311-pip python311-gobject typelib-1_0-WebKit2-4_1 xdg-utils
```

### Bez GTK — backend Qt

Jeśli WebKitGTK nie jest dostępny (albo nie chcesz go instalować):

```bash
./install.sh --qt
```

Pip dociągnie wtedy backend Qt do `.venv`. Jest cięższy (~150 MB), ale nie
wymaga pakietów systemowych poza samymi bibliotekami Qt.

### Steam Deck (SteamOS)

System plików jest tylko do odczytu, więc `pacman` odpada. Użyj `./install.sh
--qt` — backend Qt instaluje się w całości do `.venv`, bez ruszania systemu.

## Weryfikacja

```bash
./install.sh --check
```

Wypisze, czego brakuje, bez ruszania środowiska.

## Rzeczy specyficzne dla Linuksa

**Instalatory.** Program prosi GOG o pliki dla platformy `linux`, czyli natywne
instalatory **MojoSetup `.sh`** zamiast `setup*.exe`. Uruchamiane są przez
`/bin/sh` (pobrany plik nie ma bitu wykonywalnego). Gry, które nie mają wydania
linuksowego, po prostu nie pokażą instalatora — do ich uruchomienia potrzebny
jest Wine/Proton, a program tego nie robi za Ciebie.

**Instalacja z depotów Galaxy.** Działa tylko dla gier mających build linuksowy,
a takich jest niewiele. Dla reszty program powie wprost, żeby użyć instalatora
offline `.sh`.

**Uruchamianie gier.** Zamiast `playTasks` z `goggame-*.info` (to format wydań
windowsowych) używany jest `start.sh` w katalogu gry. Proces startuje odłączony
(`start_new_session`), więc zamknięcie menedżera nie ubija gry.

**Katalogi domyślne.** `~/GOG/installers` (pobrane instalatory) i `~/GOG/games`
(zainstalowane gry) — zamiast windowsowych `D:\GOGinstall` i `C:\GOG Games`.
Obie ścieżki zmienisz w ustawieniach.

**Sekrety.** Windows używa TPM-a i DPAPI. Na Linuksie nie ma ich odpowiednika,
więc `_gog_cache/data.json` jest tylko zaciemniony i zapisany z prawami `0600`
(do odczytu wyłącznie dla Ciebie). To chroni przed przypadkowym podejrzeniem,
ale **nie** przed kimś, kto ma dostęp do Twojego konta. Hasło do GOG-a i tak
nie jest nigdzie zapisywane — logowanie odbywa się w przeglądarce.
