#!/usr/bin/env bash
# Build deploy/vscode-extension into a .vsix (a zip with a manifest; no npm needed)
# and install it into VS Code. Reload open VS Code windows to start it.
# Remove: code --uninstall-extension tars.tars-bridge
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${TMPDIR:-/tmp}/tars-bridge.vsix"
python3 - "$REPO/deploy/vscode-extension" "$OUT" <<'PY'
import json, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
pkg = json.load(open(f"{src}/package.json"))
manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}"/>
    <DisplayName>{pkg['displayName']}</DisplayName>
    <Description xml:space="preserve">{pkg['description']}</Description>
    <Categories>Other</Categories>
    <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}"/></Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>"""
types = ('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/>'
         '<Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>')
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", types)
    z.writestr("extension.vsixmanifest", manifest)
    for f in ("package.json", "extension.js"):
        z.write(f"{src}/{f}", f"extension/{f}")
PY
code --install-extension "$OUT" --force
rm -f "$OUT"
