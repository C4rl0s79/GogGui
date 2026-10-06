# Changelog

Wszystkie istotne zmiany w projekcie **GOG Library Manager** (gogv2).
Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie wg [SemVer](https://semver.org/lang/pl/).

## [1.4.4] - 2026-10-06

### Naprawiono
- **Instalacja z kilkoma językami nadpisywała pliki gry wariantami innych
  języków** (Wiedźmin 3: każdy depot językowy ma własne `goggame-*.info`,
  `.hashdb`, `.script`). Teraz dla ścieżki obecnej w kilku depotach zostaje
  jedna wersja: języka głównego, potem wspólna (`*`); wariant przeznaczony tylko
  dla innych języków jest pomijany (inaczej przełączałby język gry).
- **Uruchamianie gier z zewnętrznym launcherem** — gdy GOG oznacza launcher jako
  zadanie główne (Wiedźmin 3 next-gen: `REDprelauncher.exe`, wymagający
  REDlaunchera z MSI, którego instalacja z depotu nie uruchamia), program
  uruchamia plik gry (`bin/x64_dx12/witcher3.exe`).
- **Akcje `setIni` z `goggame-*.script` są wykonywane** po instalacji (np. język
  lektora w `Dokumenty\The Witcher 3\user.settings`; `{userdocs}` = folder
  Dokumenty, także przekierowany do OneDrive). `setRegistry` (HKLM, wymaga
  admina) jest tylko logowane.

### Dodano
- Okno instalacji: wybór **języka gry (głównego)** obok listy języków.

### Testy
- 10 nowych (razem 41): kolizje plików między depotami językowymi, wybór pliku
  uruchamiania, `setIni` (z zachowaniem pozostałych linii i końców linii).

### Uwaga dla instalacji z 1.4.2 i starszych
- Gry zainstalowane z depotu, które miały kilka depotów z kontenerem małych
  plików (np. Wiedźmin 3), mają uszkodzone małe pliki (błąd naprawiony w 1.4.3)
  — wymagają reinstalacji albo naprawy.

## [1.4.3] - 2026-09-25

### Naprawiono
- **Uszkodzone małe pliki przy instalacji z kilku depotów** — kontener małych
  plików (SFC) brany był tylko z pierwszego depotu, a pliki z kolejnych
  (np. dodatkowy język) wycinane z niewłaściwego kontenera. Każdy depot jest
  teraz pobierany osobno ze swoim własnym SFC (`_collect_depot_groups`).
- **Wolna faza SFC** — plik stanu wznawiania był przepisywany w całości po
  każdym małym pliku (tysiące zapisów). Teraz zapis tylko po plikach
  pobieranych chunkami; SFC i tak składany jest od nowa przy wznowieniu.
- **Domyślny `D:\GOGinstall` zakładany na cudzych komputerach** — windowsowe
  domyślne katalogi są używane tylko, gdy już istnieją (inaczej folder obok
  programu); tworzone są wyłącznie katalogi ustawione jawnie oraz domyślne
  linuksowe `~/GOG/*`.
- Pasek postępu przy **wznawianiu** instalacji startował od 0 (porównanie
  nieznormalizowanych ścieżek) i nie dochodził do 100%.
- Pasek zbiorczy DLC pokazywał „X / 0 B" — rozmiar DLC wliczany do sumy.
- Linux: wybór instalatora `.sh` — największy plik (samorozpakowujące
  archiwum MojoSetup), bo nowe nazwy nie mają stałego prefiksu.

### Zmieniono
- Zależności redist (DOSBox/ScummVM) pobierane tym samym
  `_download_depot_fileset` co gra i DLC (koniec osobnej pętli).
- Wspólne helpery `_parse_dlc_ids`, `_depot_rel`, `_group_total` zamiast
  zdublowanego kodu.

### Testy
- 9 nowych testów (razem 31): składanie plików i SFC, liczba zapisów stanu,
  wznawianie, SFC osobno dla każdego depotu, parsowanie ID DLC, domyślny
  katalog windowsowy nie jest zakładany.

## [1.4.2] - 2026-09-15

### Naprawiono
- **Przerwana instalacja z depotu przed pierwszym zapisem stanu** mogła zostać
  uznana za ukończoną (gdy depot dostarczył `goggame-*.info` zanim padł proces).
  Marker wznawiania `_goginstall_state.json` jest teraz tworzony PRZED pobraniem
  jakiegokolwiek pliku.
- **Katalogi docelowe** — świeża instalacja (zwł. Linux `~/GOG/*`, ale też
  Windows z istniejącym dyskiem lecz bez folderu) była błędnie zastępowana
  katalogiem obok programu. Teraz katalog konfiguracyjny/domyślny jest
  tworzony, a fallback obok programu następuje tylko gdy nie da się go utworzyć
  (np. brak litery dysku przenośnej kopii).
- **Instalacja z depotu raportowała sukces mimo nieudanych DLC/dodatków** —
  worker zwraca teraz wynik uwzględniający powodzenie wszystkich zaznaczonych
  komponentów.

### Zmieniono
- SteamGridDB: użycie jawnego `urllib.parse.quote` (spójne z resztą kodu)
  zamiast re-eksportu `urllib.request.quote`.
- Wydzielono `_ensure_content_dir` na poziom modułu (testowalne; bez zmiany
  zachowania).

### Testy
- Odblokowano katalog `tests/` (usunięto z `.gitignore`) i dodano zestaw testów
  regresyjnych (stdlib `unittest`, offline): wznawianie instalacji z depotu,
  destrukcyjne sprzątanie orphanów, wykrywanie instalacji/DLC, ścieżki
  per-platforma, dobór języków/plików. Uruchomienie: `python -m unittest
  discover -s tests -t .` (22 testy).

## [1.4.1] - 2026-09-15

### Naprawiono
- **DLC z plikami SFC bez kontenera nie jest już raportowane jako
  zainstalowane** — wspólny kod pobierania depotów traktuje „są pliki sfcRef,
  ale brak smallFilesContainer" jako błąd (parytet z instalacją bazową).
- **Instalacja z depotu (Linux): wybór instalatora `.sh`** preferuje launcher
  MojoSetup (`gog_*`, `setup*`, `start*`) zamiast pierwszego alfabetycznie.

### Zmieniono
- **Wspólny `_download_depot_fileset`** dla instalacji gry bazowej i DLC —
  jedna implementacja pobierania chunków + składania kontenera SFC zamiast
  dwóch kopii (łatwiejsze utrzymanie, spójne zachowanie).
- Dogrywanie DLC przy świeżej instalacji dostaje **własny pasek postępu**
  (osobny hub) zamiast reużywać zamknięty hub gry bazowej.
- Slot postępu DLC numerowany indeksem (stabilny) zamiast `hash()` (losowy per
  proces, możliwe kolizje).
- Otwarcie okna pobierania robi mniej pełnych skanów biblioteki (dedup
  `scan_games`/`scan_installed_games`).

## [1.4.0] - 2026-09-04

### Dodano
- **Wsparcie dla Linuksa** — paczka źródłowa `GOGManager-<wersja>-linux.zip`
  (bez binarki): źródła + `install.sh` (venv z `--system-site-packages`,
  zależności, wykrycie backendu GTK/Qt, opcjonalny wpis w menu przez
  `--desktop`), `run.sh`, `requirements-linux.txt` i `DEPS.md` z komendami per
  dystrybucja. Buduje `build_linux.ps1` — skrypty trafiają do archiwum z LF
  i trybem 0755, stan użytkownika (`_gog_cache`, `settings.json`, logi) nie.
- `install.sh --qt` instaluje backend Qt prosto z pipa — dla systemów bez
  WebKitGTK i dla Steam Decka, gdzie system plików jest tylko do odczytu.

### Zmieniono
- **Platforma GOG-a nie jest już zahardkodowana.** `_MY_OS` (na górze `app.py`)
  ma wartość `windows` albo `linux` i steruje jednocześnie manifestem pobierania,
  wyborem instalatorów i endpointem buildów Galaxy — na Linuksie widać natywne
  instalatory MojoSetup `.sh` zamiast `setup*.exe`.
- **Uruchamianie instalatora** na Linuksie: `*.sh` przez `/bin/sh` (pobrany plik
  nie ma bitu wykonywalnego), odłączone od procesu menedżera. Gdy w katalogu
  leży tylko `.exe`, komunikat kieruje do innoextract/Wine zamiast milczeć.
- **Uruchamianie gry** na Linuksie idzie przez `start.sh` w katalogu gry —
  `playTasks` z `goggame-*.info` istnieją tylko w wydaniach windowsowych.
  Argumenty rozbijane przez `shlex` (POSIX nie parsuje stringa jak CreateProcess).
- **„Otwórz folder"** używa `xdg-open` zamiast `os.startfile`; brak `xdg-utils`
  daje czytelny komunikat.
- **Katalogi domyślne** na Linuksie to `~/GOG/installers` i `~/GOG/games`
  (windowsowe `D:\GOGinstall` / `C:\GOG Games` nie mają tam odpowiednika).
- **Instalacja z depotów** na Linuksie mówi wprost, że dana gra nie ma buildu
  linuksowego i trzeba użyć instalatora offline, zamiast zgłaszać brak buildów
  „dla Windows".

### Uwagi
- Sekrety na Linuksie: bez TPM-a i DPAPI (nie mają tam odpowiednika) —
  `data.json` jest zaciemniony i zapisany z prawami `0600`. Ścieżka windowsowa
  (TPM → DPAPI) zostaje bez zmian.

## [1.3.0] - 2026-08-30

### Dodano
- **Wybór języka(ów) instalacji z depotów.** Wcześniej instalacja z depotu brała
  zawsze angielski + depoty neutralne (zahardkodowane `_lang_match`), bez wyboru i
  bez możliwości wielu języków — dla gier z osobnymi depotami językowymi (np.
  Wiedźmin 3 ma pl/de/fr/ru… po ~4 GB każdy) polska wersja nigdy się nie
  instalowała. Teraz:
  - okno instalacji **i** „Dograj DLC" pokazuje listę **rzeczywistych języków z
    buildu** (`get_build_languages`) z polem wyboru (wiele naraz);
  - domyślne języki w Ustawieniach → Pobieranie (`depot_langs`, domyślnie `en`),
    nadpisywalne per instalacja;
  - dopasowanie po prefiksie (`pl` ↔ `pl-PL`), depoty neutralne (`*`) zawsze
    wchodzą; instalacja bazy i DLC używa tego samego wyboru.

## [1.2.0] - 2026-08-30

### Dodano
- **Dogrywanie DLC do zainstalowanej gry** — przycisk „➕ Dograj DLC" przy grze
  zainstalowanej otwiera listę DLC; zaznaczone są instalowane z depotów Galaxy
  prosto do katalogu gry (`install_dlc` / `_install_dlc_worker`, kolejkowalne).
  Lista pokazuje **tylko posiadane** DLC, a te już zainstalowane są oznaczone
  („zainstalowane") i domyślnie odznaczone — program wie, co jest wgrane
  (`get_downloads` zwraca `installed_dlc` na podstawie `goggame-{id}.info`).

### Naprawiono
- **DLC zaznaczone przy instalacji z depotu nie było instalowane** (np.
  Cyberpunk). Wcześniej DLC z instalacji depot trafiało do ścieżki offline
  (pobranie instalatora do GOGinstall) zamiast być rozpakowane do katalogu gry.
  Teraz zaznaczone DLC są instalowane z **ich własnych depotów** (osobny
  `productId` → własny secure-link) do katalogu gry, z zapisem `goggame-{dlc}.info`
  (`_install_dlc_via_depots`). W kroku „extras" pozostają już tylko prawdziwe
  dodatki i language packs — DLC nigdy nie jest tu pobierane jako instalator.

## [1.1.3] - 2026-08-30

### Naprawiono
- **Literówka w tłumaczeniu (EN) łamała cały JavaScript — żaden przycisk nie
  reagował.** Apostrof w „site's" był podwójnie zescapowany (`\\'`), przez co
  string i18n zamykał się za wcześnie (SyntaxError → cały `<script>` nie ładował
  się). Poprawiono na `\'`; sortowanie „Data zakupu" z 1.1.2 działa dopiero z tą
  wersją. (Weryfikacja: `node --check`.)

## [1.1.2] - 2026-08-30

### Dodano
- **Sortowanie „Data zakupu"** — jak opcja „by purchase date" na stronie GOG.
  Kolejność pobierana z `getFilteredProducts?sortBy=date_purchased` (stronicowana,
  od najświeższego zakupu) i zapisywana jako ranga per gra (`purchase_order.json`).
  Nowa opcja w dropdownie sortowania (badge `#N` = pozycja zakupu) oraz przycisk
  **„🛒 Pobierz daty zakupu"** w Ustawieniach → Zaawansowane (bez pełnej
  synchronizacji). Gry bez pobranej rangi lądują na końcu.

## [1.1.1] - 2026-08-30

### Naprawiono
- **Przerwana instalacja z depotu była uznawana za ukończoną przy wznowieniu.**
  Grę uznawaliśmy za zainstalowaną po obecności pliku `goggame-*.info`, ale ten
  plik jest częścią danych gry i bywa pobrany z depotu ZANIM reszta się ukończy;
  stan wznawiania (`_goginstall_state.json`) kasujemy dopiero po sukcesie. Skutek:
  po przerwaniu ponowny „Zainstaluj" widział `goggame-*.info` i odmawiał („już
  zainstalowana") zamiast wznowić. Teraz katalog z obecnym `_goginstall_state.json`
  jest traktowany jako instalacja w toku — nie „zainstalowana" — więc wznowienie
  dokańcza pobieranie. Poprawia też status w bibliotece (gra w trakcie nie pokazuje
  się jako zainstalowana).

## [1.1.0] - 2026-08-30

### Dodano
- **Updater klasycznych instalatorów** (`update_game` / „⟳ Aktualizuj installery"
  przy grze): odświeża pobrane instalatory offline + extras do bieżącego builda
  GOG i **trwale usuwa osierocone stare pliki**. Wersje legacy (stare buildy w
  extras, inne OS/języki, patche przyrostowe) są pomijane.
- **„Aktualizuj wszystko"** (przycisk w pasku narzędzi) — updater po kolei dla
  wszystkich pobranych gier.
- **Kolejka pobierania/instalacji**: klik „Pobierz"/„Zainstaluj" gdy coś już
  trwa dodaje zadanie do kolejki zamiast je odrzucać. Pasek kolejki w panelu
  aktywności (usuwanie pozycji, „Wyczyść"), zadania startują sekwencyjnie.
- **Sortowanie listy gier** (dropdown): Alfabetycznie, Data wydania, Ocena GOG,
  Rozmiar (pobrane), Status. Kafelek pokazuje wartość aktywnego sortowania.
- **Ocena GOG** (użytkownicy, 0–5, z `reviews.gog.com`) — w szczegółach gry i do
  sortowania; pobierana przy synchronizacji oraz przyciskiem „⭐ Pobierz oceny
  GOG" (Ustawienia → Zaawansowane), bez pełnej synchronizacji.
- Ustawienie **języków updatera** (`update_langs`, domyślnie `en, pl`) w
  Ustawienia → Pobieranie.
- Wykrywanie **extras** przy pobranych grach: rozmiar/liczba plików bonusowych
  (chip 🎁), skan uwzględnia podkatalog `extras/`.

### Naprawiono
- **Uszkodzone pliki po pobieraniu segmentowym** (MD5 nie pasuje): gdy CDN GOG
  ignorował nagłówek `Range` i zwracał całość (200), każdy segment zapisywał
  cały plik od swojego offsetu. Dodano sondę wsparcia `Range` (fallback na jedno
  połączenie), twardą kontrolę statusu `206` i obsługę `HTTP 416` przy wznawianiu.
- **Gry z samymi extras były niewidoczne** — skan uznawał grę za pobraną tylko
  po plikach instalatora w katalogu głównym; teraz uwzględnia `extras/`.
- **Filtr „Pobrane" ukrywał zainstalowane gry** — „pobrany instalator" i
  „zainstalowana gra" to niezależne stany; gra może być w obu zakładkach.
- **Kolejkowanie było niemożliwe podczas pracy** — okno wyboru plików było
  blokowane (`isRunning`), a przyciski Pobierz/Instaluj renderowały się jako
  wyłączone; teraz pozostają aktywne, by dodać zadanie do kolejki.

### Zmieniono
- **Weryfikacja przy aktualizacji**: instalatory z tagiem builda w nazwie
  (`…(NNNNN)…`) rozpoznawane po nazwie (rozmiar z API GOG bywa niewiarygodny —
  zaokrąglony do MiB); pliki bez sumy kontrolnej GOG (większość bonusów, których
  checksum 404) weryfikowane przez pobranie do RAM i porównanie treści —
  identyczne odrzucane bez zapisu, różne zastępowane.
- „Stop" przerywa bieżące zadanie **i czyści kolejkę**.

## [1.0.0]

### Baza
- Port menedżera biblioteki GOG z C# do Pythona (pywebview + klasa `Api`).
- Synchronizacja biblioteki z konta GOG, pobieranie instalatorów offline,
  instalacja z depotów Galaxy (content-system v2) wraz z zależnościami (redist),
  okładki/logo (SteamGridDB), sekrety szyfrowane (TPM/DPAPI), logowanie GOG.
