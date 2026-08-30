# Changelog

Wszystkie istotne zmiany w projekcie **GOG Library Manager** (gogv2).
Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/),
wersjonowanie wg [SemVer](https://semver.org/lang/pl/).

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
