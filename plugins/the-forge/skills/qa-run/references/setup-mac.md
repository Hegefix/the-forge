# Set up a Mac for QA runs

Do this once. About 60 GB of free disk is needed (Xcode and its simulators about 30–40 GB, Android Studio and a few AVDs about 20 GB). Check with `df -h /`. Claude Code can run most commands below for you; the installs from the App Store and the first Xcode and Android Studio launches are clicks.

## 1. iOS: Xcode and simulators

1. Install Xcode from the App Store. Open it once and accept the license. Then: `sudo xcode-select -s /Applications/Xcode.app` and `xcodebuild -runFirstLaunch`.
2. Xcode, Settings, Components (or Platforms): download the current iOS simulator runtime. Add an older runtime only if a ticket needs it (each is about 8 GB).
3. See what exists: `xcrun simctl list devices available`. Create an iPad when there is none: `xcrun simctl create "iPad QA" "iPad Pro 11-inch (M4)" <runtime id from xcrun simctl list runtimes>` (the device-type name must be one `xcrun simctl list devicetypes` prints).
4. Simulators cannot run TestFlight or App Store builds. You need a simulator `.app` from the developers or CI. Install: `scripts/install-build.sh ios <udid> <build>`.

## 2. Android: Android Studio and emulators

1. Install Android Studio, open it once, finish the setup wizard (it installs the SDK).
2. SDK Manager: install Android SDK Platform-Tools, Emulator, and the system images you need. Choose the **arm64** (Apple silicon) images. Typical set: one recent phone image, one tablet image, and one or two older API levels that match the oldest devices users still have.
3. Device Manager: create AVDs: a phone, a tablet (a "Pixel Tablet" profile), and one per older API level. Name them clearly, for example `phone-api36`, `tablet-api36`, `phone-api29`.
4. Add the tools to the shell: in `~/.zshrc`, `export ANDROID_HOME="$HOME/Library/Android/sdk"` and `export PATH="$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"`. Open a new terminal. `adb version` and `emulator -list-avds` must work.
5. An `.aab` can't be installed. Ask for an APK, or use bundletool: `java -jar bundletool.jar build-apks --bundle=app.aab --output=app.apks --mode=universal` and `unzip app.apks universal.apk`.

## 3. Java 17

`brew install openjdk@17`, then `sudo ln -sfn "$(brew --prefix)/opt/openjdk@17/libexec/openjdk.jdk" /Library/Java/JavaVirtualMachines/openjdk-17.jdk`. Check: `java -version` shows 17 or newer.

## 4. Maestro

```
brew install mobile-dev-inc/tap/maestro
maestro --version
```

Keep the tap prefix. Plain `brew install maestro` installs a different app.

## 5. Claude Code connectors

- **Atlassian (Jira):** in Claude Code run `/mcp`, pick the Atlassian server, and sign in in the browser. Without it the skill can't read or comment on tickets.
- Chat and other connectors are not needed. The skill never writes to chat.
- For web tickets, install the Claude in Chrome extension, or a browser-testing skill if your team has one.

## 6. Project config and check

Copy `templates/qa-run.json` to the project's `.claude/qa-run.json` and fill it (`config.md`). Then run `bash scripts/preflight.sh`. It must end without a `MISSING` line.

## Disk space notes

- Delete simulators and runtimes you don't use: `xcrun simctl delete unavailable`, and Xcode's Components list.
- `xcrun simctl erase all` resets every simulator to factory state. Use it only when no run is in progress.
- Emulators grow with use. Wipe data in Device Manager when one gets slow, and delete AVDs you no longer test on.
- Evidence folders hold videos. Move finished ones to the tracker and clear the local copy.
