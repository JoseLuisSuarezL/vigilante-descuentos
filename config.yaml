name: Vigilar descuentos

on:
  schedule:
    # Cada 15 minutos (GitHub puede retrasarlo unos minutos en horas punta)
    - cron: "*/15 * * * *"
  workflow_dispatch:
    inputs:
      accion:
        description: "¿Qué quieres hacer?"
        type: choice
        default: normal
        options:
          - normal
          - prueba_sin_enviar
          - mensaje_de_prueba
          - averiguar_chat_id

permissions:
  contents: write

concurrency:
  group: vigilante
  cancel-in-progress: false

jobs:
  revisar:
    runs-on: ubuntu-latest
    timeout-minutes: 12
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Instalar dependencias
        run: pip install -r requirements.txt

      - name: Instalar navegador invisible (solo si alguna tienda lo usa)
        run: |
          if grep -Eq "^[[:space:]]*navegador:[[:space:]]*true" config.yaml; then
            python -m playwright install --with-deps chromium
          fi

      - name: Revisar tiendas
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          CALLMEBOT_PHONE: ${{ secrets.CALLMEBOT_PHONE }}
          CALLMEBOT_APIKEY: ${{ secrets.CALLMEBOT_APIKEY }}
          ACCION: ${{ inputs.accion || 'normal' }}
        run: python vigilante.py

      - name: Guardar lo ya avisado
        if: always()
        run: |
          if [ -f vistos.json ]; then
            git config user.name "vigilante-bot"
            git config user.email "vigilante-bot@users.noreply.github.com"
            git add vistos.json
            if ! git diff --cached --quiet; then
              git commit -m "Actualizar artículos vistos"
              git pull --rebase --autostash || true
              git push || true
            fi
          fi
