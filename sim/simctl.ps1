# PowerShell wrapper: runs sim/simctl with Git Bash. Same commands and arguments.
#   .\sim\simctl.ps1 clock 09:29
$ErrorActionPreference = 'Stop'
$bash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (-not (Test-Path $bash)) { $bash = 'bash' }
& $bash (Join-Path $PSScriptRoot 'simctl') @args
exit $LASTEXITCODE
