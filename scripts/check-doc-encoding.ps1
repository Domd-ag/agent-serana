param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

$utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)

function New-CodepointString {
    param([int[]]$Codepoints)
    return -join ($Codepoints | ForEach-Object { [string][char]$_ })
}

$mojibakePatterns = @(
    (New-CodepointString @(0x93C4)), # mojibake marker often rendered as e.g. "is"
    (New-CodepointString @(0x935A)),
    (New-CodepointString @(0x7ED4)),
    (New-CodepointString @(0x6D93)),
    (New-CodepointString @(0x93B6)),
    (New-CodepointString @(0x9471)),
    (New-CodepointString @(0x7459)),
    (New-CodepointString @(0x5997)),
    (New-CodepointString @(0x74BA)),
    (New-CodepointString @(0x7ECB)),
    (New-CodepointString @(0x95B0)),
    (New-CodepointString @(0x951B)),
    (New-CodepointString @(0x9286)),
    (New-CodepointString @(0xFFFD)),
    (New-CodepointString @(0x00C2)),
    (New-CodepointString @(0x00C3))
)

$excludedPathParts = @(
    "\.git\",
    "\.gradle\",
    "\build\",
    "\venv\",
    "\__pycache__\",
    "\node_modules\"
)

$problems = New-Object System.Collections.Generic.List[string]

Get-ChildItem -Path $Root -Recurse -File -Filter "*.md" | ForEach-Object {
    $path = $_.FullName
    foreach ($part in $excludedPathParts) {
        if ($path.Contains($part)) {
            return
        }
    }

    $bytes = [System.IO.File]::ReadAllBytes($path)
    try {
        $text = $utf8Strict.GetString($bytes)
    } catch {
        $problems.Add("Invalid UTF-8: $path")
        return
    }

    foreach ($pattern in $mojibakePatterns) {
        if ($text.Contains($pattern)) {
            $hex = [System.Convert]::ToString([int][char]$pattern[0], 16).ToUpperInvariant()
            $problems.Add("Possible mojibake U+${hex}: $path")
            return
        }
    }
}

if ($problems.Count -gt 0) {
    $problems | ForEach-Object { Write-Output $_ }
    Write-Output "Doc encoding check failed: $($problems.Count) problem(s)."
    exit 1
}

Write-Output "Doc encoding check passed."
