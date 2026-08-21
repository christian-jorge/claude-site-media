#!/usr/bin/env bash
# Instala a skill design-to-mcp e o comando /gerar-imagem no Claude Code.
#
#   ./install.sh                  # instala para o usuario (~/.claude), vale em todo projeto
#   ./install.sh --projeto        # instala so no projeto atual (.claude)
#   ./install.sh --chave AI...    # ja registra o MCP google-midia com a chave do Gemini
#   ./install.sh --forcar         # sobrescreve instalacao existente

set -euo pipefail

ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESCOPO="usuario"
CHAVE=""
FORCAR=0

while [ $# -gt 0 ]; do
  case "$1" in
    --projeto) ESCOPO="projeto" ;;
    --chave)   CHAVE="${2:-}"; shift ;;
    --forcar)  FORCAR=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "opcao desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$ESCOPO" = "usuario" ]; then BASE="$HOME/.claude"; else BASE="$PWD/.claude"; fi
SKILL="$BASE/skills/design-to-mcp"
CMD="$BASE/commands"

echo "Instalando em $BASE ($ESCOPO)"

if [ -d "$SKILL" ] && [ "$FORCAR" -eq 0 ]; then
  echo "  ja existe: $SKILL"
  echo "  use --forcar para sobrescrever. Nada foi alterado."
  exit 1
fi

# copiar por cima deixaria para tras arquivo que a versao nova removeu
rm -rf "$SKILL"
mkdir -p "$SKILL" "$CMD"
cp -R "$ORIGEM/skills/design-to-mcp/." "$SKILL/"
cp "$ORIGEM/commands/gerar-imagem.md" "$CMD/"

echo "  skill    -> $SKILL"
echo "  comando  -> $CMD/gerar-imagem.md"

# --- dependencias ------------------------------------------------------------
echo
echo "Dependencias:"

# `command -v` nao basta: no Windows o python3 do PATH costuma ser o stub da Microsoft
# Store, que existe e nao executa. So vale o interpretador que roda de verdade.
PY=""
for candidato in python3 python py; do
  if command -v "$candidato" >/dev/null 2>&1 && "$candidato" -c "import sys" >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
done

if [ -n "$PY" ]; then
  echo "  python   ok ($("$PY" -c 'import sys;print(sys.executable)'))"
else
  echo "  python   NAO ENCONTRADO no PATH - obrigatorio"
fi

if [ -n "$PY" ] && "$PY" -c "import PIL" >/dev/null 2>&1; then
  echo "  pillow   ok"
else
  echo "  pillow   faltando - rode: ${PY:-python} -m pip install pillow"
fi

if command -v ffmpeg >/dev/null 2>&1; then
  echo "  ffmpeg   ok"
else
  echo "  ffmpeg   faltando - so afeta video (reencode e poster)"
fi

# --- MCP ---------------------------------------------------------------------
SERVIDOR="$SKILL/ferramentas/mcp_google_midia.py"
echo
echo "MCP google-midia:"
if [ -n "$CHAVE" ]; then
  claude mcp add google-midia -s user --env "GEMINI_API_KEY=$CHAVE" -- "${PY:-python}" "$SERVIDOR"
  echo "  registrado. Confira com: claude mcp list"
else
  echo "  registre com (chave em https://aistudio.google.com/apikey):"
  echo "    claude mcp add google-midia -s user --env GEMINI_API_KEY=<sua-chave> \\"
  echo "      -- ${PY:-python} \"$SERVIDOR\""
fi

echo
echo "Pronto. Reinicie o Claude Code e rode /gerar-imagem no seu projeto."
