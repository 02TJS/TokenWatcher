using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

internal static class TokenWatcherLauncher
{
    private const uint AttachParentProcess = 0xFFFFFFFF;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtimeDirectory = Path.Combine(root, "TokenWatcher.runtime");
        string executable = Path.Combine(runtimeDirectory, "TokenWatcher.exe");

        if (!File.Exists(executable))
        {
            MessageBox.Show(
                "TokenWatcher.runtime\\TokenWatcher.exe is missing. Rebuild or extract the complete TokenWatcher package.",
                "TokenWatcher",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 2;
        }

        try
        {
            bool wait = ShouldWait(args);
            if (wait)
            {
                AttachConsole(AttachParentProcess);
            }
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = executable,
                WorkingDirectory = root,
                UseShellExecute = false,
                Arguments = BuildArguments(args)
            };
            Process process = Process.Start(startInfo);
            if (process == null)
            {
                return 3;
            }

            if (wait)
            {
                process.WaitForExit();
                return process.ExitCode;
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "Unable to start TokenWatcher:\n" + error.Message,
                "TokenWatcher",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 4;
        }
    }

    private static bool ShouldWait(string[] args)
    {
        foreach (string arg in args)
        {
            if (string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(arg, "--snapshot-json", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(arg, "--screenshot", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(arg, "--help", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(arg, "-h", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    private static string BuildArguments(string[] args)
    {
        StringBuilder commandLine = new StringBuilder();
        foreach (string arg in args)
        {
            if (commandLine.Length > 0)
            {
                commandLine.Append(' ');
            }
            commandLine.Append(QuoteArgument(arg));
        }
        return commandLine.ToString();
    }

    private static string QuoteArgument(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0)
        {
            return arg;
        }

        StringBuilder quoted = new StringBuilder();
        quoted.Append('"');
        int backslashes = 0;
        foreach (char character in arg)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }

            if (character == '"')
            {
                quoted.Append('\\', backslashes * 2 + 1);
                quoted.Append('"');
                backslashes = 0;
                continue;
            }

            quoted.Append('\\', backslashes);
            backslashes = 0;
            quoted.Append(character);
        }
        quoted.Append('\\', backslashes * 2);
        quoted.Append('"');
        return quoted.ToString();
    }
}
