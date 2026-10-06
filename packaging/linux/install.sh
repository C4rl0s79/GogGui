#!/usr/bin/env sh
# Instalacja GOG Library Managera na Linuksie: venv + zależności Pythona.
# Nie kompiluje binarki — stawia środowisko obok źródeł, w katalogu .venv.
#
#   ./install.sh              # venv + zależności (backend GTK z systemu)
#   ./install.sh --qt         # dodatkowo backend Qt z pipa (gdy brak GTK)
#   ./install.sh --desktop    # wpis w menu aplikacji
#   ./install.sh --check      # tylko raport, bez instalacji
#
# Venv powstaje z --system-site-packages, bo pywebview w wariancie GTK
# potrzebuje PyGObject (`python3-gi`), którego nie da się sensownie
# zainstalować pipem — jest pakietem systemowym z bindingami do WebKitGTK.
set -eu

cd "$(dirname "$0")"

RED=''; YEL=''; GRN=''; DIM=''; OFF=''
if [ -t 1 ]; then
    RED=$(printf '\033[31m'); YEL=$(printf '\033[33m')
    GRN=$(printf '\033[32m'); DIM=$(printf '\033[2m'); OFF=$(printf '\033[0m')
fi
ok()   { printf '%s  OK  %s %s\n' "$GRN" "$OFF" "$1"; }
warn() { printf '%s BRAK %s %s\n' "$YEL" "$OFF" "$1"; }
die()  { printf '%s BŁĄD %s %s\n' "$RED" "$OFF" "$1" >&2; exit 1; }

WANT_QT=0
DO_DESKTOP=0
CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --qt)      WANT_QT=1 ;;
        --desktop) DO_DESKTOP=1 ;;
        --check)   CHECK_ONLY=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) die "nieznany argument: $arg (użyj --help)" ;;
    esac
done

# --- 1. Python >= 3.10 ------------------------------------------------------

find_python() {
    for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
        command -v "$cand" >/dev/null 2>&1 || continue
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
           >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

PY=$(find_python) || die "potrzebny Python 3.10+ (znaleziono: $(python3 -V 2>&1 || echo 'brak'))"
ok "Python: $($PY -V) ($(command -v "$PY"))"

# --- 2. Backend przeglądarki (pywebview) ------------------------------------

HAVE_GTK=0
if "$PY" - <<'EOF' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "3.0")
for ver in ("4.1", "4.0", "6.0"):
    try:
        gi.require_version("WebKit2", ver)
        break
    except ValueError:
        continue
else:
    raise SystemExit(1)
EOF
then
    HAVE_GTK=1
    ok "backend GTK (PyGObject + WebKit2) obecny"
else
    warn "brak PyGObject/WebKit2 — GUI nie ruszy bez backendu"
    printf '%s  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1%s\n' "$DIM" "$OFF"
    printf '%s  Fedora:        sudo dnf install python3-gobject webkit2gtk4.1%s\n' "$DIM" "$OFF"
    printf '%s  Arch:          sudo pacman -S python-gobject webkit2gtk-4.1%s\n' "$DIM" "$OFF"
    printf '%s  Albo: ./install.sh --qt  (backend Qt prosto z pipa)%s\n' "$DIM" "$OFF"
fi

if command -v xdg-open >/dev/null 2>&1; then
    ok "xdg-open: $(command -v xdg-open)"
else
    warn "xdg-open — bez niego „Otwórz folder” nie zadziała (pakiet xdg-utils)"
fi

[ "$CHECK_ONLY" -eq 1 ] && exit 0

# --- 3. venv ----------------------------------------------------------------

if ! "$PY" -c 'import venv' >/dev/null 2>&1; then
    die "brak modułu venv — doinstaluj python3-venv (Debian/Ubuntu)"
fi

if [ ! -x .venv/bin/python ]; then
    printf '\nTworzę środowisko w .venv …\n'
    "$PY" -m venv --system-site-packages .venv || die "nie udało się utworzyć .venv"
else
    printf '\nŚrodowisko .venv już istnieje — aktualizuję zależności.\n'
fi

.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements-linux.txt \
    || die "instalacja zależności nie powiodła się"

if [ "$WANT_QT" -eq 1 ]; then
    .venv/bin/python -m pip install "pywebview[qt]" \
        || die "nie udało się zainstalować backendu Qt"
    ok "backend Qt zainstalowany"
elif [ "$HAVE_GTK" -eq 0 ]; then
    warn "zależności Pythona gotowe, ale wciąż brak backendu GUI"
fi

if .venv/bin/python -c 'import webview' >/dev/null 2>&1; then
    ok "pywebview importuje się poprawnie"
else
    warn "pywebview zainstalowane, ale import pada — sprawdź DEPS.md"
fi

# --- 4. Wpis w menu aplikacji (opcjonalnie) ---------------------------------

if [ "$DO_DESKTOP" -eq 1 ]; then
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    HERE=$(pwd)
    ICON=""
    [ -f assets/favicon.svg ] && ICON="Icon=$HERE/assets/favicon.svg"
    cat > "$APPS/gog-library-manager.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=GOG Library Manager
Comment=Biblioteka, pobieranie i instalacja gier z GOG-a
Exec="$HERE/run.sh"
Path=$HERE
Terminal=false
Categories=Game;Utility;
$ICON
EOF
    chmod 755 "$APPS/gog-library-manager.desktop"
    ok "wpis w menu: $APPS/gog-library-manager.desktop"
fi

printf '\n%sGotowe.%s  Uruchomienie: ./run.sh\n' "$GRN" "$OFF"
printf '%sPrzy pierwszym starcie ustaw katalogi (domyślnie ~/GOG/installers i ~/GOG/games).%s\n' \
    "$DIM" "$OFF"
