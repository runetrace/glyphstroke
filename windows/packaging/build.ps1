# Сборка Glyphstroke: программа и установщик одним файлом.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Что получается:
#   dist\app\                     программа со всем нужным внутри
#   dist\Glyphstroke-ВЕРСИЯ-setup.exe установщик — то, что раздаётся
#
# Нужны: .NET 8 SDK и Inno Setup 6. Без Inno Setup соберётся только папка
# dist\app — её можно запускать как есть, это уже рабочая программа.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$appDir = Join-Path $dist 'app'

function Say($text) {
    Write-Host ''
    Write-Host $text -ForegroundColor Cyan
}

Say '1/3 Сборка программы'
if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
# Самодостаточная сборка: .NET на машине пользователя не нужен. Файл выходит
# крупнее, зато установка не упирается в «сначала поставьте среду выполнения».
dotnet publish (Join-Path $root 'src\Glyphstroke.App\Glyphstroke.App.csproj') `
    -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=false `
    -o $appDir

Say '2/3 Проверки ядра'
dotnet test (Join-Path $root 'tests\Glyphstroke.Core.Tests\Glyphstroke.Core.Tests.csproj') -c Release --nologo

Say '3/3 Установщик'
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host 'Inno Setup 6 не найден — установщик не собран.' -ForegroundColor Yellow
    Write-Host 'Программа готова и работает: ' -NoNewline
    Write-Host (Join-Path $appDir 'Glyphstroke.exe')
    Write-Host 'Поставить Inno Setup: https://jrsoftware.org/isdl.php'
    exit 0
}

& $iscc (Join-Path $root 'packaging\glyphstroke.iss')
Get-ChildItem (Join-Path $dist '*setup.exe') | ForEach-Object { Write-Host $_.FullName -ForegroundColor Green }
