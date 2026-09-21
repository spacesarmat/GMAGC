# Локальная сборка ПК-приложения для Windows и проверка запуска (та же, что в CI).
# Запуск из корня репозитория:  .\scripts\build_windows.ps1
# Параметры: -Venv <путь к окружению Python 3.12 с flet==1.0.0>, -Seconds <сколько секунд держать приложение запущенным>
param(
    [string]$Venv = "$env:USERPROFILE\.venv312",
    [int]$Seconds = 20
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"                 # Flet выводит символы вне cp1252
$env:FLET_CLI_NO_RICH_OUTPUT = "1"
Set-Location (Split-Path -Parent $PSScriptRoot)

$flet = Join-Path $Venv "Scripts\flet.exe"
if (-not (Test-Path $flet)) {
    throw "Не найден $flet. Создайте окружение: py -3.12 -m venv $Venv; $Venv\Scripts\python.exe -m pip install flet==1.0.0"
}

$timer = [Diagnostics.Stopwatch]::StartNew()
& $flet build windows apps/desktop --yes --no-rich-output --build-version 0.0.0
if ($LASTEXITCODE -ne 0) { throw "flet build завершился с кодом $LASTEXITCODE" }
Write-Host "Сборка заняла $([int]$timer.Elapsed.TotalSeconds) с"

# Дымовая проверка: запускаем собранное приложение и ищем ошибки Python в его выводе и в console.log
$exe = Get-ChildItem apps/desktop/build/windows -Filter *.exe | Select-Object -First 1
$consoleLog = Join-Path $env:LOCALAPPDATA "@ANDY_BUM\GMAGC\console.log"
Remove-Item $consoleLog -ErrorAction SilentlyContinue
$err = Join-Path $env:TEMP "gmagc_app_err.txt"
$out = Join-Path $env:TEMP "gmagc_app_out.txt"
$process = Start-Process -FilePath $exe.FullName -PassThru -RedirectStandardError $err -RedirectStandardOutput $out
Start-Sleep -Seconds $Seconds
$exited = $process.HasExited
if (-not $exited) { Stop-Process -Id $process.Id -Force }

$files = @($err, $out, $consoleLog) | Where-Object { Test-Path $_ }
if ($exited) { throw "Приложение завершилось само, код $($process.ExitCode)" }
if ($files -and (Select-String -Path $files -Pattern "Traceback" -Quiet)) {
    Get-Content $files
    throw "В выводе приложения есть ошибка Python (см. выше)"
}
Write-Host "ГОТОВО: приложение запущено, ошибок Python нет. Папка сборки: $($exe.DirectoryName)"
