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
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [STAThread]
        private static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new StartupForm());
        }
    }

    internal sealed class StartupForm : Form
    {
        private const string ReadySignal = "__DTM_READY__";
        private readonly Label statusLabel;
        private readonly Timer statusTimer;
        private Process appProcess;
        private string statusPath;

        internal StartupForm()
        {
            ClientSize = new Size(560, 300);
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

            statusLabel = new Label();
            statusLabel.AutoSize = false;
            statusLabel.BackColor = Color.Transparent;
            statusLabel.ForeColor = Color.FromArgb(242, 244, 251);
            statusLabel.Font = new Font("Segoe UI", 10.0f, FontStyle.Regular);
            statusLabel.Location = new Point(30, 252);
            statusLabel.Size = new Size(500, 32);
            statusLabel.Text = "Starting DTM Vehicle Builder...";
            statusLabel.TextAlign = ContentAlignment.MiddleLeft;
            Controls.Add(statusLabel);

            statusTimer = new Timer();
            statusTimer.Interval = 100;
            statusTimer.Tick += CheckStartupStatus;
            Shown += StartApplication;
            FormClosed += Cleanup;
        }

        private static Image LoadSplashImage()
        {
            using (Stream stream = Assembly.GetExecutingAssembly()
                .GetManifestResourceStream("DTMStartupSplash"))
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
