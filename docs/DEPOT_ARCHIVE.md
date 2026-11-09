# Lokalne archiwum depotów GOG

Tryb, w którym GOG Manager przechowuje pobrane gry jako **lokalne archiwum
depotów Galaxy (content-system v2)** zamiast offline-instalatorów i instaluje gry
bezpośrednio z tego archiwum — bez dostępu do GOG CDN.

Archiwum jest projektowane pod przyszłe udostępnianie przez EmuStart Server
(Lumen: odczyt chunków z serwera → dekompresja → zapis do katalogu gry). Ta
wersja implementuje wyłącznie stronę GogGui; integracji sieciowej jeszcze nie ma.

## 1. Ustawienie

**Ustawienia → Pobieranie → „Pobieraj jako lokalne depoty zamiast instalatorów
offline”** (`settings.json`: `"archive_mode": true`).

- Domyślnie **wyłączone** — także dla istniejących konfiguracji (brak klucza =
  `false`). Wyłączone = dotychczasowe działanie bez zmian.
- **Samo włączenie niczego nie zmienia na dysku** — nic nie jest pobierane,
  migrowane ani usuwane, dopóki nie uruchomisz pobierania lub aktualizacji.
- Włączone:
  - **Pobierz** — zaznaczone instalatory / DLC / pakiety językowe stają się
    *zakresem archiwum* (ich języki i identyfikatory DLC); extras pobierają się
    jak dotąd jako pliki; łatki (patches) są pomijane — build depotowy jest
    zawsze kompletny. Archiwizacja **nie instaluje** gry i nie zostawia
    rozpakowanego katalogu gry.
  - **⟳ Aktualizuj (jednej gry)** i **Aktualizuj wszystko** — migracja
    instalatorów do archiwum / aktualizacja archiwum do bieżącego buildu.
    Zmiana formatu przechowywania jest powodem migracji także wtedy, gdy wersja
    gry się nie zmieniła.
- Opcjonalnie `"archive_dir"` w `settings.json` (domyślnie
  `<katalog instalatorów>/_depots`; podkatalog z `_` jest pomijany przez skan
  pobranych gier).

## 2. Migracja — sekwencyjnie, gra po grze

Jednostką kolejki jest **cała gra** (z DLC, językami i zależnościami). Kolejność
dla każdej gry jest obowiązkowa i zapisywana w dzienniku
`_depots/migrations/<productId>.json`:

1. **Inwentaryzacja** plików instalatora w folderze gry (`*.exe`, `*.bin`, …).
2. **Plan**: bieżący build Galaxy (ta sama polityka co „Aktualizuj wszystko”:
   najnowszy build bez gałęzi beta), języki, DLC, zależności.
3. **Pobranie** brakujących manifestów, chunków i zależności (równolegle w
   obrębie tej jednej gry).
4. **Pełna weryfikacja** archiwum: każdy chunk ponownie odczytany, MD5
   skompresowanych danych, dekompresja, MD5 po dekompresji.
5. **Trwałe zatwierdzenie**: rekord buildu dostaje `"state": "complete"`
   (zapis atomowy), w dzienniku zostaje **zamrożona lista plików do usunięcia**
   (faza `committed`).
6. **Usunięcie wyłącznie zastąpionych instalatorów tej gry** (faza `cleanup`).
7. **Zapis zakończenia** (faza `done`).
8. Dopiero teraz **następna gra**.

Zakazy wbudowane w kod: nie ma fazy „pobierz całą bibliotekę”, gry nie są
migrowane równolegle, kolejna gra nie startuje przed końcem sprzątania
poprzedniej, nic nie jest usuwane przed weryfikacją, a cały katalog gry nigdy
nie jest kasowany (usuwane są pojedyncze pliki z zatwierdzonej listy).

Chwilowa duplikacja dotyczy więc **tylko jednej, aktualnie migrowanej gry**.

### Które pliki są usuwane

Tylko pliki **przypisane jednoznacznie**: dokładna nazwa bieżącego pliku GOG
(rozwiązany downlink) **i** dokładny rozmiar, dla:

- instalatora EXE gry bazowej i jego części BIN,
- instalatora DLC (posiadanego),

i tylko jeśli zweryfikowane archiwum je zastępuje:

- wszystkie języki instalatora są w archiwum i w buildzie (instalator
  wielojęzyczny = wszystkie jego języki),
- DLC jest w archiwum (z plikami albo jako DLC bez własnych plików, które build
  wymienia w `products`).

Zostają zawsze: **extras**, grafiki, metadane, zapisy, zainstalowane gry, stare
wersje instalatorów (nie pasują do bieżących plików GOG), pliki innego systemu,
pliki o **niejednoznacznym** przypisaniu (np. ta sama nazwa i rozmiar pod grą i
pod DLC), pliki zmienione od inwentaryzacji, instalatory języków/DLC, których
build nie zawiera. Każdy zachowany plik trafia do raportu z powodem.

Usuwanie jest **trwałe (nie do Kosza)** — Kosz nie zwolniłby miejsca; UI mówi to
przed startem.

### Błędy i wznawianie

| Sytuacja | Skutek |
|---|---|
| za mało miejsca na **nowe** dane (bez liczenia przyszłego usunięcia instalatorów; +64 MB zapasu) | gra pominięta z błędem, nic nie pobrano, instalatory nietknięte |
| błąd pobierania / weryfikacji | błąd w raporcie, instalatory nietknięte, kolejka idzie dalej; uszkodzone kopie chunków są kasowane, by następny przebieg pobrał je od nowa |
| brakująca zależność (redist) w repozytorium GOG | błąd, instalatory zostają |
| brak buildu Galaxy v2 / brak języka w buildzie | gra pominięta z konkretnym powodem, instalatory zostają |
| archiwum zweryfikowane, ale usuwanie instalatora nie powiodło się | **kolejka WSTRZYMANA** (faza `cleanup_failed`), następna gra nie startuje |
| restart po `committed` / `cleanup` / `cleanup_failed` | przy następnym „Aktualizuj wszystko” ta gra idzie **pierwsza**, kończone jest tylko sprzątanie zamrożonej listy, nic nie jest pobierane |
| restart w trakcie pobierania / weryfikacji | rekord `incomplete`; przebieg jest idempotentny — obecne i poprawne chunki nie są pobierane ponownie |

UI pokazuje stan „🗄 Depot zweryfikowany — czeka na sprzątanie”.

### Wersje

Archiwizowany jest bieżący build Galaxy (polityka „Aktualizuj wszystko”). Gdy
wersja instalatora różni się od wersji buildu albo archiwum przechodzi na nowszy
build, raport pokazuje zmianę (`instalator 1.0 → depot 1.1`). Starsze rekordy tej
samej gry są usuwane dopiero **po** zatwierdzeniu nowego; chunki, których używa
inny rekord (inna gra, build, zależność), zostają (GC po referencjach).

### Raport

Po przebiegu: zmigrowane gry, zaktualizowane archiwa, bez zmian, pominięte (z
powodem), błędy, zachowane pliki z powodem, **rozmiar usuniętych instalatorów**
oraz osobno **nowe dane w archiwum** i **bilans wolnego miejsca** (usunięte −
dodane) — rozmiar usuniętych instalatorów nie jest przyrostem wolnego miejsca.

Postęp na żywo: „Gra X z Y · etap” (inwentaryzacja, plan, manifesty, pobieranie
z transferem, weryfikacja, sprzątanie, wynik) + standardowy pasek transferu.

## 3. Format archiwum (wersja 1)

```
_depots/
  archive.json                          {"format":"goggui-depot-archive","version":1}
  chunks/ab/cd/<compressedMd5>          skompresowany chunk (zlib) dokładnie jak z CDN
  manifests/depot/ab/cd/<id>.json       manifest depotu (zdekodowany JSON)
  manifests/dep/ab/cd/<id>.json         manifest depotu zależności (redist)
  products/<pid>/<build>.meta.json      meta buildu Galaxy (depots, products,
                                        dependencies, installDirectory, …)
  products/<pid>/<build>.json           REKORD archiwum
  migrations/<pid>.json                 dziennik migracji gry
```

Rekord (`products/<pid>/<build>.json`):

```json
{
  "format": "goggui-depot-archive", "version": 1,
  "product_id": "1207658924", "title": "…", "slug": "…",
  "build_id": "5678", "version_name": "1.32", "os": "windows", "generation": 2,
  "install_directory": "The Witcher 3 Wild Hunt",
  "products": [{"id": "1207658924", "role": "base", "has_files": true},
               {"id": "1234", "role": "dlc", "name": "…", "has_files": false}],
  "depots": [{"manifest": "…", "productId": "…", "languages": ["*"], "size": 0, "compressedSize": 0}],
  "dependencies": [{"id": "MSVC2017", "manifest": "…"}],
  "scope": {"languages": ["en", "pl"], "dlcs": ["1234"]},
  "collisions": 3,
  "compressed_size": 0, "size": 0,
  "state": "complete", "created": "…", "verified": "…"
}
```

- **Identyfikatory**: productId gry i DLC, buildId, wersja.
- **Powiązania gra ↔ DLC**: `products` (rola `dlc`, `has_files`).
- **Języki**: `scope.languages` = języki zarchiwizowane; `depots[].languages`
  mapuje depoty na języki (`*` = neutralny, zawsze wchodzi).
- **Zależności i finalizacja**: manifesty zależności + pliki
  `goggame-<id>.info/.script` z depotów (z nich instalator odtwarza
  `supportData`/`setIni`).
- **Integralność**: nazwa chunka = MD5 skompresowanych danych; manifest niesie
  MD5 po dekompresji i MD5 plików.
- **Kompletność**: `state` dla konkretnego zakresu (build + języki + DLC).
- **Współdzielenie**: chunki są adresowane treścią i wspólne dla wszystkich gier,
  buildów i zależności (bez dodatkowej deduplikacji). GC usuwa tylko chunki, do
  których nie odwołuje się żaden rekord.
- **Bez sekretów**: tokeny, cookies, secure-linki i dane konta nigdy nie trafiają
  do archiwum (dodatkowo `strip_secrets` przy każdym zapisie).
- **Wersjonowanie**: archiwum z `version` nowszym niż obsługiwany jest odrzucane.

Kod formatu: `depot_archive.py` (bez zależności od UI — do ponownego użycia).

## 4. Instalacja z lokalnego archiwum

Przycisk **„📦 Zainstaluj z lokalnego depo”** (gra niezainstalowana) i
**„📦 DLC z lokalnego depo”** (gra zainstalowana). Okno pozwala wybrać:

- **build** (jeśli lokalnie jest kilka),
- **języki** (jeden lub kilka) i **język główny** — wygrywa przy plikach
  obecnych w kilku depotach językowych (np. `goggame-*.info`),
- **DLC** (także bez własnych plików — dostają `goggame-<id>.info`),
- **katalog docelowy** (domyślnie `<katalog gier>/<installDirectory>`; poza
  katalogiem gier biblioteka nie pokaże gry jako zainstalowanej — log ostrzega).

Zachowanie:

- kompletny zakres lokalnie → instalacja **bez żadnego zapytania do GOG**,
- brakujący zakres (język/DLC spoza archiwum, brakujące chunki/manifesty) →
  dokładna lista braków; **„Pobierz brakujące / napraw”** wymaga osobnej zgody,
- uszkodzone dane (sprawdzenie „dokładne (MD5)” albo błąd w trakcie instalacji)
  → propozycja naprawy (ten sam build, ponowne pobranie złych chunków,
  pełna weryfikacja, zatwierdzenie),
- **nigdy cichego fallbacku do CDN**.

Instalator to ten sam silnik co instalacja z depotów CDN
(`_collect_depot_groups` + `_download_depot_fileset`), tylko z innym źródłem
danych: chunk czytany z archiwum → weryfikacja MD5 → dekompresja → zapis
bezpośrednio w pliku docelowym. Bufory są ograniczone (jeden chunk ≈10 MB na
połączenie); jedyny plik tymczasowy to kontener małych plików (SFC) jednego
depotu. Postęp zapisuje `_goginstall_state.json` (wznowienie pomija ukończone
pliki), po zapisie wszystkie pliki są weryfikowane (rozmiar, MD5 z manifestu),
potem `supportData`/`setIni` z `.script` i `goggame-<id>.info` (z `buildId`) —
uruchamianie działa jak dla instalacji z depotów CDN.

Dogrywanie DLC sprawdza zgodność buildu: DLC z archiwum należą do buildu X —
jeśli zainstalowana gra ma w `goggame-<id>.info` inny `buildId`, operacja jest
odrzucana.

**Bezpieczeństwo ścieżek**: każda ścieżka z manifestu przechodzi
`depot_archive.safe_join` (odrzuca `..`, ścieżki z literą dysku/UNC, `:`/ADS,
nazwy urządzeń Windows; sprawdza wynik po `resolve()`). Jedna zła ścieżka
przerywa cały zestaw plików zanim cokolwiek zostanie zapisane. Akcje
`supportData` z `.script` nie mogą kopiować poza katalog gry, `setIni` — poza
katalog gry i Dokumenty; `setRegistry` jest tylko logowane (jak dotąd). Żadne
polecenia z manifestu nie są wykonywane.

**Rozszerzalność**: zdalne źródło (EmuStart Server) = kolejna para
`load(depot) → manifest` i `fetch(chunk) → bajty`; ten sam instalator.

## 5. Języki i DLC

- **Języki archiwizowane** (`scope.languages`) ≠ **języki instalacji** (wybór
  w oknie instalacji, podzbiór archiwizowanych).
- Migracja archiwizuje: języki z **Ustawienia → Języki aktualizacji**, + języki
  rozpoznane w zastępowanych instalatorach, + języki już obecne w archiwum,
  + zawsze depoty neutralne. Kody instalatorów są mapowane na kody depotów
  (`cz→cs`, `cn→zh`, `jp→ja`, `br→pt`, …).
- Brak języka w buildzie → **bez cichej zamiany na angielski**: język nie jest
  archiwizowany, a instalator w tym języku zostaje (powód w raporcie).
- Build z samymi depotami neutralnymi pokrywa wszystkie języki.
- Pliki obecne w kilku depotach językowych z różną treścią są liczone
  (`collisions`) i archiwizowane wszystkie; instalacja wybiera wariant języka
  głównego (ta sama logika co dotąd).
- DLC: posiadane DLC z instalatorami na dysku + DLC już w archiwum; DLC spoza
  buildu Galaxy → instalator zostaje.

## 6. Ograniczenia i nieobsługiwane formaty

- Obsługiwany jest wyłącznie **Galaxy content-system v2** (`generation=2`) dla
  platformy programu. Gry tylko z buildami v1, gry bez buildów Galaxy dla
  Linuksa itp. są **pomijane z powodem** — instalatory zostają.
- Migracja nie rozpakowuje EXE/BIN — dane są zawsze pobierane z GOG.
- Instalacja z depotów nie tworzy wpisów rejestru ani skrótów (jak dotąd);
  `setRegistry` (HKLM) jest pomijane.
- Pakiety językowe (osobne instalatory) nie są usuwane — nie mają
  jednoznacznego odpowiednika w depotach.
- Inwentaryzacja rozwiązuje linki tylko dla części, których rozmiar istnieje na
  dysku; stare wersje instalatorów (inna nazwa) zostają — usuń je ręcznie lub
  klasycznym updaterem (z wyłączoną opcją).
- Zmiana lokalizacji archiwum tylko przez `archive_dir` w `settings.json`.

## 7. Testy

Automatyczne: `tests/test_archive.py` (syntetyczny „GOG”, atrapy API i CDN,
katalogi tymczasowe). Uruchomienie: `python -m unittest discover -s tests -t .`

### Checklista ręczna (realne buildy — wymaga konta GOG i dużych pobrań)

Nie wykonane automatycznie — status do uzupełnienia przy teście:

- [ ] mała gra jednojęzyczna z instalatorem EXE+BIN: migracja, raport, brak instalatorów, extras na miejscu
- [ ] gra z PL i EN (np. Wiedźmin 3): archiwum `en, pl`, instalacja PL+EN z PL jako głównym, gra startuje po polsku
- [ ] gra z DLC z plikami i DLC bez plików: oba instalatory DLC usunięte; instalacja z DLC; dogranie DLC do istniejącej instalacji
- [ ] gra DOS (DOSBox jako zależność): instalacja z archiwum przy odłączonej sieci, gra startuje
- [ ] dwie gry w kolejce: druga zaczyna się dopiero po usunięciu instalatorów pierwszej (log)
- [ ] zablokowany plik instalatora (otwarty w innym programie): kolejka wstrzymana, po zwolnieniu i ponownym „Aktualizuj wszystko” dokończone tylko sprzątanie
- [ ] przerwanie (✕) w trakcie pobierania: ponowne uruchomienie nie pobiera ponownie gotowych chunków
- [ ] gra bez buildu Galaxy v2: pominięta z powodem, instalatory zostają
