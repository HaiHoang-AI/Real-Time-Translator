using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace RealTimeTranslator
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string venvPythonW = Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe");
            string venvPython = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");

            string targetExe = null;
            if (File.Exists(venvPythonW))
            {
                targetExe = venvPythonW;
            }
            else if (File.Exists(venvPython))
            {
                targetExe = venvPython;
            }

            string appArgs = "-m rtt.app";
            if (args.Length > 0)
            {
                appArgs += " " + string.Join(" ", args);
            }
            else
            {
                appArgs += " --src en --tgt vi";
            }

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.WorkingDirectory = baseDir;

            if (targetExe != null)
            {
                psi.FileName = targetExe;
                psi.Arguments = appArgs;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
            }
            else
            {
                // Fallback to uv run if .venv is not populated
                psi.FileName = "cmd.exe";
                psi.Arguments = "/c uv run python -m rtt.app" + (args.Length > 0 ? " " + string.Join(" ", args) : " --src en --tgt vi");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
            }

            try
            {
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Không thể khởi chạy Real-Time Translator:\n" + ex.Message, "Real-Time Translator Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
