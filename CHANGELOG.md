# Changelog

Wszystkie istotne zmiany w projekcie **GOG Library Manager** (gogv2).
Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie wg [SemVer](https://semver.org/lang/pl/).

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
