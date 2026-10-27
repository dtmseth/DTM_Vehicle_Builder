using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace DTMStartup
{
    internal static class Program
    {
        private const string AppUserModelId = "DTM.VehicleBuilder";

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern uint SetCurrentProcessExplicitAppUserModelID(string appId);

        [STAThread]
        private static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            try { SetCurrentProcessExplicitAppUserModelID(AppUserModelId); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new StartupForm());
        }
    }

    internal sealed class StartupForm : Form
    {
        private const string ReadySignal = "__DTM_READY__";
        private const int SplashCount = 6;
        private readonly Label productLabel;
        private readonly Label statusLabel;
        private readonly Timer statusTimer;
        private Process appProcess;
        private string statusPath;

        internal StartupForm()
        {
            ClientSize = new Size(960, 540);
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            TopMost = true;
            BackColor = Color.FromArgb(36, 39, 44);
            BackgroundImage = LoadSplashImage();
            BackgroundImageLayout = ImageLayout.None;

            Rectangle area = Screen.FromPoint(Cursor.Position).WorkingArea;
            Location = new Point(
                area.Left + Math.Max(0, (area.Width - Width) / 2),
                area.Top + Math.Max(0, (area.Height - Height) / 2)
            );

            productLabel = new Label();
            productLabel.AutoSize = false;
            productLabel.BackColor = Color.Transparent;
            productLabel.ForeColor = Color.FromArgb(248, 249, 251);
            // Pixel units keep Windows/Parallels DPI scaling from enlarging the
            // glyphs beyond this fixed photographic canvas and clipping them.
            productLabel.Font = new Font(
                "Segoe UI Semibold", 28.0f, FontStyle.Bold, GraphicsUnit.Pixel
            );
            productLabel.Location = new Point(46, 404);
            productLabel.Size = new Size(700, 56);
            productLabel.Text = "Vehicle Builder  " + ReadInstalledVersion();
            productLabel.TextAlign = ContentAlignment.MiddleLeft;
            Controls.Add(productLabel);

            statusLabel = new Label();
            statusLabel.AutoSize = false;
            statusLabel.BackColor = Color.Transparent;
            statusLabel.ForeColor = Color.FromArgb(224, 227, 235);
            statusLabel.Font = new Font(
                "Segoe UI", 18.0f, FontStyle.Regular, GraphicsUnit.Pixel
            );
            statusLabel.Location = new Point(46, 466);
            statusLabel.Size = new Size(820, 42);
            statusLabel.Text = "Starting DTM Vehicle Builder...";
            statusLabel.TextAlign = ContentAlignment.MiddleLeft;
            Controls.Add(statusLabel);

            statusTimer = new Timer();
            statusTimer.Interval = 100;
            statusTimer.Tick += CheckStartupStatus;
            Shown += StartApplication;
            FormClosed += Cleanup;
        }

        private static string ReadInstalledVersion()
        {
            try
            {
                string versionPath = Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory,
                    "_internal",
                    "dtm_buildsheet",
                    "_build_version.txt"
                );
                string version = File.ReadAllText(versionPath).Trim();
                if (!String.IsNullOrEmpty(version))
                {
                    return "v" + version;
                }
            }
            catch { }
            return "";
        }

        private static Image LoadSplashImage()
        {
            string resourceName = "DTMStartupSplash" + (NextSplashIndex() + 1).ToString();
            using (Stream stream = Assembly.GetExecutingAssembly()
                .GetManifestResourceStream(resourceName))
            {
                if (stream == null)
                {
                    return null;
                }
                using (Image source = Image.FromStream(stream))
                {
                    return new Bitmap(source);
                }
            }
        }

        private static int NextSplashIndex()
        {
            try
            {
                string stateDirectory = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "DTM Vehicle Builder"
                );
                Directory.CreateDirectory(stateDirectory);
                string stateFile = Path.Combine(stateDirectory, "startup-splash-index.txt");
                int previous = -1;
                if (File.Exists(stateFile))
                {
                    Int32.TryParse(File.ReadAllText(stateFile).Trim(), out previous);
                }
                int next = (Math.Max(previous, -1) + 1) % SplashCount;
                File.WriteAllText(stateFile, next.ToString());
                return next;
            }
            catch
            {
                return (int)(DateTime.UtcNow.Ticks % SplashCount);
            }
        }

        private void StartApplication(object sender, EventArgs args)
        {
            Refresh();
            BeginInvoke(new Action(delegate
            {
                try
                {
                    statusPath = Path.Combine(
                        Path.GetTempPath(),
                        "dtm-startup-" + Guid.NewGuid().ToString("N") + ".status"
                    );
                    string appDirectory = AppDomain.CurrentDomain.BaseDirectory;
                    ProcessStartInfo startInfo = new ProcessStartInfo();
                    startInfo.FileName = Path.Combine(appDirectory, "DTM Vehicle Builder.exe");
                    startInfo.WorkingDirectory = appDirectory;
                    startInfo.UseShellExecute = false;
                    startInfo.EnvironmentVariables["DTM_STARTUP_SPLASH_STATUS_FILE"] = statusPath;
                    appProcess = Process.Start(startInfo);
                    statusTimer.Start();
                }
                catch
                {
                    Close();
                }
            }));
        }

        private void CheckStartupStatus(object sender, EventArgs args)
        {
            try
            {
                if (!String.IsNullOrEmpty(statusPath) && File.Exists(statusPath))
                {
                    string status = File.ReadAllText(statusPath).Trim();
                    if (status == ReadySignal)
                    {
                        Close();
                        return;
                    }
                    if (!String.IsNullOrEmpty(status))
                    {
                        statusLabel.Text = status;
                    }
                }
                if (appProcess != null && appProcess.HasExited)
                {
                    Close();
                }
            }
            catch
            {
                // A simultaneous status-file replacement is harmless; retry.
            }
        }

        private void Cleanup(object sender, FormClosedEventArgs args)
        {
            statusTimer.Stop();
            if (!String.IsNullOrEmpty(statusPath))
            {
                try { File.Delete(statusPath); } catch { }
            }
            if (BackgroundImage != null)
            {
                BackgroundImage.Dispose();
            }
        }
    }
}
