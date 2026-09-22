# Packaging

## Goal

Package the GUI-first app for macOS and Windows without changing how the core code is developed.

## Approach

- Keep application code in `src/dtm_buildsheet/`
- Keep packaging-specific files in `packaging/`
- Keep icons in `packaging/icons/`
- Keep the writable workspace outside the bundled app when packaged

## Current Choice

`PyInstaller` is the production packaging target for both platforms. macOS builds produce a DMG;
Windows builds use Inno Setup around the PyInstaller output.

## Build Entry

- macOS build script:
  `packaging/build_macos.sh`
- Windows build script:
  `packaging/build_windows.ps1`
- Shared PyInstaller spec:
  `packaging/pyinstaller/DTM_VehicleBuilder.spec`

## Icons

Place the app icons here:

- `packaging/icons/app.icns` for macOS
- `packaging/icons/app.ico` for Windows

You can replace them later at any time without touching the app code.
Just overwrite those files and rebuild.

## Output

PyInstaller outputs will be created under:

- `build/`
- `dist/`

Those are ignored by git.

GitHub Actions builds both platforms on pushes to `main`. The manual release workflow publishes the
version tag and release, uploads the platform installers, stages installers/release metadata in
SharePoint, and feeds the in-app update path. See `DEVELOPMENT.md` and `VERSIONING.md` before a
release.

## macOS Signing and Keychain Identity

Development builds are ad-hoc signed. That identity changes when the executable changes, so macOS
cannot carry an `Always Allow` Keychain decision from one build to the next. Internal releases use
one long-lived, self-signed Code Signing identity to give every version the same designated
requirement. This costs nothing and is sufficient for stable local Keychain ACLs, but it is not
Apple notarization: a new workstation may require the user to right-click the app and choose Open.

Create the identity once in Keychain Access with Certificate Assistant > Create a Certificate:

- Name: `DTM Vehicle Builder Internal Signing`
- Identity Type: `Self Signed Root`
- Certificate Type: `Code Signing`
- Enable `Let me override defaults` and choose a long validity period

Keep the certificate and private key permanently. Export the complete identity from My Certificates
as a password-protected `.p12`; losing or replacing it changes the app's identity and causes macOS
to ask for Keychain access again.

Manual release runs require these GitHub Actions secrets:

- `MACOS_CERTIFICATE`: base64-encoded self-signed `.p12`
- `MACOS_CERTIFICATE_PASSWORD`: password used when exporting the `.p12`
- `MACOS_KEYCHAIN_PASSWORD`: random password used only for the ephemeral CI keychain
- `MACOS_CODESIGN_IDENTITY`: exact certificate name, normally `DTM Vehicle Builder Internal Signing`

The release job imports and temporarily trusts the certificate in an isolated CI keychain, builds
the app ad-hoc, then re-signs the complete app and DMG with the internal identity. It deliberately
does not use Apple notarization or timestamp services. The temporary keychain is deleted after the
job. Push builds remain ad-hoc development artifacts; do not distribute them as production updates
because doing so would change the app's designated requirement and restart Keychain prompts.

For a local internal-signed build, import the same identity into the login keychain and run:

```bash
DTM_INTERNAL_CODESIGN_IDENTITY="DTM Vehicle Builder Internal Signing" \
  bash packaging/build_macos.sh
```

`DTM_MAC_CODESIGN_IDENTITY` remains available for a future Developer ID build, but it is not used
by the free internal release workflow.
