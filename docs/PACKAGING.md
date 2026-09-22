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
- Include **Key Usage: Digital Signature** and **Extended Key Usage: Code Signing**.
  Extended Key Usage alone is insufficient for the macOS signing policy.

Keep the certificate and private key permanently. Export the complete identity from My Certificates
as a password-protected `.p12`; losing or replacing it changes the app's identity and causes macOS
to ask for Keychain access again.

Manual release runs require these GitHub Actions secrets:

- `MACOS_CERTIFICATE`: base64-encoded self-signed `.p12`
- `MACOS_CERTIFICATE_PASSWORD`: password used when exporting the `.p12`
- `MACOS_KEYCHAIN_PASSWORD`: random password used only for the ephemeral CI keychain
- `MACOS_CODESIGN_IDENTITY`: exact certificate name, normally `DTM Vehicle Builder Internal Signing`

The release job imports the identity into an isolated CI keychain, validates the certificate's
code-signing policy, and trusts its public certificate in the disposable runner's admin trust
domain. It builds
the app ad-hoc, then re-signs the complete app and DMG with the internal identity. It deliberately
does not use Apple notarization or timestamp services. The temporary keychain is deleted after the
job. Push builds remain ad-hoc development artifacts; do not distribute them as production updates
because doing so would change the app's designated requirement and restart Keychain prompts.

An imported private key or an entry in `security find-identity -v` is not sufficient proof that
`codesign` can use the identity. Validate the public self-signed certificate explicitly with
`security verify-cert -c certificate.pem -r certificate.pem -p codeSign -L`, then require a real
sign-and-verify probe. `Invalid Key Usage for policy` means the certificate must be reissued with
Digital Signature Key Usage; changing the import flags, keychain search list, or runner image
does not repair it. Reissuing changes the certificate fingerprint even when retaining the private
key, so keep the original export and update the CI `.p12` only after the new identity passes the
signing probe.

For a local internal-signed build, import the same identity into the login keychain and run:

```bash
DTM_INTERNAL_CODESIGN_IDENTITY="DTM Vehicle Builder Internal Signing" \
  bash packaging/build_macos.sh
```

`DTM_MAC_CODESIGN_IDENTITY` remains available for a future Developer ID build, but it is not used
by the free internal release workflow.
