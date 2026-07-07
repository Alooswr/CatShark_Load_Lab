param(
    [Parameter(Mandatory=$true)][int]$ShardIndex,
    [string]$RunId = "gb28181-8nodes-test"
)

$ShardCount = 8
$ExampleRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Resolve-Path (Join-Path $ExampleRoot "..\..")
$OutputDir = Join-Path $PSScriptRoot ("out\node-{0}" -f $ShardIndex)

Push-Location $ProjectRoot
python -m bukong_load_tester.headless_worker `
    --config (Join-Path $ExampleRoot "base_config.template.json") `
    --run-id $RunId `
    --node-id ("{0}-node-{1}" -f $env:COMPUTERNAME, $ShardIndex) `
    --shard-index $ShardIndex `
    --shard-count $ShardCount `
    --output-dir $OutputDir
Pop-Location
