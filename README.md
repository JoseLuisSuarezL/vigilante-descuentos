Vigilante de descuentos → Telegram
Este programa revisa cada 15 minutos las secciones de ofertas que elijas y te
manda un mensaje de Telegram en cuanto aparece un artículo rebajado más del 60 %.
Funciona en los servidores de GitHub: no necesitas tener el ordenador encendido.
Es gratis.
No repite avisos. Si ya te avisó de un artículo, solo vuelve a hacerlo si baja todavía más.
Son 6 partes. Calcula unos 20 minutos la primera vez. Hazlas en orden.
---
PARTE 1 · Crear tu bot de Telegram (desde el móvil)
Un "bot" es una cuenta automática de Telegram. Vas a crear una tuya, que será la
que te escriba los avisos.
1.1. Si no tienes Telegram, instálalo desde la tienda de aplicaciones y créate una cuenta con tu número.
1.2. Abre Telegram y toca la lupa (buscar). Escribe `BotFather`.
Elige el que tiene una marca azul de verificado ✔️. Hay copias falsas, así que fíjate en la marca.
1.3. Toca Iniciar (o escribe `/start` y envíalo).
1.4. Escribe `/newbot` y envíalo.
1.5. BotFather te pide un nombre para el bot. Es el nombre que verás en el chat.
Escribe, por ejemplo: `Mis Chollos`
1.6. Ahora te pide un nombre de usuario. Tiene que ser único y terminar en `bot`.
Escribe, por ejemplo: `chollos_joseluis_bot`
Si te dice que ya existe, prueba con otro (añade números, p. ej. `chollos_joseluis88_bot`).
1.7. BotFather te responde con un mensaje que incluye una línea así:
```
Use this token to access the HTTP API:
7123456789:AAHk3x...una_cadena_larga...
```
Ese texto largo es el TOKEN (número, dos puntos y letras).
Cópialo y guárdalo: mantén el dedo encima del mensaje → Copiar, y pégalo en una
nota del móvil o envíatelo por email. Lo necesitarás en la Parte 4.
> ⚠️ El token es como la contraseña de tu bot. No lo compartas con nadie.
1.8. En ese mismo mensaje de BotFather hay un enlace del tipo `t.me/chollos_joseluis_bot`.
Tócalo para abrir el chat con tu bot y pulsa Iniciar (o envía `/start`).
> Este paso es imprescindible: un bot no puede escribirte si tú no le has escrito antes.
> El bot no contestará nada todavía; es normal.
✅ Al terminar la Parte 1 tienes: el token guardado, y le has enviado `/start` a tu bot.
---
PARTE 2 · Crear tu cuenta y tu "repositorio" en GitHub (mejor desde el ordenador)
GitHub es la web donde se va a guardar y ejecutar el programa. Un "repositorio" es
simplemente una carpeta en GitHub.
2.1. Entra en https://github.com y pulsa Sign up.
Pon tu email, una contraseña y un nombre de usuario. Confirma el código que te llega al email.
Si ya tienes cuenta, pulsa Sign in y entra.
2.2. Arriba a la derecha, pulsa el botón + y elige New repository.
2.3. Rellena la página así:
Repository name: `vigilante-descuentos`
Marca Public (público).
Lo demás déjalo como está.
Pulsa el botón verde Create repository.
> **¿Por qué público?** En los repositorios públicos GitHub no limita el uso. En los
> privados solo da 2.000 minutos al mes, que no llegan para revisar cada 15 minutos.
> Tu token **no** se verá: lo guardarás como "secreto" en la Parte 4. Lo único que
> se ve es la lista de tiendas y de ofertas encontradas.
✅ Ahora estás en la página de tu repositorio, que de momento está vacío.
---
PARTE 3 · Subir los archivos del programa
3.1. En tu ordenador, descomprime el archivo vigilante-descuentos.zip
(clic derecho → Extraer todo). Se crea una carpeta `vigilante-descuentos`.
3.2. En la página de tu repositorio verás un texto que dice
"…or uploading an existing file". Pulsa ese enlace.
(Si no lo ves: botón Add file → Upload files).
3.3. Abre la carpeta que descomprimiste y arrastra a la web estos 4 archivos:
`vigilante.py`
`config.yaml`
`requirements.txt`
`README.md`
3.4. Espera a que aparezcan en la lista y pulsa el botón verde Commit changes (abajo).
3.5. Ahora falta un quinto archivo, que se crea a mano porque está en una carpeta
oculta. Pulsa Add file → Create new file.
3.6. En la casilla del nombre (arriba, donde pone Name your file…) escribe
exactamente esto, letra por letra:
```
.github/workflows/vigilante.yml
```
Al escribir cada `/` verás que GitHub lo convierte en una carpeta. Es lo correcto.
3.7. En tu ordenador, dentro de la carpeta descomprimida, entra en `.github` → `workflows`
y abre `vigilante.yml` con el Bloc de notas (clic derecho → Abrir con → Bloc de notas).
> Si no ves la carpeta `.github` en Windows: en el Explorador de archivos, menú
> **Vista** → marca **Elementos ocultos**. En Mac: pulsa `Cmd + Shift + .`
3.8. En el Bloc de notas, selecciona todo (`Ctrl + A`), copia (`Ctrl + C`),
vuelve a GitHub, haz clic en el cuadro grande de texto y pega (`Ctrl + V`).
3.9. Pulsa el botón verde Commit changes… y, en la ventanita, otra vez Commit changes.
✅ En tu repositorio ves ahora: la carpeta `.github` y los 4 archivos.
---
PARTE 4 · Guardar el token como "secreto"
4.1. En tu repositorio, pulsa la pestaña Settings (arriba, con un engranaje ⚙️).
4.2. En el menú de la izquierda, busca Secrets and variables y pulsa en Actions.
4.3. Pulsa el botón verde New repository secret.
4.4. Rellena:
Name: `TELEGRAM_TOKEN` (en mayúsculas, con guion bajo)
Secret: pega aquí el token de la Parte 1 (el `7123456789:AAH…`), sin espacios delante ni detrás.
Pulsa Add secret.
4.5. Ahora, en ese mismo menú de la izquierda, pulsa Actions → General.
Baja hasta Workflow permissions, marca Read and write permissions y pulsa Save.
(Esto permite que el programa recuerde qué te ha avisado ya.)
---
PARTE 5 · Averiguar tu número de chat y hacer la primera prueba
Telegram necesita saber a qué chat mandarte los avisos. Ese número lo averigua el propio programa.
5.1. Pulsa la pestaña Actions de tu repositorio.
Si aparece un botón verde del tipo "I understand my workflows, go ahead and enable them", púlsalo.
5.2. A la izquierda, pulsa Vigilar descuentos.
5.3. A la derecha aparece un botón Run workflow ▾. Púlsalo.
En el desplegable "¿Qué quieres hacer?" elige averiguar_chat_id y pulsa el botón verde Run workflow.
> Importante: haz esto en las **24 horas** siguientes a haber enviado `/start` a tu bot
> (paso 1.8). Si ha pasado más tiempo, vuelve a escribirle `/start` y repite.
5.4. Espera unos segundos y recarga la página. Aparecerá una ejecución nueva.
Cuando tenga un ✅ verde (tarda 1–2 minutos), pulsa sobre ella.
5.5. Pulsa en revisar y luego despliega el paso Revisar tiendas. Verás algo así:
```
================================================
  TU CHAT ID ES:  123456789   (José Luis)
================================================
```
Copia ese número. Si tu número empieza por un guion (`-`), cópialo también con el guion.
5.6. Vuelve a Settings → Secrets and variables → Actions → New repository secret y crea:
Name: `TELEGRAM_CHAT_ID`
Secret: el número que acabas de copiar
Pulsa Add secret.
5.7. Vuelve a Actions → Vigilar descuentos → Run workflow, elige
mensaje_de_prueba y pulsa Run workflow.
En 1–2 minutos te llegará a Telegram, desde tu bot:
"✅ Vigilante de descuentos: ¡funciona! A partir de ahora te avisaré aquí."
🎉 Si te ha llegado, la conexión está hecha. Si no, mira "Si algo falla" al final.
---
PARTE 6 · Comprobar las tiendas
Todas las tiendas ya vienen configuradas en `config.yaml`: las 7 de moda/tecnología
(revisando todo lo de hombre) y las de los clubes de LaLiga, Premier League y Serie A.
No hay que pegar ninguna dirección.
6.1. Actions → Vigilar descuentos → Run workflow → elige prueba_sin_enviar → Run workflow.
6.2. Verás que se lanzan 17 tareas: una por cada tienda de moda/tecnología, los grupos
"Moda Inditex" y "Moda Tendam", y 8 grupos de clubes (LaLiga 1 y 2,
Premier 1, 2 y 3, Serie A 1, 2 y 3). Cuando acaben
(3–15 minutos), entra en la ejecución y pulsa cada una a la izquierda →
Revisar tiendas. Verás cuántos artículos ha leído y el mayor descuento encontrado.
Al final aparece lo que te mandaría.
✅ ¡Terminado! Desde ahora se revisa todo solo cada 15 minutos.
---
Si algo falla
Lo que ves en el registro	Qué hacer
`faltan los secretos TELEGRAM_TOKEN y TELEGRAM_CHAT_ID`	Revisa la Parte 4 y el paso 5.6: los nombres deben estar escritos exactamente así, en mayúsculas.
`Telegram no acepta el token` o `HTTP 401`	El token está mal copiado. Bórralo en Settings → Secrets y créalo de nuevo, sin espacios.
`No hay mensajes. Abre tu bot…`	Escribe `/start` a tu bot (paso 1.8) y repite el paso 5.3.
`HTTP 400: chat not found`	El TELEGRAM_CHAT_ID está mal. Repite la Parte 5 desde 5.3.
`HTTP 403` o `0 artículos` en una tienda	Esa web está bloqueando a GitHub. Copia el registro de esa tienda y pásaselo a Claude.
Una ejecución sale con ❌ rojo	Pulsa sobre ella, copia el texto del error y pásaselo a Claude.
---
Preguntas frecuentes
¿Cómo cambio el porcentaje?
Edita `descuento_minimo: 60` en `config.yaml` (con el lápiz ✏️) y guarda.
¿Cómo lo pauso?
Actions → Vigilar descuentos → botón ··· (arriba a la derecha) → Disable workflow.
Para reanudarlo: Enable workflow.
¿Por qué a veces tarda más de 15 minutos?
GitHub retrasa las tareas programadas cuando tiene mucho tráfico. Lo normal es cada 15–20 minutos.
Me ha llegado un email de GitHub diciendo que ha desactivado el workflow.
GitHub pausa las tareas programadas de los repositorios públicos tras 60 días sin
actividad. Entra en Actions y pulsa Enable workflow.
¿Me avisa de cualquier cosa rebajada?
No. Hay un filtro de ropa y tallas (al principio de config.yaml, apartado `tallas`):
Solo ropa de hombre adulto: descarta gorras, pines, bufandas, calcetines,
calzado, balones, tazas… y la ropa de mujer y de niño.
Solo si queda disponible en talla XL o mayor (XL, XXL, 3XL…).
Pantalones, vaqueros y bermudas: talla 48 o mayor (en pulgadas, W38 o más).
Americanas, trajes y abrigos con talla de número: 54 o más. Camisas con talla de
cuello: 43 o más.
Cada aviso indica las tallas grandes que quedan, por ejemplo "Tallas: XL, XXL".
Para saber las tallas, en muchas tiendas hay que abrir la ficha de cada artículo.
Se abren unas 40 por tienda en cada vuelta, así que la primera revisión de una
tienda grande puede tardar varias vueltas: el resumen inicial llega al terminar.
En PcComponentes el filtro está apagado (`tallas: false`), porque no vende ropa.
¿Y Amazon, El Corte Inglés y Pull&Bear?
Están en config.yaml pero desactivadas (`activa: false`): sus protecciones
anti-robots bloquean las visitas automáticas desde GitHub (errores 503 y 403), y la
herramienta no intenta saltarse esas protecciones. Alternativas:
Amazon: Keepa (keepa.com), que avisa cuando un producto baja más del
porcentaje que elijas.
El Corte Inglés: guarda en favoritos sus páginas de "Descuentos TOP" y míralas
de vez en cuando.
Pull&Bear: su sección de rebajas/ofertas de hombre en la web o la app.
Si algún día quieres probar otra vez una tienda desactivada, cambia `activa: false`
por `activa: true` en config.yaml (o borra la línea). Esto sirve para apagar
cualquier tienda sin borrarla.
¿Qué revisa exactamente de cada tienda?
Tienda	Qué revisa	Cada cuánto
Zara	Todo hombre (~3.000 artículos) + secciones de ofertas, que detecta solas	Cada 15 min
Fifty	Todo hombre (~3.400 artículos)	Cada 15 min
PcComponentes	Ofertas TOP y Últimas unidades, ordenadas por descuento	Cada 15 min
PcComponentes	Las 520 categorías de la tienda, ordenadas por descuento	Por turnos: vuelta completa ~1,5 h
Lefties	Secciones de ofertas de hombre (Promoción, Rebajas…), que detecta solas	Cada 15 min
Lefties	Resto del catálogo de hombre (~4.000 artículos)	Por turnos: vuelta completa ~4 h
Sevilla FC	Catálogo completo de la tienda (~1.400) + colecciones de ofertas	Cada 15 min
Silbon	Todo hombre + rebajas, segundas rebajas y Black Friday de hombre	Cada 15 min
Scalpers	Todo hombre (~2.500) + rebajas, outlet, flash sale, mid season y marcas invitadas	Cada 15 min
Massimo Dutti	Secciones de ofertas de hombre (Special Prices, Promociones…), que detecta solas	Cada 15 min
Massimo Dutti	Resto del catálogo de hombre	Por turnos (vuelta completa en unas horas)
Springfield / Pedro del Hierro	Secciones de ofertas de hombre de la portada (Precios especiales, Mid season, Black Friday)	Cada 15 min
Springfield / Pedro del Hierro	Todo hombre (~7.400 / ~2.800 artículos)	Por turnos: vuelta completa ~1,5 h / ~45 min
El Ganso	Rebajas y precios especiales de hombre (con navegador)	Cada 15 min
Amazon, El Corte Inglés, Pull&Bear	Desactivadas (bloquean las visitas automáticas)	—
¿Y las tiendas de los clubes?
Tipo	Clubes	Qué revisa
Catálogo completo (Shopify / API)	Athletic, Racing, Levante, Villarreal, Celta, Alavés, Deportivo, Elche · Nottingham Forest, Ipswich, Newcastle, Crystal Palace, Bournemouth · Napoli, Como, Roma, Milan, Venezia, Parma, Cagliari, Frosinone	Toda la tienda, cada 15 min
Secciones de ofertas (las busca solas en la portada)	Valencia, Osasuna, Getafe, Málaga, Real Sociedad, Espanyol, Rayo · Fulham, Coventry, Hull, Arsenal, Brentford, Brighton · Juventus, Inter, Atalanta, Bologna, Fiorentina, Lazio, Torino, Sassuolo, Lecce, Monza, Genoa	Sale / Outlet / Rebajas / Saldi… y todas sus páginas
Fanatics (protección antibots)	Aston Villa, Chelsea, Everton, Leeds, Man City, Man United, Liverpool, Tottenham, Sunderland	Se intenta; si sale BLOQUEADA en el registro, esa tienda no se puede vigilar desde GitHub
No incluida	Udinese	No tiene tienda online propia (vende en Amazon)
La tienda del Alavés es compartida con el Baskonia (baloncesto), así que también puede
avisarte de productos del Baskonia.
La primera vez me llegó un mensaje "🆕 … ahora mismo hay X artículos rebajados".
Es el resumen inicial: para no mandarte cientos de mensajes, la primera vez que revisa
una tienda te envía solo las 5 mejores ofertas. Después solo avisa de las nuevas.
Si prefieres recibirlas todas, pon `resumen_primera_vez: false` en `config.yaml`.
Las partes "por turnos" son catálogos muy grandes: leerlos enteros cada 15 minutos
sería demasiado pesado y las tiendas acabarían bloqueando las visitas.
¿Puedo pasarme a WhatsApp más adelante?
Sí. Cuando CallMeBot vuelva a tener plazas, consigue tu clave y crea los secretos
`CALLMEBOT_PHONE` (tu móvil con prefijo, p. ej. `+34600111222`) y `CALLMEBOT_APIKEY`.
Después borra los dos secretos de Telegram. El programa usará WhatsApp automáticamente.
