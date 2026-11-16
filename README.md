# BetAnalyzer ⚽

Herramienta web de **análisis de fútbol**. Consulta partidos y resultados reales
de TheSportsDB, calcula probabilidades con un modelo Poisson y muestra por qué
una predicción se inclina hacia un equipo.

## Aviso

Esto no predice ganadores con certeza, no coloca apuestas y no garantiza beneficios.
Las combinadas multiplican el riesgo y el margen de la casa. El cash-out es una
comparación matemática entre una oferta y un valor estimado, no una orden de apuesta.

## Qué analiza

- Fútbol masculino y femenino mediante ligas configuradas en TheSportsDB.
- Forma reciente: victorias, empates, derrotas, goles y estilo aproximado.
- Enfrentamientos directos recientes, con peso pequeño porque suelen ser pocas muestras.
- Rendimiento local/visitante y ventaja de campo.
- Bajas clave y motivación como **entradas manuales**. No se inventan lesiones ni se
  presenta una suposición como noticia. El efecto de estos campos está limitado.
- Probabilidades de 1X2, más de 2.5 goles, ambos marcan y goles esperados.
- Combinadas con probabilidad conjunta.
- Cash-out en vivo a partir del minuto, marcador, cuota original y oferta actual.
- Seguimiento en SQLite. Al registrar el resultado real, el modelo vuelve a entrenar.
  También guarda el contexto usado en cada predicción para poder auditarlo.

El análisis solo usa resultados de TheSportsDB y los datos que introduzcas. No hace
scraping y no contiene datos ficticios. Si la API falla, la interfaz muestra el error.

## Ejecutar

```bash
pip install -r requirements.txt
export THESPORTSDB_KEY=tu_clave
python -m betanalyzer.app
```

Abre http://localhost:5000.

La clave pública de prueba `3` se usa si no defines `THESPORTSDB_KEY`. Para cambiar las
ligas sin tocar el código:

```bash
export THESPORTSDB_LEAGUE_IDS=4328,4335,4849
```

La versión actual usa un modelo de goles, por eso la configuración predeterminada es
fútbol. Otros deportes necesitan modelos y mercados específicos, no deben mezclarse con
Poisson de goles.

## Tests

```bash
pytest -q
```

## Variables de entorno

- `THESPORTSDB_KEY`: clave de TheSportsDB.
- `THESPORTSDB_LEAGUE_IDS`: IDs separados por comas.
- `THESPORTSDB_TIMEOUT`: timeout HTTP en segundos, por defecto `15`.
- `BETANALYZER_DB`: ruta del SQLite, por defecto `betanalyzer.db` en la raíz.
