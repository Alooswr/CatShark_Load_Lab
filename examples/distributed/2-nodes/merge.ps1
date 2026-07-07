param([string]$RunId = "gb28181-2nodes-test")

$ExampleRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Resolve-Path (Join-Path $ExampleRoot "..\..")

Push-Location $ProjectRoot
python -m bukong_load_tester.merge_reports `
    --input-dir (Join-Path $PSScriptRoot "out") `
    --output-dir (Join-Path $PSScriptRoot "merged")
Pop-Location
