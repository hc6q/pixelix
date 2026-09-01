#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


version = required("PIXELIX_VERSION")
published_at = required("PIXELIX_PUBLISHED_AT")
download_url = required("PIXELIX_DOWNLOAD_URL")
ipa_size_raw = os.environ.get("PIXELIX_IPA_SIZE", "").strip()
ipa_size = int(ipa_size_raw) if ipa_size_raw else None
changelog_b64 = os.environ.get("PIXELIX_CHANGELOG_B64", "")
changelog = base64.b64decode(changelog_b64).decode("utf-8", errors="replace").strip() if changelog_b64 else ""
if not changelog:
    changelog = f"Automated iOS build of Pixelix {version}."

repo = os.environ.get("GITHUB_REPOSITORY", "hc6q/pixelix")
raw_base = f"https://raw.githubusercontent.com/{repo}/main"
repo_url = f"https://github.com/{repo}"
icon_url = f"{raw_base}/iosApp/iosApp/Assets.xcassets/AppIcon.appiconset/pixelix_logo_192.png"
screenshot_url = f"{raw_base}/assets/pixelix_screenshots.png"

source_path = Path(os.environ.get("PIXELIX_SOURCE_PATH", "source.json"))
existing_versions = []
if source_path.exists():
    try:
        old = json.loads(source_path.read_text(encoding="utf-8"))
        apps = old.get("apps") or []
        if apps:
            existing_versions = apps[0].get("versions") or []
    except (json.JSONDecodeError, OSError, TypeError):
        existing_versions = []

new_version = {
    "version": version,
    "date": published_at,
    "localizedDescription": changelog,
    "downloadURL": download_url,
    "minOSVersion": "16.2"
}
if ipa_size is not None:
    new_version["size"] = ipa_size

# Replace a version if it was rebuilt, otherwise keep prior releases for downgrade/history.
versions = [v for v in existing_versions if str(v.get("version", "")) != version]
versions.insert(0, new_version)
versions = versions[:30]

app = {
    "name": "Pixelix",
    "bundleIdentifier": "com.daniebeler.pfpixelix.iosApp",
    "developerName": "Ghostbyte",
    "subtitle": "Pixelfed & Vernissage client",
    "localizedDescription": "An open-source client for Pixelfed and Vernissage, built with Compose Multiplatform for browsing, publishing photos and interacting across the federated social web. This IPA is an unofficial automated build of the upstream source code.",
    "versionDescription": changelog,
    "iconURL": icon_url,
    "screenshotURLs": [screenshot_url],
    "versions": versions,
    "version": version,
    "versionDate": published_at,
    "downloadURL": download_url,
    "appPermissions": {}
}
if ipa_size is not None:
    app["size"] = ipa_size

source = {
    "name": "Pixelix iOS — Unofficial Builds",
    "identifier": "dev.hc6q.pixelix-ios-source",
    "subtitle": "Automated Pixelix builds for sideloading",
    "description": "Unofficial unsigned iOS builds of the open-source Pixelix client, automatically compiled from Ghostbyte's upstream releases for use with Feather and other AltStore-compatible source readers.",
    "iconURL": icon_url,
    "website": repo_url,
    "apps": [app],
    "news": []
}

source_path.parent.mkdir(parents=True, exist_ok=True)
source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Updated {source_path} for Pixelix {version} with {len(versions)} version(s).")
