<#
.SYNOPSIS
  Instala a skill design-to-mcp e o comando /gerar-imagem no Claude Code.

.EXAMPLE
  .\install.ps1                 # instala para o usuario (~/.claude), vale em todo projeto
  .\install.ps1 -Escopo projeto # instala so no projeto atual (.claude)
  .\install.ps1 -Chave AI...    # ja registra o MCP google-midia com a chave do Gemini
#>
[CmdletBinding()]
param(
    [ValidateSet('usuario', 'projeto')]
    [string]$Escopo = 'usuario',
    [string]$Chave,
    [switch]$Forcar
)

$ErrorActionPreference = 'Stop'
$origem = Split-Path -Parent $MyInvocation.MyCommand.Path

$destinoBase = if ($Escopo -eq 'usuario') { Join-Path $HOME '.claude' } else { Join-Path (Get-Location) '.claude' }
$destinoSkill = Join-Path $destinoBase 'skills\design-to-mcp'
$destinoCmd = Join-Path $destinoBase 'commands'

Write-Host "Instalando em $destinoBase ($Escopo)" -ForegroundColor Cyan

if ((Test-Path $destinoSkill) -and (-not $Forcar)) {
    Write-Host "  ja existe: $destinoSkill" -ForegroundColor Yellow
    Write-Host "  use -Forcar para sobrescrever. Nada foi alterado."
    exit 1
}

# copiar por cima deixaria para tras arquivo que a versao nova removeu
if (Test-Path $destinoSkill) { Remove-Item -Recurse -Force $destinoSkill }
New-Item -ItemType Directory -Force -Path $destinoSkill, $destinoCmd | Out-Null
Copy-Item -Recurse -Force (Join-Path $origem 'skills\design-to-mcp\*') $destinoSkill
Copy-Item -Force (Join-Path $origem 'commands\gerar-imagem.md') $destinoCmd

Write-Host "  skill    -> $destinoSkill" -ForegroundColor Green
Write-Host "  comando  -> $(Join-Path $destinoCmd 'gerar-imagem.md')" -ForegroundColor Green

# --- dependencias -----------------------------------------------------------
Write-Host "`nDependencias:" -ForegroundColor Cyan

# Get-Command nao basta: o python3 do PATH no Windows costuma ser o stub da Microsoft
# Store, que existe e nao executa. So vale o interpretador que roda de verdade.
$py = $null
foreach ($candidato in @('python', 'py', 'python3')) {
    if (Get-Command $candidato -ErrorAction SilentlyContinue) {
        try {
            & $candidato -c "import sys" 2>$null
            if ($?) { $py = $candidato; break }
        } catch {}
    }
}
if ($py) {
    $exe = & $py -c "import sys;print(sys.executable)"
    Write-Host "  python   ok ($exe)" -ForegroundColor Green
} else {
    Write-Host "  python   NAO ENCONTRADO no PATH - obrigatorio" -ForegroundColor Red
}

$pillow = $false
if ($py) {
    & $py -c "import PIL" 2>$null
    $pillow = $?
}
if ($pillow) { Write-Host "  pillow   ok" -ForegroundColor Green }
else { Write-Host "  pillow   faltando - rode: pip install pillow" -ForegroundColor Yellow }

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Write-Host "  ffmpeg   ok" -ForegroundColor Green }
else { Write-Host "  ffmpeg   faltando - so afeta video (reencode e poster)" -ForegroundColor Yellow }

# --- MCP --------------------------------------------------------------------
$servidor = Join-Path $destinoSkill 'ferramentas\mcp_google_midia.py'
$exePy = if ($py) { & $py -c "import sys;print(sys.executable)" } else { "python" }
$cmdMcp = "claude mcp add google-midia -s user --env GEMINI_API_KEY=<sua-chave> -- `"$exePy`" `"$servidor`""

Write-Host "`nMCP google-midia:" -ForegroundColor Cyan
if ($Chave) {
    & claude mcp add google-midia -s user --env "GEMINI_API_KEY=$Chave" -- "$exePy" "$servidor"
    if ($?) { Write-Host "  registrado. Confira com: claude mcp list" -ForegroundColor Green }
} else {
    Write-Host "  registre com (chave em https://aistudio.google.com/apikey):"
    Write-Host "    $cmdMcp" -ForegroundColor White
}

Write-Host "`nPronto. Reinicie o Claude Code e rode /gerar-imagem no seu projeto." -ForegroundColor Cyan
