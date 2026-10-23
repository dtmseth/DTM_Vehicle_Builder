# Simple Parallels Updater Test

This tests the updater only inside your Parallels Windows VM. It does not change the version in
`pyproject.toml`, publish a release, or upload either disposable installer to SharePoint. The app
uses its normal cloud sign-in so the visible experience matches production.

## Before you start

1. Take a Parallels snapshot. This is your undo button.
2. Close DTM Vehicle Builder.
3. Open PowerShell in the Windows copy of this repository.

The first attempt checks for Python and Inno Setup, which are required to create Windows
installers. If either is missing, it prints the exact one-time `winget` install command. Install
those tools, close and reopen PowerShell, then run the test command again. On an ARM-based
Parallels VM, the helper also checks that x64 Python is installed so the test package matches the
x64 Windows build used by DTM customers.

## Run one command

```powershell
.\packaging\test_windows_updater.cmd
```

The script builds the frozen app once, makes two disposable installers from it, installs the first,
opens DTM, and places the second in DTM's local update queue. The first run can still take a few
minutes, but later runs reuse the local build cache. Wait until PowerShell says `READY`. The command
launcher bypasses PowerShell's script restriction only for this one test; it does not change the
Windows execution policy.

## Check four things

1. Wait up to one minute for the update banner in DTM.
2. Sign in normally. Do not create or publish real work during this updater-only test.
3. Click **Restart & Install**. The DTM window must disappear before installer progress appears;
   then DTM should reopen by itself.
4. Confirm the newer version appears in DTM and you can sign in again.

A normal app close uses the quieter path: it installs the ready update without showing the installer
and leaves DTM closed. That behavior is covered by the focused automated updater test so this first
Parallels check can stay short.

That is the first test. If any step fails, stop and send the PowerShell error or a photo of what you
see. Keep Windows Defender, SmartScreen, and the firewall enabled; photograph a warning instead of
disabling security.

## When finished

Restore the Parallels snapshot. That removes the disposable installation and test data.

If you cannot restore the snapshot, this command only clears the two test environment settings:

```powershell
.\packaging\test_windows_updater.cmd -Cleanup
```

It does not remove the test installation, which is why restoring the snapshot is preferred.
