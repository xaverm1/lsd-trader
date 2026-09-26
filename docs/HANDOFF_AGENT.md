# Übergabe: LSD-Strategie, Stand 26.09.2026

Für einen Agenten, der lokal (nicht in der Cloud) weiterarbeitet. Lies diese Datei ganz,
bevor du etwas änderst. Die ausführliche Chronik aller Tests steht in `docs/HANDOFF.md`
(Englisch); diese Datei fasst den aktuellen Stand zusammen.

## 1. Worum es geht

Xaver handelt eine eigene Strategie („LSD“: Liquidity, Sweep, Demand/Supply-Zone) diskretionär
auf Futures (MNQ/MES, Prop-Firm). Ziel: herausfinden, ob die Regeln, so wie er sie handelt,
nach Kosten einen Vorteil haben, und sie dafür exakt in Code fassen. Der Code ist ein eigener
Backtester in Python (`src/lsdtrader`).

Xaver liest Deutsch. Er will ehrliche Ergebnisse (Widerspruch erwünscht) und bei
Regelfragen ein Bild statt Text.

## 2. Einrichtung lokal

Zwei Repos:

| Repo | Inhalt | Sichtbarkeit |
|---|---|---|
| `xaverm1/lsd-trader` | Code, Tests, Skripte, Doku | öffentlich |
| `xaverm1/lsd-trader-data` | Kursdaten, TradingView-Indikator | **privat** |

Arbeitsbranch: `claude/funny-maxwell-41yhp6` (enthält alles; `main` ist 40+ Commits zurück,
es gibt noch keinen PR).

```bash
git clone https://github.com/xaverm1/lsd-trader.git
cd lsd-trader
git checkout claude/funny-maxwell-41yhp6
git clone https://github.com/xaverm1/lsd-trader-data.git data   # privat, braucht Zugriff
python3 -m venv .venv          # Python >= 3.12
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q            # alle Tests müssen grün sein
```

(Unter Windows: `.venv\Scripts\...` statt `.venv/bin/...`.) `data/` steht in
`.git/info/exclude` bzw. muss dort eingetragen werden: **Kursdaten und der Indikator dürfen
nie ins öffentliche Repo.**

Daten in `data/`:
- `databento/ES_ohlcv1m_2010..2026.csv.gz`, `NQ_...`: CME-Futures 1-Minute mit Volumen,
  Databento GLBX.MDP3, kontinuierlicher Front-Kontrakt nach Volumen (`ES.v.0`, `NQ.v.0`),
  UTC, 01.2010 bis 25.09.2026. **Das sind die Daten für die aktuelle Strategie.**
- `histdata/`: HistData-CFD-Dateien ohne Volumen (XAUUSD 2009-2025, SPXUSD 2020-2025), für
  die älteren Tests.
- `tradingview/absorption_bubbles_leg.pine`: Xavers aktueller Indikator (Basis: „Absorption
  Bubbles“ von profitprotrading, MPL-2.0, angepasst: Volumen vom Mini, Bein-Projektion).

Neue Databento-Daten: `scripts/databento_download.py` liest den Schlüssel nur aus der
Umgebungsvariable `DATABENTO_API_KEY`. Den Schlüssel nie in Dateien, Commits oder Chat
schreiben. (Der erste Schlüssel wurde im Chat gepostet und muss von Xaver erneuert werden.)

Arbeitsspeicher: ein voller Lauf 2010-2026 braucht mehrere GB; Läufe nacheinander, nicht
parallel starten (drei parallele Läufe sind mit 15 GB abgestürzt).

## 3. Die Strategie, wie sie jetzt im Code steht

Long-Regeln; Short ist exakt gespiegelt (der Code spiegelt die Kerzen und nutzt dieselbe
Logik). Zonen und Liquidität kommen von 30-min-Kerzen, Sweep, Tap und Einstieg werden
minutengenau auf 1-min-Kerzen geprüft.

1. **Swing-Tief**: Kerze mit 1 Kerze links und rechts, die nicht tiefer sind (`piv_len=1`).
2. **BOS**: Für ein neues Swing-Tief P ist L0 das letzte Swing-Tief darunter, H2 das höchste
   Hoch zwischen L0 und P. BOS = eine 30-min-Kerze schließt über H2.
3. **Zone (Demand)**: Ursprung = die letzte bärische (oder Doji-) Kerze bis P zurück. Zone =
   ihr Hoch bis Tief („normal“), bzw. Körperoberkante bis Tief, wenn die Folgekerze nicht
   höher geht („accuracy“). Solange die Zone noch „baut“, verschiebt eine bärische Kerze, die
   sie berührt, die Zone auf diese Kerze. Die Zone ist „verlassen“, sobald eine Kerze
   komplett darüber liegt.
4. **Invalidierung der Zone** (`zone_kill=close_inside`, Standard): Eine 30-min-Kerze
   schließt in der Zone (Close ≤ Oberkante), oder irgendein Docht geht unter die Unterkante.
   Den Docht prüft der Code jede Minute. Nach der Invalidierung gibt es keinen Einstieg mehr.
5. **Liquidität**: Das Swing-Tief P eines BOS, das über einer verlassenen Zone liegt und
   nach dem Zonenursprung entstanden ist. Dazu kommen zwei strengere Regeln von Xaver:
   - `liq_rule=nearest`: Nur das offene Swing-Tief, das der Zone am nächsten liegt, zählt.
     Liegt ein anderes offenes Swing-Tief dazwischen, gilt es als zu weit weg.
   - `liq_bos_pivot=N`: Das Level H2, das der BOS der Liquidität gebrochen hat, muss selbst
     ein echtes Swing-Hoch sein, mit N Kerzen links und rechts, alle vor der BOS-Kerze
     („starker BOS“). Getestet mit N = 2 und 3.
6. **Sweep**: Eine Minute handelt unter die Liquidität.
7. **Tap**: Eine Minute berührt danach die Zonenoberkante. Das Zeitfenster vom Sweep bis zum
   Tap regelt `max_min_sweep_to_tap` (Minuten) und `max_bars_sweep_to_tap` (30-min-Kerzen).
8. **Absorption** (`entry_mode=absorption_1m`): Nach dem Tap braucht es eine Minute mit
   Volumen / Standardabweichung (Population) der letzten 100 Minuten-Volumen ≥ 1,3 und
   langem unteren Docht (Kerzenmitte ≤ Körperunterkante). Das ist die Bubble aus Xavers
   Indikator. Ein neues tieferes Tief entwertet die Bubble, eine neue Bubble ersetzt sie.
9. **Einstieg**: Die erste spätere Minute, die über dem Hoch der Absorptionsminute
   schließt, innerhalb von 15 Minuten (`absorb_wait_min`), zum Close dieser Minute.
10. **Stop**: Das tiefste Tief seit dem Sweep (`stop_ref=extreme`, Xavers Live-Stop).
    Alternative: das Tief der Absorptionsminute (`stop_ref=absorption`), war schlechter.
11. **Ziel**: 4 R (`rr=4`). Positionen laufen über Nacht (`--hold-overnight`), ohne
    Handelsfenster und ohne Glattstellung.
12. **Kosten**: Kommission laut Instrument (ES/NQ je 2,50 $ pro Seite) plus 1 Tick
    Slippage pro Seite, in R des jeweiligen Trades.

Aktueller Befehl (Testlauf NQ, 2025 nur zum Aufwärmen):

```bash
D=data/databento
.venv/bin/lsd backtest $D/NQ_ohlcv1m_2025.csv.gz $D/NQ_ohlcv1m_2026.csv.gz \
  --timeframe 30 --hold-overnight \
  --set entry_mode=absorption_1m --set liq_rule=nearest --set zone_kill=close_inside \
  --set liq_bos_pivot=2 --set max_bars_sweep_to_tap=48 --set max_min_sweep_to_tap=120
```

Ausgabe: `runs/<Zeit>_<Symbol>_<hash>/` (trades.parquet, meta.json). Auswertung:

```bash
.venv/bin/python scripts/absorption_report.py runs/<lauf>        # Ziele 2/3/4/6 R, brutto/netto, Jahre, Bubble-Stärke, Stopgröße
.venv/bin/python scripts/trade_charts.py runs/<lauf> --since 2026-01-01 --latest 15 --random 10
.venv/bin/python scripts/sd_be.py runs/<lauf>                    # Ziele an Bein-Levels, Einstand
```

`trade_charts.py` schreibt `runs/<lauf>/trade_charts.html`: pro Trade 30-min-Kontext und
1-min-Detail, Tabelle mit Berlin-Zeiten und Preisen zum Abgleich in TradingView. Mehrere
Zonen können denselben Sweep teilen und in derselben Minute auslösen; Report und Charts
behalten nur einen Trade pro Minute und Seite (live wäre das eine Position).

## 4. Was bisher herauskam

| Test | Ergebnis |
|---|---|
| Gold (HistData, 5-min-Regeln, Prop-Zeiten) 2015-2021, eingefrorene Basis | +0,047 R/Trade brutto (t 1,9), nach Kosten negativ |
| Viele Varianten auf Gold (Zonenalter, Trigger, Liquiditätsabstand, Stop-Modus, Trend, MA, Zeitrahmen 15-240 min, Reclaim/CISD auf 1 min) | nichts überlebt die Kosten |
| SPX CFD 30m + 1-min-CISD | leicht positiv brutto, nicht signifikant |
| **Absorption auf ES/NQ 2010-2026, alte Regeln** (jede Liquidität, Zone nur beim 30-min-Close geprüft) | NQ brutto ±0, netto −0,16 R; ES brutto −0,11 R (t −4), netto −0,40 R. Kein Vorteil. |
| Xavers Prüfung der Charts | 30 % der Liquidität lag > 3 Zonenhöhen entfernt; 20 % der Einstiege kamen nach einem Docht durch die Zone. Daraufhin Regeln 4 und 5 (oben) eingebaut. |
| **Neue Regeln, nur NQ 2026** (in-sample!) | liq_bos_pivot=2: 174 Trades, netto +0,12 R; =3: 144 Trades, +0,01 R |
| Fenster Sweep→Tap, NQ 2026, pivot 2 | 15 min +0,57 R (75 T), 60 min +0,39 (114), 2 h +0,34 (139), 4 h +0,17 (158), 24 h +0,13 (194). Median Sweep→Tap 43 min. Tap > 1 h nach dem Sweep: negativ. |

**Wichtig:** Alle Regeln der letzten Runde sind entstanden, während Xaver Trades aus 2026
angeschaut hat. 2026 ist damit in-sample, die guten Zahlen dort beweisen nichts (dazu kleine
N und sieben getestete Fenster). Der ehrliche Test sind 2010-2025, die in die Regeln nicht
eingeflossen sind.

## 5. Nächste Schritte (mit Xaver abgestimmt, noch nicht gestartet)

1. Xaver prüft die 2026-Charts (Varianten Swing 2 und 3). Erst nach seinem OK weiter.
2. Validierung auf **2010-2025, NQ und ES**, mit den Fenstern Sweep→Tap 15 min, 1 h, 4 h,
   24 h und liq_bos_pivot 2 und 3. Wenige Varianten, vorher festlegen, Ergebnisse mit N,
   brutto und netto, pro Jahr. Mehrfachtests beachten (8 Varianten × 2 Märkte).
3. Wenn etwas übrig bleibt: Ziele (feste R vs. Bein-Levels) und Einstand erneut prüfen.

Offene Fragen an Xaver:
- **Prop-Zeiten**: Die Futures-Läufe halten über Nacht und haben kein Handelsfenster. Für
  seine Prop-Firm galt früher: keine Einstiege 14:00-17:00 Chicago, flat um 15:10 Chicago.
  Klären, ob das hier auch gelten soll (CLI: ohne `--hold-overnight`).
- **Docht während die Zone noch baut**: Geht die Kerze nach dem Zonenursprung mit einem
  Docht knapp unter die Zone, bevor die Zone verlassen ist, bleibt die Zone gültig (nur ein
  Close darunter killt sie in dieser Phase). Beispiel NQ 25.09.2026 16:20. Noch nicht
  bestätigt.
- Welche Variante (Swing 2 oder 3) entspricht seinem „starken Level“.

Technisch offen:
- Die Strategie-Spezifikation `docs/specs/2026-09-25-lsd-strategy-v1.md` ist für die
  Absorptions-Regeln und die neuen Optionen (`liq_rule`, `liq_bos_pivot`,
  `zone_kill`-Minutenprüfung, `max_min_sweep_to_tap`) noch **nicht** nachgetragen. Die
  Arbeitsregel verlangt das bei jeder Regeländerung.
- `docs/HANDOFF.md` ist die lange Chronik; bei Änderungen dort und hier nachtragen.

## 6. Arbeitsregeln mit Xaver

- **Nach jeder Regeländerung zuerst ein Testlauf nur auf dem aktuellen Jahr** (ES oder NQ),
  mit Chart-Datei (`trade_charts.py --since 2026-01-01`). Xaver gleicht die Trades in
  TradingView ab. Erst nach seinem OK der volle Lauf.
- Regeln nur ändern, wenn ein Setup falsch erkannt wird, nie weil ein Trade verloren hat.
- Ergebnisse immer mit N, Kosten und Zeitraum melden; auf Mehrfachtests hinweisen.
- Regelfragen mit Bild erklären (matplotlib-Skizze reicht), Antworten auf Deutsch.
- Bei Unklarheit nachfragen statt raten.
- Vor jedem Push die komplette CI-Prüfung lokal: `ruff check .`, `ruff format --check .`,
  `mypy`, `pytest --cov=lsdtrader --cov-fail-under=90`. (Ein vergessener Formatfehler hat
  Xaver Fehler-Mails von GitHub geschickt.)
- Jede Regeländerung: Test, der vorher fehlschlägt, dann Code, dann Lauf.
- Commits mit `git -c user.name=Xaver -c
  user.email=138877794+xaverm1@users.noreply.github.com commit ...`.
- Kursdaten, Indikator und API-Schlüssel nie ins öffentliche Repo.

## 7. Wichtige Dateien

| Datei | Inhalt |
|---|---|
| `src/lsdtrader/core/config.py` | alle Strategie-Parameter mit Kommentaren |
| `src/lsdtrader/strategy/structure.py` | Swings, BOS, `strong_level` |
| `src/lsdtrader/strategy/zones.py` | Zonen, Verschieben, Invalidierung, `kill_by_minute` |
| `src/lsdtrader/strategy/liquidity.py` | Liquidität, `match_zones` (nearest-Regel) |
| `src/lsdtrader/strategy/setups.py` | Sweep→Tap→Absorption→Einstieg (`on_minute_absorption`) |
| `src/lsdtrader/strategy/lsd.py` | Zusammenbau, Volumen-Score, Spiegelung für Short |
| `src/lsdtrader/execution/broker.py` | Ausführung, Kosten, Session-Fenster |
| `src/lsdtrader/backtest/runner.py` | Backtest-Schleife, Lauf ohne TP für MFE |
| `src/lsdtrader/data/minute_files.py` | Loader HistData und Databento |
| `scripts/*.py` | Auswertungen (siehe Kopf jeder Datei) |
| `docs/HANDOFF.md` | vollständige Chronik aller Tests (Englisch) |
