# GOG Manager

Lokalny menedżer biblioteki **GOG** dla Windows — logujesz się na konto GOG,
przeglądasz swoje gry, **pobierasz i instalujesz je bez GOG Galaxy**, dogrywasz
DLC i aktualizujesz. Interfejs to strona (HTML/CSS/JS) w natywnym oknie
(pywebview), a cała aplikacja jest **przenośna** — metadane, cache i sekrety leżą
obok programu.

## Po co, skoro jest GOG Galaxy

- **Instalacja prosto z depotów Galaxy** — bez uruchamiania Galaxy i bez
  klasycznego instalatora: pliki gry pobierane są z CDN GOG i rozpakowywane
  wprost do katalogu gry.
- **Wybór języka(ów) instalacji** — dla gier z osobnymi depotami językowymi
  (np. Wiedźmin 3 ma pl/de/fr/ru… po kilka GB) instalujesz dokładnie to, co chcesz.
- **Offline-instalatory też** — możesz zamiast tego pobrać klasyczne
  offline-instalatory + extras i trzymać je jak backup.
- **Bez zbędnego balastu** — jedno lekkie okno, przenośne, bez tła rezydentnego.

## Uruchomienie i logowanie

Wersja przenośna: uruchom **`GOGManager.exe`**. Ze źródeł:

```bash
pip install -r requirements.txt
python app.py
```

Do działania potrzebny jest **Microsoft Edge WebView2 Runtime** (na Windows 11
i większości Windows 10 już jest) oraz **konto GOG** — logujesz się w aplikacji
(**Konto GOG → Zaloguj**), token jest zapamiętywany i odświeżany automatycznie.
Po zalogowaniu kliknij synchronizację, żeby zaciągnąć listę posiadanych gier.

## Główne funkcje

| Element | Co robi |
| --- | --- |
| **Lista gier** | cała biblioteka z okładką, statusem (pobrana / zainstalowana) i wyszukiwarką |
| **Sortowanie** | alfabetycznie, data wydania, **ocena GOG**, rozmiar, status, **data zakupu** |
| **Pobierz** | pliki gry z depotów albo offline-instalator + extras |
| **Zainstaluj** | rozpakowanie z depotów prosto do katalogu gry (z wyborem języków) |
| **➕ Dograj DLC** | instaluje posiadane DLC z ich depotów do zainstalowanej gry |
| **⟳ Aktualizuj installery / Aktualizuj wszystko** | odświeża offline-instalatory do bieżącego builda, kasuje osierocone stare pliki |
| **Uruchom / Otwórz folder / Usuń** | odpalenie gry lub instalatora, dostęp do plików, kasowanie |

Kliki „Pobierz"/„Zainstaluj", gdy coś już trwa, **dodają zadanie do kolejki**
(pasek kolejki z ✕ i „Wyczyść") — zadania idą po kolei.

## Instalacja: depoty, języki, DLC, zależności

- **Depoty (domyślnie)** — pliki gry z manifestu Galaxy, pobierane chunkami
  wieloma połączeniami i składane w katalogu gry; po sukcesie powstaje
  `goggame-<id>.info`, po którym biblioteka rozpoznaje instalację.
- **Języki** — okno instalacji pokazuje **rzeczywiste języki z buildu**; wybierasz
  jeden lub kilka. Domyślne ustawiasz w **Ustawienia → Pobieranie → języki
  instalacji (depot)**. Dopasowanie po prefiksie (`pl` ↔ `pl-PL`), depoty
  neutralne wchodzą zawsze.
- **DLC** — instalowane z **własnych depotów** (osobny productId) do katalogu gry;
  lista pokazuje tylko posiadane, oznacza już wgrane.
- **Zależności (redist)** — gry DOS/ScummVM dostają swój runtime (DOSBox itd.)
  z repozytorium zależności GOG, więc dają się uruchomić.

Wznawianie jest bezpieczne: postęp zapisywany jest na bieżąco
(`_goginstall_state.json`), a przerwaną instalację po prostu uruchamiasz jeszcze
raz — dokańcza brakujące pliki (nie zaczyna od zera i nie udaje ukończonej).

## Grafiki (tła i logo)

**SteamGridDB** daje ładniejsze tła (**hero**) i **logo** niż GOG — wpisujesz klucz
API w Ustawieniach (przycisk **Testuj**), a w szczegółach gry wybierasz/nadpisujesz
grafikę. **Ocena GOG** (użytkownicy, 0–5) i **kolejność zakupów** dociągane są
osobnymi przyciskami w Ustawieniach → Zaawansowane (bez pełnej synchronizacji).

## Katalogi i ustawienia

Aplikacja jest **przenośna**: metadane gier, cache GOG i sekrety są **zawsze
w katalogu programu**. W Ustawieniach → Katalogi wybierasz tylko:

- **gdzie pobierać** offline-instalatory (domyślnie `GOGinstall`),
- **gdzie są zainstalowane** gry (domyślnie `C:\GOG Games`).

Dalej: liczba połączeń pobierania (pliki × segmenty), języki aktualizacji
installerów, języki instalacji z depotów, motyw i rozmiary czcionek. Poziom
zabezpieczenia sekretów (token/klucze) pokazuje `security_status`.

## Wymagania

- **Windows** + **Microsoft Edge WebView2 Runtime**
- **konto GOG** (logowanie w aplikacji)
- Python 3.10+ ze źródeł: `pywebview` (patrz `requirements.txt`); opcjonalnie
  `zstandard` (szybsza dekompresja cache, jest fallback)

## Historia zmian

Patrz [CHANGELOG.md](CHANGELOG.md). Wersja bieżąca: stała `APP_VERSION` w `app.py`.
