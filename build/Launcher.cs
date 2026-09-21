using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Threading;
class Launcher {
    static int Main(string[] args) {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        bool created;
        using (var mutex = new Mutex(true, "Local\\MetaverseLocalInstaller", out created)) {
            if (!created) { Console.WriteLine("이미 설치 또는 실행 준비가 진행 중입니다."); return 2; }
            try {
                if (!Environment.Is64BitOperatingSystem) throw new Exception("64비트 Windows가 필요합니다.");
                string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MetaverseLocal");
                string mode = args.Length > 0 ? args[0].ToLowerInvariant() : "";
                if (mode != "" && mode != "--stop" && mode != "--check" && mode != "--no-browser") throw new Exception("지원하지 않는 실행 옵션입니다.");
                Directory.CreateDirectory(root);
                string version;
                using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
                using (var sha = System.Security.Cryptography.SHA256.Create()) {
                    // The embedded payload hash is the release identity. This prevents a
                    // rebuilt installer from being mistaken for an older source revision.
                    version = BitConverter.ToString(sha.ComputeHash(payload)).Replace("-", "").Substring(0,20).ToLowerInvariant();
                }
                string target = Path.Combine(root, "releases", version);
                if (!File.Exists(Path.Combine(target, ".extracted"))) {
                    Directory.CreateDirectory(target);
                    using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
                    using (var archive = new ZipArchive(stream, ZipArchiveMode.Read)) {
                        foreach (var entry in archive.Entries) {
                            string dest = Path.GetFullPath(Path.Combine(target, entry.FullName));
                            if (!dest.StartsWith(Path.GetFullPath(target) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("잘못된 패키지 경로입니다.");
                            if (String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(dest); continue; }
                            Directory.CreateDirectory(Path.GetDirectoryName(dest));
                            entry.ExtractToFile(dest, true);
                        }
                    }
                    File.WriteAllText(Path.Combine(target, ".extracted"), version);
                }
                string exe = Assembly.GetExecutingAssembly().Location;
                string installedExe = Path.Combine(root, "Metaverse-Setup.exe");
                if (!String.Equals(exe, installedExe, StringComparison.OrdinalIgnoreCase)) File.Copy(exe, installedExe, true);
                string option = mode == "--stop" ? " -Stop" : mode == "--check" ? " -CheckOnly" : mode == "--no-browser" ? " -NoBrowser" : "";
                var startInfo = new ProcessStartInfo {
                    FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe"),
                    Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(target, "setup.ps1") + "\" -InstallRoot \"" + root + "\"" + option,
                    UseShellExecute = false,
                    WorkingDirectory = target
                };
                startInfo.EnvironmentVariables["PSModulePath"] = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\Modules") + ";" + Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "WindowsPowerShell\\Modules");
                var p = Process.Start(startInfo);
                p.WaitForExit(); return p.ExitCode;
            } catch (Exception ex) {
                Console.WriteLine("실행 실패: " + ex.Message);
                Console.WriteLine("Enter 키를 누르면 닫힙니다.");
                if (!Console.IsInputRedirected) Console.ReadLine();
                return 1;
            }
        }
    }
}
