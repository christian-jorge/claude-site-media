<#
.SYNOPSIS
  Instala a skill design-to-mcp e o comando /gerar-imagem no Claude Code.

.DESCRIPTION
  A chave do Gemini nao e argumento DESTE script: `-Chave AI...` ficaria no
  historico do PSReadLine e na linha de comando do processo. Use -PedirChave,
  que le sem ecoar na tela. Ela ainda aparece no argv do `claude mcp add` que roda
  em seguida (a CLI so aceita o valor assim) e fica em repouso no registro do MCP.
  Para evitar os dois, use -SemMcp, defina GEMINI_API_KEY no ambiente do Windows e
  registre sem --env.

.EXAMPLE
  .\install.ps1                  # instala para o usuario (~/.claude)
  .\install.ps1 -Escopo projeto  # instala so no projeto atual (.\.claude)
  .\install.ps1 -Forcar          # substitui a instalacao existente (guarda backup)
  .\install.ps1 -PedirChave      # pede a chave e registra o MCP
#>
[CmdletBinding()]
param(
    [ValidateSet('usuario', 'projeto')]
    [string]$Escopo = 'usuario',
    [switch]$PedirChave,
    [switch]$SemMcp,
    [switch]$Forcar
)

$ErrorActionPreference = 'Stop'
$origem = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Escopo -eq 'usuario') {
    $destinoBase = Join-Path $HOME '.claude'
} else {
    $aqui = (Get-Location).Path
    $pareceProjeto = (Test-Path (Join-Path $aqui '.git')) -or
                     (Test-Path (Join-Path $aqui 'package.json')) -or
                     (Test-Path (Join-Path $aqui '.claude'))
    if (-not $pareceProjeto) {
        Write-Host "AVISO: '$aqui' nao parece a raiz de um projeto (sem .git, package.json ou .claude)." -ForegroundColor Yellow
        $r = Read-Host '  Instalar aqui mesmo? [s/N]'
        if ($r -notmatch '^[sSyY]$') { Write-Host 'cancelado.'; exit 1 }
    }
    $destinoBase = Join-Path $aqui '.claude'
}
$destinoSkill = Join-Path $destinoBase 'skills\design-to-mcp'
$destinoCmd = Join-Path $destinoBase 'commands'

Write-Host "Instalando em $destinoBase ($Escopo)" -ForegroundColor Cyan

if ((Test-Path $destinoSkill) -and (-not $Forcar)) {
    Write-Host "  ja existe: $destinoSkill" -ForegroundColor Yellow
    Write-Host '  use -Forcar para substituir. Nada foi alterado.'
    exit 1
}

if (Test-Path $destinoSkill) {
    $item = Get-Item $destinoSkill -Force
    if ($item.LinkType) {
        # apagar o link transformaria um checkout de desenvolvimento numa copia congelada
        Write-Host "  AVISO: $destinoSkill e um $($item.LinkType) -> $($item.Target)." -ForegroundColor Yellow
        Write-Host '         Nao vou toca-lo. Remova o link a mao se quiser uma copia.'
        exit 1
    }
    $backup = "$destinoSkill.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Move-Item $destinoSkill $backup
    Write-Host "  instalacao anterior guardada em $backup" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path $destinoSkill, $destinoCmd | Out-Null
Copy-Item -Recurse -Force (Join-Path $origem 'skills\design-to-mcp\*') $destinoSkill
# a arvore de trabalho carrega __pycache__ e artefatos de rodada, que nao sao a skill
Get-ChildItem $destinoSkill -Recurse -Force -Include '__pycache__' -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $destinoSkill -Recurse -Force -Include '*.pyc', 'midias.json', 'briefing*.json', 'inventario_midias.html' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $origem 'commands\gerar-imagem.md') $destinoCmd

Write-Host "  skill    -> $destinoSkill" -ForegroundColor Green
Write-Host "  comando  -> $(Join-Path $destinoCmd 'gerar-imagem.md')" -ForegroundColor Green

# --- dependencias -----------------------------------------------------------
Write-Host "`nDependencias:" -ForegroundColor Cyan

# Get-Command nao basta: o python3 do PATH no Windows costuma ser o stub da Store,
# que existe e nao executa. E ter Python nao basta: o servidor MCP recusa gerar sem
# Pillow, entao o interpretador REGISTRADO tem de ser um que a tenha.
$py = $null
$pySemPillow = $null
foreach ($candidato in @('python', 'py', 'python3')) {
    if (-not (Get-Command $candidato -ErrorAction SilentlyContinue)) { continue }
    try {
        & $candidato -c 'import sys' 2>$null
        if (-not $?) { continue }
        & $candidato -c 'import PIL' 2>$null
        if ($?) { $py = $candidato; break }
        if (-not $pySemPillow) { $pySemPillow = $candidato }
    } catch {}
}
if (-not $py) { $py = $pySemPillow }

$exePy = $null
if ($py) {
    $exePy = & $py -c 'import sys;print(sys.executable)'
    Write-Host "  python   ok ($exePy)" -ForegroundColor Green
} else {
    Write-Host '  python   NAO ENCONTRADO no PATH - obrigatorio' -ForegroundColor Red
}

$pillow = $false
if ($py) {
    & $py -c 'import PIL' 2>$null
    $pillow = $?
}
if ($pillow) {
    Write-Host '  pillow   ok' -ForegroundColor Green
} elseif ($py) {
    Write-Host '  pillow   FALTANDO no interpretador que vai ser registrado.' -ForegroundColor Yellow
    Write-Host '           gerar_imagem vai RECUSAR antes de cobrar. Rode:'
    Write-Host "             & `"$exePy`" -m pip install pillow"
}

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host '  ffmpeg   ok' -ForegroundColor Green
} else {
    Write-Host '  ffmpeg   faltando - gerar_video e preparar_video vao recusar antes de cobrar' -ForegroundColor Yellow
}

# --- MCP --------------------------------------------------------------------
$servidor = Join-Path $destinoSkill 'ferramentas\mcp_google_midia.py'
# o escopo do MCP acompanha o da instalacao: registrar em -s user uma skill que so
# existe neste projeto deixa um servidor quebrado em todos os outros
$escopoMcp = if ($Escopo -eq 'projeto') { 'local' } else { 'user' }

Write-Host "`nMCP google-midia:" -ForegroundColor Cyan
if ($SemMcp) {
    Write-Host '  -SemMcp: nada foi registrado.'
} elseif ($PedirChave) {
    $segura = Read-Host 'Chave do Gemini (nao aparece na tela)' -AsSecureString
    $chave = [System.Net.NetworkCredential]::new('', $segura).Password
    if (-not $chave) { Write-Host 'chave vazia; nada foi registrado.' -ForegroundColor Yellow; exit 2 }
    # `claude mcp add` so aceita o valor como ARGUMENTO: nao ha caminho por stdin. A
    # chave aparece no argv deste unico processo e fica em repouso no registro do MCP.
    # Para nao deixa-la em nenhum dos dois: defina GEMINI_API_KEY no ambiente do
    # Windows e registre sem --env, que o servidor le do proprio os.environ.
    try {
        & claude mcp add google-midia -s $escopoMcp --env "GEMINI_API_KEY=$chave" -- "$exePy" "$servidor"
        if ($?) { Write-Host "  registrado no escopo $escopoMcp. Confira com: claude mcp list" -ForegroundColor Green }
    } finally {
        $chave = $null
    }
} else {
    Write-Host '  registre com (chave em https://aistudio.google.com/apikey):'
    Write-Host "    claude mcp add google-midia -s $escopoMcp --env GEMINI_API_KEY=<sua-chave> -- `"$exePy`" `"$servidor`""
    Write-Host '  ou rode de novo com -PedirChave, que le a chave sem ecoar na tela.'
}

Write-Host "`nOpcional, no registro do MCP: MIDIA_TETO_USD (padrao 5,00 em 24h) e"
Write-Host 'MIDIA_TETO_CHAMADA_USD (padrao 1,00) limitam o gasto no proprio servidor.'
Write-Host 'MIDIA_EXIGE_ORCAMENTO=1 exige o token da PARADA 2 em cada geracao.'
Write-Host "`nPronto. Reinicie o Claude Code e rode /gerar-imagem no seu projeto." -ForegroundColor Cyan
