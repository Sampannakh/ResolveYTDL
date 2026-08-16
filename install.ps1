param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$InstallerArgs
)
$ErrorActionPreference = "Stop"
$python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
& $python (Join-Path $PSScriptRoot "installer.py") @InstallerArgs
exit $LASTEXITCODE
