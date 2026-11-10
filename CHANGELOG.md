# Changelog

Wszystkie istotne zmiany w projekcie **GOG Library Manager** (gogv2).
Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie wg [SemVer](https://semver.org/lang/pl/).

## [Unreleased]

## [1.6.0] - 2026-11-10

### Dodano
- **Archiwum depotów obsługuje gry ze starym buildem Galaxy (content-system v1).** Wiele klasycznych gier
  (np. Betrayal at Krondor, Unreal Gold, World in Conflict) ma na GOG tylko build generation 1, a „Aktualizuj
  wszystko” je dotąd pomijało. Teraz pliki takiej gry są pobierane z `main.bin` (zapytania HTTP Range, sąsiednie
  małe pliki w jednym zapytaniu), sprawdzane MD5 z manifestu v1 i zapisywane w archiwum jako zwykłe chunki zlib
  z manifestem w formacie v2 — instalacja z archiwum, Lumen i serwer EmuStart czytają je jak każdy inny build.
  Rekord takiej gry ma pole `source: {content_system: 1, timestamp}`. „Napraw” odtwarza brakujące chunki
  takiej gry z `main.bin` (CDN chunków v2 ich nie ma, naprawa pobiera tylko pliki z brakującymi chunkami).
  Redisty buildu v1 (DOSBox, nGlide, MSVC, DirectX, .NET) trafiają do archiwum z repozytorium zależności GOG;
  redist z własnym katalogiem docelowym (np. nGlide → `system/`) ma w archiwum kopię manifestu z przesuniętymi
  ścieżkami. Instalacja online gry tylko z buildem v1 kończy się czytelnym komunikatem (instalator offline albo
  archiwum).

### Zmieniono
- **Extras przy „Aktualizuj wszystko” nie są pobierane ponownie:** CDN GOG podaje MD5 pliku jako ETag, więc
  plik na dysku o tym samym MD5 jest uznawany za aktualny bez pobierania do RAM — także przy pierwszym
  przebiegu po aktualizacji programu albo po utracie `_state/file_state.json`.
- Dziennik migracji pominiętej gry ma stan `skipped` z powodem (wcześniej zostawał `planned` bez powodu),
  nieudanej — `failed` z błędem; zakończonej migracji (`done`) późniejsze pominięcie nie nadpisuje.

### Naprawiono
- **Gry nie znikają z Lumena / serwera EmuStart po nieudanym „Aktualizuj wszystko”:** rozszerzenie zakresu
  tego samego buildu (nowy język, DLC) nie oznacza już kompletnego rekordu jako `incomplete` na czas pobierania
  — gdy pobranie albo weryfikacja się nie powiedzie (np. nieczytelny plik na dysku archiwum), gra zostaje
  dostępna w dotychczasowym zakresie.

## [1.5.1] - 2026-11-10

### Zmieniono
- **Szybsze kolejne „Aktualizuj wszystko”** po pierwszym pobraniu i weryfikacji:
  - extras: pamiętany stan plików (`<katalog instalatorów>/_state/file_state.json`, moduł `file_state.py`) —
    niezmienione pliki (ten sam rozmiar i czas modyfikacji) nie są ponownie haszowane, a pliki bez sumy GOG nie są
    pobierane do RAM, gdy CDN (HEAD: ETag / Last-Modified / długość) zgłasza ten sam obiekt;
  - archiwum: zatwierdzony rekord bieżącego buildu jest uznawany za aktualny bez czytania manifestów i `stat`
    każdego chunka; przy nowym buildzie nowe chunki są w pełni sprawdzane w pamięci zaraz po pobraniu (MD5,
    dekompresja, MD5 po dekompresji), a chunki z wcześniej zatwierdzonych rekordów tej gry nie są czytane ponownie;
  - sprzątanie nieużywanych chunków raz na cały przebieg i tylko wśród chunków usuniętych buildów (zamiast
    przeglądu całego archiwum po każdej grze); manifesty czytane raz na build;
  - skan folderu pobrań tylko dla bieżącej gry (zamiast pełnego skanu kilka razy na grę), buildy kolejnych gier
    pobierane w tle, lista posiadanych produktów z pamięci podręcznej (30 min);
  - pełna weryfikacja (naprawa, stan archiwum) sprawdza chunki równolegle.
- Nowa opcja *Ustawienia → Pobieranie → „Pełna weryfikacja przy każdej aktualizacji”* (domyślnie wyłączona)
  przywraca sprawdzanie wszystkiego od nowa.

## [1.5.0] - 2026-11-09

### Dodano
- **Archiwum depotów obejmuje całą grę:** wszystkie języki buildu i wszystkie posiadane DLC, które build
  zawiera — także gdy instalator offline miał tylko jeden język. Instalacja (EmuStart / Lumen) wybiera języki i
  DLC z archiwum. Starsze archiwa uzupełnia „Aktualizuj wszystko” (tylko brakujące chunki). DLC nieposiadane nie
  są pobierane; gdy lista posiadanych produktów jest niedostępna — DLC z instalatorów i wcześniejszego rekordu.
- **Metadane gier w folderach `<katalog instalatorów>/<slug>/`** (pełna synchronizacja, „Aktualizuj metadane”
  gry, migracja do archiwum): `product_<slug>.json`, `game-details.json` (bez kluczy CD i linków konta),
  `galaxy_<slug>.json` (producent, wydawca, gatunki, data wydania z api.gog.com/v2) i grafiki: `icon_`, `logo_`
  (logo z tytułem), `boxart_` (pionowa okładka), `background_`, `titlelogo_` (PNG z przezroczystością),
  `iconsquare_`. Istniejące grafiki nie są pobierane ponownie. Czyta je serwer EmuStart (opis i grafiki gier GOG
  w Lumen).
- **Lokalne archiwum depotów zamiast instalatorów offline** — opcja
  *Ustawienia → Pobieranie → „Pobieraj jako lokalne depoty zamiast instalatorów
  offline”* (domyślnie wyłączona, także dla istniejących konfiguracji). Archiwum
  (`<katalog instalatorów>/_depots`, wersjonowany format `goggui-depot-archive`
  v1, moduł `depot_archive.py`) przechowuje meta buildu, manifesty depotów i
  zależności oraz skompresowane chunki (wspólne dla gier/buildów), bez tokenów
  i secure-linków. Opis: `docs/DEPOT_ARCHIVE.md`.
- **Migracja „Aktualizuj wszystko” gra po grze**: inwentaryzacja → plan →
  pobranie → pełna weryfikacja → zatwierdzenie → usunięcie wyłącznie
  zastąpionych instalatorów tej gry (EXE/BIN, DLC; trwale, nie do Kosza) →
  zapis zakończenia → dopiero następna gra. Dziennik per gra pozwala wznowić
  po restarcie (także stan „zweryfikowane, czeka na sprzątanie”); błąd
  usuwania wstrzymuje kolejkę; raport z bilansem miejsca.
- **„📦 Zainstaluj z lokalnego depo” / „📦 DLC z lokalnego depo”** — wybór
  buildu, języków (+ główny), DLC i katalogu; instalacja bez dostępu do GOG,
  dokładna lista braków i naprawa tylko za zgodą (bez cichego fallbacku do CDN),
  wznawianie i weryfikacja zainstalowanych plików.
- Osobne oznaczenia w widoku gry: instalatory offline / depot lokalny
  (kompletny, niekompletny, czeka na sprzątanie) / zainstalowana.

### Zmieniono
- Wspólny silnik instalacji depotów przyjmuje źródło danych (CDN albo
  archiwum) — bez drugiego instalatora; wybór depotów wg języka w jednej
  funkcji (`_select_depots`) dla gry, DLC i archiwum.

### Bezpieczeństwo
- Ścieżki z manifestów depotów są sprawdzane przed zapisem (`..`, litera
  dysku/UNC, `:`, nazwy urządzeń; dotyczy też zwykłej instalacji z CDN).
- `supportData` z `goggame-*.script` nie kopiuje poza katalog gry, `setIni` nie
  pisze poza katalog gry i Dokumenty.

## [1.4.5] - 2026-10-27

### Zmieniono
- **Widok gry: metadane na grafice tła.** Karta „Metadane” zniknęła — data
  wydania, ocena GOG, instalacja, platformy, pliki instalatora, języki i linki
  wyświetlają się teraz w pasku pod logo, na półprzezroczystym tle (czytelne na
  każdej grafice; rozmiar tekstu z ustawienia „Metadane / małe”). Długa lista
  języków skraca się do 2 linii, pełna w podpowiedzi.
- **Prawa kolumna: dwie osobne karty** — „Screenshoty” i „Dodatki (extras)”,
  każda przewija się sama (bez wspólnego, przewijanego kontenera). Screenshoty
  układają się w tyle kolumn, ile się mieści; pokazywanych jest do 12 (było 4).

### Naprawiono
- **Puste miejsce po prawej stronie widoku gry** po przeciągnięciu podziału
  opis/prawa kolumna: prawa kolumna miała wagę `.9fr`, a pojedyncza kolumna
  z wagą < 1 zajmuje tylko taki ułamek wolnego miejsca (ok. 10% szerokości
  zostawało puste). Teraz `1fr`; domyślne proporcje bez zmian.

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
