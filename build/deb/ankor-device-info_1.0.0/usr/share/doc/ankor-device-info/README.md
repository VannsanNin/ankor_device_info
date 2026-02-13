# Hardware Monitor (PyQt6 / PySide6)

Cross-platform desktop app (Linux + Windows) that shows live:
- CPU usage
- CPU temperature (when exposed by OS/sensors)
- RAM usage
- Swap usage
- Disk usage
- Network upload/download rate
- GPU usage + temperature (NVIDIA, optional)
- Optional always-on-screen overlay for CPU temp, GPU temp, and RAM usage
- Modern dark/light UI toggle
- Saved preferences (theme, overlay enabled state, window positions)

## 1) Create virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux
# .venv\Scripts\activate    # Windows PowerShell
```

## 2) Install dependencies

Install shared dependencies:

```bash
pip install -r requirements.txt
```

Choose one GUI binding:

```bash
pip install PySide6
```

or

```bash
pip install PyQt6
```

## 3) Run

```bash
python main.py
```

In the app, enable:
- `Pinned Overlay` to open a mini always-on-top panel.
- `Dark Theme` to switch between dark/light modern styles.

The app remembers:
- main window size/position
- overlay position
- last selected theme and overlay enabled state

## Notes

- CPU temperature depends on your hardware/driver exposure.
  - Linux usually works with `lm-sensors` configured.
  - On Windows, CPU temp may show `N/A` without additional vendor interfaces.
- GPU metrics require NVIDIA driver + `pynvml` (already in requirements).

## Build a `.deb`

Prerequisites (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y dpkg-dev
```

Build:

```bash
chmod +x scripts/build_deb.sh
./scripts/build_deb.sh 1.0.0
```

Output:

- `dist/ankor-device-info_1.0.0_all.deb`

Install locally for test:

```bash
sudo apt-get install -y ./dist/ankor-device-info_1.0.0_all.deb
ankor-device-info
```

## Generate and host an APT repository

Prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y dpkg-dev apt-utils
```

Generate repo files from local `.deb` artifacts:

```bash
chmod +x scripts/publish_apt_repo.sh
./scripts/publish_apt_repo.sh ./dist ./apt-repo
```

Serve it as static files (local quick test):

```bash
python3 -m http.server --directory ./apt-repo 8080
```

Client setup (unsigned repo):

```bash
echo "deb [trusted=yes] http://YOUR_HOST:8080 stable main" | \
  sudo tee /etc/apt/sources.list.d/ankor-device-info.list
sudo apt-get update
sudo apt-get install -y ankor-device-info
```

### Signed repository (recommended)

Generate signed metadata:

```bash
GPG_KEY_ID="YOUR_KEY_ID" ./scripts/publish_apt_repo.sh ./dist ./apt-repo
gpg --armor --export "YOUR_KEY_ID" > ./apt-repo/ankor-archive-keyring.asc
```

Client setup (signed-by keyring):

```bash
curl -fsSL http://YOUR_HOST:8080/ankor-archive-keyring.asc | \
  sudo gpg --dearmor -o /usr/share/keyrings/ankor-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/ankor-archive-keyring.gpg] http://YOUR_HOST:8080 stable main" | \
  sudo tee /etc/apt/sources.list.d/ankor-device-info.list
sudo apt-get update
sudo apt-get install -y ankor-device-info
```

## Publish to Ubuntu App Center (Snap)

Ubuntu App Center publishes desktop apps from the Snap Store.

### 1) Build locally

Install Snapcraft (Ubuntu):

```bash
sudo snap install snapcraft --classic
```

Build:

```bash
snapcraft
```

Install for local test:

```bash
sudo snap install --dangerous ./ankor-device-info_*.snap
```

Optional interface connections for richer hardware metrics:

```bash
sudo snap connect ankor-device-info:hardware-observe
sudo snap connect ankor-device-info:system-observe
sudo snap connect ankor-device-info:network-observe
```

### 2) Register and publish

```bash
snapcraft login
snapcraft register ankor-device-info
snapcraft upload --release=stable ./ankor-device-info_*.snap
```

### 3) App Center listing quality

In the Snap Store dashboard, add:
- app icon (512x512)
- screenshots
- clear description and categories

These listing assets are what users see in Ubuntu App Center.

### 4) Before first release

- If `ankor-device-info` is already taken, change `name:` in `snap/snapcraft.yaml`.
- Update `version:` in `snap/snapcraft.yaml` for each release.
- Current snap packaging includes `PySide6` as the Qt binding.
