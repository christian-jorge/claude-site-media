#!/usr/bin/env bash
# Instala a skill design-to-mcp e o comando /gerar-imagem no Claude Code.
set -euo pipefail

ajuda() {
  cat <<'FIM'
Instala a skill design-to-mcp e o comando /gerar-imagem no Claude Code.

  ./install.sh                 instala para o usuario (~/.claude), vale em todo projeto
  ./install.sh --projeto       instala so no projeto atual (./.claude)
  ./install.sh --forcar        substitui uma instalacao existente (guarda backup)
  ./install.sh --chave         pede a chave do Gemini por prompt e registra o MCP
  ./install.sh --chave-stdin   le a chave da entrada padrao e registra o MCP
  ./install.sh --sem-mcp       nao registra nada, so imprime o comando
  ./install.sh -h | --help     esta ajuda

A chave nao e argumento DESTE script: `--chave AI...` ficaria no historico do
shell e na linha de comando do processo, visivel para qualquer `ps` da maquina.
Ela ainda aparece no argv do `claude mcp add` que roda em seguida (a CLI so aceita
o valor assim) e fica em repouso no registro do MCP. Para evitar os dois, use
--sem-mcp, defina GEMINI_API_KEY no ambiente do sistema e registre sem --env.
FIM
}

ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ESCOPO="usuario"
CHAVE=""
FORCAR=0
SEM_MCP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --projeto) ESCOPO="projeto" ;;
    --forcar)  FORCAR=1 ;;
    --sem-mcp) SEM_MCP=1 ;;
    --chave)
      printf 'Chave do Gemini (nao aparece na tela): ' >&2
      read -r -s CHAVE || true
      printf '\n' >&2
      [ -n "$CHAVE" ] || { echo "chave vazia; nada foi registrado." >&2; exit 2; }
      ;;
    --chave-stdin)
      read -r CHAVE || true
      [ -n "$CHAVE" ] || { echo "nada veio na entrada padrao." >&2; exit 2; }
      ;;
    -h|--help) ajuda; exit 0 ;;
    *) echo "opcao desconhecida: $1" >&2; echo >&2; ajuda >&2; exit 2 ;;
  esac
  shift
done

if [ "$ESCOPO" = "usuario" ]; then
  BASE="$HOME/.claude"
else
  # instalar no diretorio errado espalha um .claude/ que ninguem sabe de onde veio
  if [ ! -d ".git" ] && [ ! -f "package.json" ] && [ ! -d ".claude" ]; then
    echo "AVISO: '$PWD' nao parece a raiz de um projeto (sem .git, package.json ou .claude)." >&2
    printf '  Instalar aqui mesmo? [s/N] ' >&2
    read -r resposta || true
    case "${resposta:-}" in s|S|y|Y) ;; *) echo "cancelado."; exit 1 ;; esac
  fi
  BASE="$PWD/.claude"
fi
SKILL="$BASE/skills/design-to-mcp"
CMD="$BASE/commands"

echo "Instalando em $BASE ($ESCOPO)"

if [ -d "$SKILL" ] && [ "$FORCAR" -eq 0 ]; then
  echo "  ja existe: $SKILL"
  echo "  use --forcar para substituir. Nada foi alterado."
  exit 1
fi

if [ -d "$SKILL" ] || [ -L "$SKILL" ]; then
  if [ -L "$SKILL" ]; then
    # apagar o link e copiar por cima transformaria silenciosamente um checkout
    # de desenvolvimento numa copia congelada
    echo "  AVISO: $SKILL e um symlink (-> $(readlink "$SKILL"))."
    echo "         Nao vou toca-lo. Remova o link a mao se quiser uma copia."
    exit 1
  fi
  BACKUP="$SKILL.bak-$(date +%Y%m%d-%H%M%S)"
  mv "$SKILL" "$BACKUP"
  echo "  instalacao anterior guardada em $BACKUP"
fi

mkdir -p "$SKILL" "$CMD"
# --exclude porque a arvore de trabalho carrega __pycache__ e artefatos de rodada,
# que nao sao a skill e viajam para dentro de ~/.claude
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude 'midias.json' \
        --exclude 'briefing*.json' --exclude 'inventario_midias.html' \
        "$ORIGEM/skills/design-to-mcp/" "$SKILL/"
else
  cp -R "$ORIGEM/skills/design-to-mcp/." "$SKILL/"
  find "$SKILL" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find "$SKILL" -name '*.pyc' -delete 2>/dev/null || true
  rm -f "$SKILL/midias.json" "$SKILL/briefing"*.json "$SKILL/inventario_midias.html"
fi
cp "$ORIGEM/commands/gerar-imagem.md" "$CMD/"

echo "  skill    -> $SKILL"
echo "  comando  -> $CMD/gerar-imagem.md"

# --- dependencias ------------------------------------------------------------
echo
echo "Dependencias:"

# `command -v` nao basta: no Windows o python3 do PATH costuma ser o stub da
# Microsoft Store, que existe e nao executa. E ter Python nao basta: o servidor
# MCP recusa gerar sem Pillow, entao o interpretador REGISTRADO tem de ser um
# que a tenha -- registrar o que nao tem era o que fazia a skill recusar depois.
PY=""
PY_SEM_PILLOW=""
for candidato in python3 python py; do
  command -v "$candidato" >/dev/null 2>&1 || continue
  "$candidato" -c "import sys" >/dev/null 2>&1 || continue
  if "$candidato" -c "import PIL" >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
  [ -n "$PY_SEM_PILLOW" ] || PY_SEM_PILLOW="$candidato"
done
[ -n "$PY" ] || PY="$PY_SEM_PILLOW"

if [ -n "$PY" ]; then
  PY_EXE="$("$PY" -c 'import sys;print(sys.executable)')"
  echo "  python   ok ($PY_EXE)"
else
  PY_EXE=""
  echo "  python   NAO ENCONTRADO no PATH - obrigatorio"
fi

if [ -n "$PY" ] && "$PY" -c "import PIL" >/dev/null 2>&1; then
  echo "  pillow   ok"
elif [ -n "$PY" ]; then
  echo "  pillow   FALTANDO no interpretador que vai ser registrado."
  echo "           gerar_imagem vai RECUSAR antes de cobrar. Rode:"
  echo "             \"$PY_EXE\" -m pip install pillow"
fi

if command -v ffmpeg >/dev/null 2>&1; then
  echo "  ffmpeg   ok"
else
  echo "  ffmpeg   faltando - gerar_video e preparar_video vao recusar antes de cobrar"
fi

# --- MCP ---------------------------------------------------------------------
SERVIDOR="$SKILL/ferramentas/mcp_google_midia.py"
# o escopo do MCP acompanha o escopo da instalacao: registrar em -s user uma skill
# que so existe neste projeto deixa um servidor quebrado em todos os outros
ESCOPO_MCP="user"
[ "$ESCOPO" = "projeto" ] && ESCOPO_MCP="local"

echo
echo "MCP google-midia:"
if [ "$SEM_MCP" -eq 1 ]; then
  echo "  --sem-mcp: nada foi registrado."
elif [ -n "$CHAVE" ]; then
  # `claude mcp add` so aceita o valor como ARGUMENTO: nao ha caminho por stdin. A
  # chave aparece no argv deste unico processo e fica em repouso no registro do MCP.
  # Para nao deixa-la em nenhum dos dois: defina GEMINI_API_KEY no ambiente do
  # sistema e registre sem --env, que o servidor le do proprio os.environ.
  claude mcp add google-midia -s "$ESCOPO_MCP" \
    --env "GEMINI_API_KEY=$CHAVE" -- "${PY_EXE:-python}" "$SERVIDOR"
  unset CHAVE
  echo "  registrado no escopo $ESCOPO_MCP. Confira com: claude mcp list"
else
  echo "  registre com (chave em https://aistudio.google.com/apikey):"
  echo "    claude mcp add google-midia -s $ESCOPO_MCP --env GEMINI_API_KEY=<sua-chave> \\"
  echo "      -- \"${PY_EXE:-python}\" \"$SERVIDOR\""
  echo "  ou rode de novo com --chave, que pede a chave sem ecoar na tela."
fi

echo
echo "Opcional, no registro do MCP: MIDIA_TETO_USD (padrao 5,00 em 24h) e"
echo "MIDIA_TETO_CHAMADA_USD (padrao 1,00) limitam o gasto no proprio servidor."
echo "MIDIA_EXIGE_ORCAMENTO=1 exige o token da PARADA 2 em cada geracao."
echo
echo "Pronto. Reinicie o Claude Code e rode /gerar-imagem no seu projeto."
