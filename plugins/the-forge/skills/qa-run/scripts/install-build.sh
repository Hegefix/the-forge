#!/usr/bin/env bash
# Installs a build on a booted simulator or emulator. Explains what to do when the build can't run there.
# Usage: install-build.sh <ios|android> <device-id> <build file>
#   ios: a simulator .app folder, or a .zip / .tar.gz that contains one. Android: an .apk, or a .zip that contains one.
set -uo pipefail
[ $# -eq 3 ] || { sed -n 2,5p "$0"; exit 2; }
plat=$1; dev=$2; src=$3
work=$(mktemp -d "${TMPDIR:-/tmp}/qa-build.XXXXXX"); trap 'rm -rf "$work"' EXIT

unpack() { # extract an archive into $work
  case "$1" in
    *.zip) unzip -q "$1" -d "$work" ;;
    *.tar.gz|*.tgz) tar -xzf "$1" -C "$work" ;;
  esac
}

case "$plat" in
  ios)
    case "$src" in
      *.ipa) echo "BLOCKED: an .ipa (TestFlight / App Store build) can't run on a simulator. Ask the developers for a simulator build (.app) of the same commit."; exit 3 ;;
      *.zip|*.tar.gz|*.tgz) unpack "$src"; app=$(find "$work" -maxdepth 4 -name '*.app' -type d | head -1) ;;
      *.app) app=$src ;;
      *) echo "Unknown iOS build type: $src"; exit 2 ;;
    esac
    [ -n "${app:-}" ] || { echo "No .app found in $src"; exit 2; }
    plist="$app/Info.plist"
    # A device build has an embedded provisioning profile; a simulator build never does.
    [ -f "$app/embedded.mobileprovision" ] && { echo "BLOCKED: this .app is built for real devices (it carries a provisioning profile). Ask for a simulator build."; exit 3; }
    xcrun simctl install "$dev" "$app" && echo "installed on $dev: $(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$plist" 2>/dev/null)"
    ;;
  android)
    case "$src" in
      *.aab) echo "BLOCKED: an .aab can't be installed directly. Ask for an APK, or build one with bundletool (references/setup-mac.md)."; exit 3 ;;
      *.zip) unpack "$src"; apk=$(find "$work" -maxdepth 4 -name '*.apk' | head -1) ;;
      *.apk) apk=$src ;;
      *) echo "Unknown Android build type: $src"; exit 2 ;;
    esac
    [ -n "${apk:-}" ] || { echo "No .apk found in $src"; exit 2; }
    adb -s "$dev" install -r "$apk" && echo "installed on $dev"
    ;;
  *) sed -n 2,5p "$0"; exit 2 ;;
esac
