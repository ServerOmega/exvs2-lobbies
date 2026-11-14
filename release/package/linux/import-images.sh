#!/usr/bin/env bash
# Import card-website pictures from the official Server-Infinite v1.2.0 release
# into a built matchmaking server. Copies only wwwroot/images.
# Never changes Configurations/ or ServerInfinite.db unless you pass --database
# (and even then it will not overwrite an existing database).
#
# Usage:
#   ./linux/import-images.sh /path/to/Server-Infinite-v1.2.0.zip
#   ./linux/import-images.sh /path/to/official-folder
#   ./linux/import-images.sh /path/to/official-folder /path/to/server-linux
#   ./linux/import-images.sh /path/to/official-folder --database
#   ./linux/import-images.sh /path/to/official-folder --force   # overwrite existing pictures only
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
SERVER_DIR="${SERVER_DIR:-$ROOT/server-linux}"
FORCE=0
COPY_DB=0
SRC=""

usage() {
  cat <<EOF
Usage: $0 <official-folder-or-zip> [server-dir] [--force] [--database]

Copies only wwwroot/images from the official Server-Infinite v1.2.0 release
into the built server. Does not copy the official program, and does not change
Configurations/ or ServerInfinite.db unless you pass --database.

  --force      overwrite picture files that are already in the server folder
  --database   copy ServerInfinite.db only if the destination does not already have one

Pictures: https://github.com/Chiang-17/EXVS2-IB-Server/releases/tag/v1.2.0
EOF
}

fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --force) FORCE=1; shift ;;
    --database) COPY_DB=1; shift ;;
    --) shift; break ;;
    -*) fail "Unknown option: $1  (try --help)" ;;
    *)
      if [ -z "$SRC" ]; then
        SRC="$1"
      else
        SERVER_DIR="$1"
      fi
      shift
      ;;
  esac
done

[ -n "$SRC" ] || { usage; exit 1; }
[ -e "$SRC" ] || fail "Path not found: $SRC"
[ -d "$SERVER_DIR/wwwroot" ] || fail "No wwwroot folder in '$SERVER_DIR'. Build the server first (./linux/build-server.sh), or pass the server folder as the second argument."

DEST="$SERVER_DIR/wwwroot/images"
mkdir -p "$DEST"
echo "EXVS2 matchmaking server - import pictures"
echo "    Server folder: $SERVER_DIR"
echo "    Pictures go to: $DEST"

looks_like_images() {
  local d="$1"
  [ -d "$d" ] || return 1
  [ -d "$d/mobile_suits" ] || [ -d "$d/pilots" ] || [ -d "$d/titles" ] || [ -d "$d/navis" ] || [ -d "$d/sticker" ] && return 0
  ls "$d"/*.webp "$d"/*.WEBP >/dev/null 2>&1
}

find_images_dir() {
  local base="$1" d
  for d in "$base/wwwroot/images" "$base/images"; do
    looks_like_images "$d" && { printf '%s\n' "$d"; return 0; }
  done
  for d in "$base"/*/wwwroot/images "$base"/*/images; do
    looks_like_images "$d" && { printf '%s\n' "$d"; return 0; }
  done
  looks_like_images "$base" && { printf '%s\n' "$base"; return 0; }
  return 1
}

official_root_from_images() {
  local images="$1" parent
  if [ "$(basename "$images")" = images ]; then
    parent="$(dirname "$images")"
    if [ "$(basename "$parent")" = wwwroot ]; then
      dirname "$parent"
      return
    fi
    printf '%s\n' "$parent"
    return
  fi
  printf '%s\n' "$images"
}

# Lowercase only the file extension (.WEBP -> .webp). The website asks for .webp,
# and Linux is case-sensitive. No two official files collide when this is applied.
dest_relpath() {
  local rel="$1" dir base name ext
  dir="$(dirname "$rel")"
  base="$(basename "$rel")"
  case "$base" in
    *.*)
      name="${base%.*}"
      ext="$(printf '%s' "${base##*.}" | tr 'A-Z' 'a-z')"
      if [ "$dir" = . ]; then printf '%s
' "$name.$ext"; else printf '%s
' "$dir/$name.$ext"; fi
      ;;
    *)
      printf '%s
' "$rel"
      ;;
  esac
}

copy_images() {
  local src="$1" dest="$2" f rel d copied=0
  while IFS= read -r -d '' f; do
    rel="${f#"$src"/}"
    d="$dest/$(dest_relpath "$rel")"
    if [ -e "$d" ] && [ "$FORCE" != 1 ]; then
      continue
    fi
    mkdir -p "$(dirname "$d")"
    cp -f "$f" "$d"
    copied=$((copied + 1))
  done < <(find "$src" -type f -print0)
  printf '%s
' "$copied"
}

# If an older copy left both 103_0.WEBP and 103_0.webp, drop the uppercase-ext leftover.
drop_uppercase_ext_duplicates() {
  local dir="$1" f new n
  find "$dir" -type f \( -name '*.WEBP' -o -name '*.PNG' -o -name '*.JPG' -o -name '*.JPEG' \) -print0 |
  while IFS= read -r -d '' f; do
    n="${f##*/}"
    new="$(dirname "$f")/${n%.*}.$(printf '%s' "${n##*.}" | tr 'A-Z' 'a-z')"
    if [ "$f" != "$new" ] && [ -e "$new" ]; then
      rm -f "$f"
    elif [ "$f" != "$new" ]; then
      mv "$f" "$new"
    fi
  done
}

TMP=""
cleanup() { if [ -n "${TMP:-}" ] && [ -d "$TMP" ]; then rm -rf "$TMP"; fi; }
trap cleanup EXIT

OFFICIAL_ROOT=""
COPIED=0

if [ -f "$SRC" ] && [[ "${SRC,,}" == *.zip ]]; then
  command -v unzip >/dev/null || fail "'unzip' is not installed. Install it first (e.g. sudo apt install unzip)."
  echo "    Reading pictures from the zip (only wwwroot/images; the official program is not copied)..."
  if ! unzip -l "$SRC" | grep -q 'wwwroot/images/'; then
    fail "No wwwroot/images files found in the zip. Is this Server-Infinite-v1.2.0.zip from https://github.com/Chiang-17/EXVS2-IB-Server/releases/tag/v1.2.0 ?"
  fi
  TMP="$(mktemp -d "${TMPDIR:-/tmp}/exvs2-images.XXXXXX")"
  # Official zip has wwwroot/images at the root; some extractors add a wrapper folder.
  # -o: overwrite without prompting (needed if a glob is listed twice).
  if unzip -Z -1 "$SRC" 2>/dev/null | grep -q '^wwwroot/images/'; then
    unzip -qo "$SRC" 'wwwroot/images/*' -d "$TMP"
  else
    unzip -qo "$SRC" '*/wwwroot/images/*' -d "$TMP"
  fi
  IMAGES="$(find_images_dir "$TMP")" || fail "Unzipped the zip but could not find wwwroot/images inside it."
  echo "    Found pictures in the zip."
else
  [ -d "$SRC" ] || fail "Not a folder or zip: $SRC"
  SRC="$(cd "$SRC" && pwd)"
  IMAGES="$(find_images_dir "$SRC")" || fail "Could not find wwwroot/images under '$SRC'. Extract Server-Infinite-v1.2.0.zip and point at the folder that contains Server-Infinite.exe and wwwroot."
  OFFICIAL_ROOT="$(official_root_from_images "$IMAGES")"
  echo "    Found pictures in: $IMAGES"
fi

# Copy. --force overwrites pictures only; default fills in missing files.
# Extensions are lowercased on the destination so Linux can serve what the website requests.
COPIED="$(copy_images "$IMAGES" "$DEST")"
drop_uppercase_ext_duplicates "$DEST"
if [ "$FORCE" = 1 ]; then
  echo "    Copied / updated $COPIED picture files."
else
  echo "    Copied $COPIED new picture files (existing files were left as they were)."
fi
TOTAL="$(find "$DEST" -type f | wc -l)"
echo "    Pictures in server folder now: $TOTAL files."

if [ "$COPY_DB" = 1 ]; then
  if [ -z "$OFFICIAL_ROOT" ]; then
    echo "    The official v1.2.0 zip does not include a card database. Point at an official folder you have already used if you want to copy ServerInfinite.db."
  else
    OFF_DB="$OFFICIAL_ROOT/ServerInfinite.db"
    NEW_DB="$SERVER_DIR/ServerInfinite.db"
    if [ ! -f "$OFF_DB" ]; then
      echo "    No ServerInfinite.db in the official folder."
    elif [ -f "$NEW_DB" ]; then
      echo "    Your server already has ServerInfinite.db - left it alone (this script never overwrites the database)."
    else
      cp "$OFF_DB" "$NEW_DB"
      echo "    Card database copied (it gets one new column on first start). The original is unchanged."
    fi
  fi
fi

printf '\nDone. Hard-reload the card website (Ctrl+F5). If pictures still don'\''t show, restart the server and try again.\n'
echo "Check:  http://127.0.0.1:28080/images/mobile_suits/0.webp"
