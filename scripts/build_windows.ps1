# Локальная сборка ПК-приложения для Windows (PyInstaller) и проверка запуска (та же, что в CI).
# Запуск из корня репозитория:  .\scripts\build_windows.ps1
# Параметры: -Venv <путь к окружению Python 3.12>, -Seconds <сколько секунд держать приложение запущенным>
param(
    [string]$Venv = "$PWD\.venv",
    [int]$Seconds = 20
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Не найден $python. Создайте окружение: py -3.12 -m venv $Venv; $python -m pip install -r packaging/pyinstaller/requirements.txt"
}

$timer = [Diagnostics.Stopwatch]::StartNew()
& $python -m PyInstaller packaging/pyinstaller/gmagc-desktop.spec --noconfirm --distpath dist-app --workpath build-app
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с кодом $LASTEXITCODE" }
Write-Host "Сборка заняла $([int]$timer.Elapsed.TotalSeconds) с"

# Дымовая проверка: запускаем собранное приложение с отдельной папкой данных и ищем ошибки Python в его выводе и логе
$exe = Get-Item dist-app/gmagc-desktop/gmagc-desktop.exe
$data = Join-Path $env:TEMP "gmagc-smoke"
Remove-Item $data -Recurse -ErrorAction SilentlyContinue
$env:GMAGC_DATA_DIR = $data
$err = Join-Path $env:TEMP "gmagc_app_err.txt"
$out = Join-Path $env:TEMP "gmagc_app_out.txt"
$process = Start-Process -FilePath $exe.FullName -PassThru -RedirectStandardError $err -RedirectStandardOutput $out
Start-Sleep -Seconds $Seconds
$exited = $process.HasExited
if (-not $exited) { Stop-Process -Id $process.Id -Force }

$log = Join-Path $data "gmagc.log"
$files = @($err, $out, $log) | Where-Object { Test-Path $_ }
if ($exited) { throw "Приложение завершилось само, код $($process.ExitCode)" }
if ($files -and (Select-String -Path $files -Pattern "Traceback" -Quiet)) {
    Get-Content $files
    throw "В выводе приложения есть ошибка Python (см. выше)"
}
Write-Host "ГОТОВО: приложение запущено, ошибок Python нет. Папка сборки: $($exe.DirectoryName)"
