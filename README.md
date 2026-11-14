# Wanderpin

Set your iPhone's GPS location from your PC. Pick a place on a map, save favourite spots, or play a route at walking, biking or driving speed.

It uses [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), a free open-source library, to talk to Apple's developer location-simulation service (the same one Xcode uses). Nothing on the phone is jailbroken or modified.

## What you need
- An iPhone or iPad on **iOS 17.4 or newer**
- **Developer Mode** on: Settings → Privacy & Security → Developer Mode (the phone restarts). If the option is missing, connect the phone to this PC once by USB first.
- **Python 3.10+** on Windows, with "Add python.exe to PATH" ticked when installing
- A USB cable for setup

## Use it
1. Double-click `start.bat`. The first run installs what it needs; then your browser opens the app.
2. Plug in and unlock the iPhone, and tap **Trust** if asked.
3. Click **Start phone connection** and approve the admin prompt. A console window opens; leave it running.
4. Click **Connect**.
5. Click the map (or search) and press **Set location**. **Real GPS** switches back.

Keep the app window open while you spoof. Closing it, or the phone disconnecting, hands the phone back its real GPS. Restarting the phone always does too.

## Routes
Tick **Route mode**, click points in order, choose Walk / Bike / Drive and press **Play route**. "Follow roads" snaps the path to real roads using the public OSRM demo server; untick it to move in straight lines.

## Updates
Each time Wanderpin opens it checks GitHub for a newer version. If there is one, an **Update now** box appears; it downloads the new version, checks its checksum, swaps it in and restarts. Saved spots are kept.

### Publishing a new version (for whoever maintains it)
One-time setup:
1. Make a free account at github.com and create a **public** repository named `wanderpin`.
2. In `app.py`, set `UPDATE_REPO = "your-github-name/wanderpin"`, then build and install from that copy so installed apps know where to look.

Every new version:
1. Make your changes.
2. In PowerShell in this folder run `.\make_release.ps1 -Version 1.0.1 -Notes "What changed"`.
3. If the GitHub CLI (`gh`) is installed and signed in, say `y` to publish. Otherwise follow the printed steps to upload `dist\Wanderpin-Setup.zip` and `dist\Wanderpin-Setup.zip.sha256` to a new release tagged `v1.0.1`.

## Where things are stored
Saved spots: `%LOCALAPPDATA%\Wanderpin\spots.json`. Python environment: `%LOCALAPPDATA%\Wanderpin\venv` (delete it to reinstall).

## Heads-up
Some apps and games detect impossible movement and may restrict accounts. Using a fake location can break those apps' rules; that's on you.
