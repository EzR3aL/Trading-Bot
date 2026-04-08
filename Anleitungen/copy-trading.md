# Copy-Trading

> Kopiere automatisch die Trades einer öffentlichen Hyperliquid-Wallet auf deine eigene Exchange.
>
> *Automatically copy the trades of a public Hyperliquid wallet to your own exchange.*

---

## Deutsch

### Was ist Copy-Trading?

Copy-Trading ist eine neue Bot-Strategie, mit der du einer öffentlichen Hyperliquid-Wallet (zum Beispiel einem erfolgreichen Trader, den du auf Hyperliquid gefunden hast) folgen kannst. Der Bot beobachtet die Wallet rund um die Uhr und kopiert ihre Trades auf die Exchange deiner Wahl (Bitget, BingX, Bitunix, Weex oder Hyperliquid selbst).

Du brauchst **keinen** Zugang zum privaten Schlüssel der Source-Wallet — es reicht die öffentliche Adresse, denn Hyperliquid macht alle Positionen und Fills über seine öffentliche API sichtbar.

### Was genau wird kopiert?

In der ersten Version (v1) werden folgende Aktionen der Source-Wallet automatisch auf deinem Account nachgebaut:

- **Entries** — Wenn die Source eine neue Position öffnet, öffnet dein Bot eine entsprechende Position auf der Ziel-Exchange.
- **Full Closes** — Wenn die Source eine Position komplett schließt, schließt dein Bot die Kopie automatisch im nächsten Tick. Der Exit-Grund wird als `COPY_SOURCE_CLOSED` im Trade-Log eingetragen.

Folgendes wird in v1 **nicht** gespiegelt:

- **Add-Ins** (Nachkäufe in eine bereits offene Position)
- **Teil-Closes** (teilweises Reduzieren einer Position)
- **TP/SL-Anpassungen** der Source-Wallet nach dem Einstieg

Das heißt: Dein Bot erstellt genau einen Trade pro Entry der Source und schließt ihn wieder, wenn die Source ihre Position vollständig schließt. Alles dazwischen wird ignoriert.

### Wie funktioniert das Budget? (Slots)

Beim Anlegen gibst du zwei Werte an:

- **Budget** — zum Beispiel `1000 USDT`
- **Max Slots** — zum Beispiel `5`

Der Bot teilt dein Budget gleichmäßig auf die Slots auf. In diesem Beispiel:

```
1000 USDT / 5 Slots = 200 USDT pro Trade
```

Jeder kopierte Trade bekommt also eine feste Größe von 200 USDT Notional, unabhängig davon, wie groß die Source-Position ist. Das schützt dich vor Whales, die plötzlich mit sehr hohem Einsatz traden.

**Wichtig:** Wenn alle 5 Slots belegt sind und die Source einen 6. Trade öffnet, wird dieser Trade **übersprungen**. Du bekommst eine Notification (Telegram / Discord / E-Mail, je nachdem was du konfiguriert hast), damit du weißt, dass der Bot einen Trade nicht kopieren konnte.

### Cold Start — Bestehende Positionen werden nicht kopiert

Wenn du den Bot startest, übernimmt er **nicht** die Positionen, die die Source-Wallet **bereits** offen hat. Der Bot setzt beim ersten Tick eine Wasserlinie („Watermark") auf den aktuellen Zeitpunkt und ignoriert alles, was davor passiert ist.

**Warum?** Weil du sonst beim Bot-Start in Positionen einsteigst, die die Source vielleicht schon vor Tagen zu einem viel besseren Preis geöffnet hat — du würdest den Move verpassen und nur das Risiko tragen.

Das bedeutet konkret:

- Startest du den Bot um 14:00 Uhr, folgt er nur Trades, die die Source **ab 14:00 Uhr** eröffnet.
- Positionen, die die Source um 13:30 Uhr geöffnet hat, bleiben außen vor.
- Sobald die Source eine neue Position öffnet, kopiert dein Bot diese sofort beim nächsten Polling-Tick.

### Schritt-für-Schritt: Copy-Bot anlegen

#### 1. Bot Builder öffnen

Gehe im Dashboard auf **„Neuer Bot"** und wähle im ersten Schritt die Strategie **Copy Trading**.

#### 2. Ziel-Exchange wählen

Wähle die Exchange, auf der du die Trades ausführen willst. Du brauchst dort natürlich gültige API-Keys (siehe die jeweilige Exchange-Anleitung im `Anleitungen/`-Ordner).

> Hinweis: Die Source-Wallet liegt **immer** auf Hyperliquid, aber die Ziel-Exchange ist frei wählbar.

#### 3. Source-Wallet eingeben und prüfen

Trage die Hyperliquid-Adresse der Wallet ein, der du folgen möchtest (`0x...`, 42 Zeichen). Klicke dann auf **„Wallet prüfen"**.

Der Bot prüft dann vier Dinge in dieser Reihenfolge:

1. **Format** — Ist die Adresse eine gültige EVM-Adresse (`0x` + 40 Hex-Zeichen)?
2. **Existenz** — Existiert die Wallet überhaupt auf Hyperliquid?
3. **Aktivität** — Hat die Wallet in den letzten **30 Tagen** Trades gemacht? (Wenn sie tot ist, warnt dich das Frontend.)
4. **Symbol-Verfügbarkeit** — Welche der Symbole, die die Source handelt, sind auf deiner Ziel-Exchange verfügbar?

Du siehst danach eine Vorschau wie diese:

```
✓ Wallet gültig
✓ 47 Trades in den letzten 30 Tagen
✓ Verfügbare Symbole auf Bitget: BTC, ETH, SOL, ARB
✗ Nicht verfügbar: HYPE, PURR (werden vom Bot übersprungen)
```

**Blocker:** Wenn **keines** der Symbole der Source auf deiner Ziel-Exchange verfügbar ist, lässt dich das Frontend den Bot gar nicht erst anlegen — es würde ja nichts kopiert werden.

#### 4. Budget und Slots einstellen

Trage dein Budget ein (in USDT) und wie viele Slots du haben möchtest. Empfehlung: starte konservativ mit wenigen großen Slots (z. B. 3 Slots à 300 USDT), bis du der Source vertraust.

#### 5. Optionale Einstellungen

- **Hebel (Leverage)** — Optional. Wenn du das Feld leer lässt, nutzt der Bot den gleichen Hebel wie die Source. Wenn du einen Wert setzt, wird er verwendet — **aber** automatisch auf das Maximum der Ziel-Exchange gecappt (siehe `src/exchanges/leverage_limits.py` für die statische Tabelle). Wird gecappt, bekommst du eine Notification.

  Beispiel: Du setzt 50x Hebel, aber die Ziel-Exchange erlaubt nur 25x → der Bot tradet mit 25x und schickt dir einen Hinweis.

- **Whitelist (Symbols)** — Komma-separierte Liste, z. B. `BTC,ETH,SOL`. Wenn gesetzt, kopiert der Bot **nur** Trades auf diesen Symbolen. Alle anderen werden übersprungen.

- **Blacklist (Symbols)** — Komma-separierte Liste, z. B. `MEME,DOGE`. Diese Symbole werden explizit **nicht** kopiert, egal was die Source macht.

- **Mindestgröße (`min_position_size_usdt`)** — Default `10`. Trades, die nach dem Slot-Sizing unter dieser Schwelle liegen würden, werden übersprungen (verhindert Dust-Trades, die nach Fees im Minus enden).

- **Polling-Intervall (`schedule_interval_minutes`)** — Default `1` Minute. Wie oft der Bot die Source-Wallet abfragt. Kürzer = schnellere Reaktion, aber mehr API-Last.

#### 6. Bot starten

Klicke auf **„Bot starten"**. Im nächsten Tick setzt der Bot seine Watermark und beginnt, die Source zu beobachten.

### Was passiert im Betrieb?

Der Bot arbeitet in einem einfachen Loop (Standard alle 60 Sekunden):

1. **Poll** — Hole alle neuen Fills der Source-Wallet seit der letzten Watermark.
2. **Filter** — Ignoriere alles, was vor der Watermark liegt, nicht in der Whitelist ist, in der Blacklist steht, kleiner als `min_position_size_usdt` ist, oder dessen Symbol auf der Ziel-Exchange nicht existiert.
3. **Symbol Mapping** — Rechne das Hyperliquid-Symbol (`BTC`) in das Ziel-Exchange-Symbol (`BTCUSDT`) um.
4. **Entry oder Exit** — Handelt es sich um ein Entry, öffne eine neue Position (sofern noch Slots frei sind). Handelt es sich um einen Full-Close, schließe die zugehörige Kopie mit `exit_reason=COPY_SOURCE_CLOSED`.
5. **Notification** — Bei übersprungenen Trades (Slot voll, Symbol nicht verfügbar, Hebel gecappt, zu klein) bekommst du eine Benachrichtigung.

Negative Symbol-Lookups (Symbol nicht auf Ziel-Exchange) werden **24 Stunden** pro Paar `(exchange, coin)` gecacht, damit der Bot die Exchange nicht mit denselben erfolglosen Anfragen flutet.

### Häufige Fragen

**Was passiert, wenn die Source über Nacht 30 Trades macht?**
Dein Bot kopiert die ersten *N*, bis alle Slots belegt sind. Alle weiteren werden mit einer Notification geskippt. Sobald die Source eine Position schließt, wird ein Slot frei und der nächste neue Entry kann wieder kopiert werden.

**Was ist, wenn die Source eine Position über Stunden langsam aufbaut (Add-Ins)?**
In v1 wird nur der **erste** Entry kopiert. Alle weiteren Add-Ins werden ignoriert. Du bekommst also die Ursprungsposition, nicht die endgültige Größe, die die Source hat.

**Kann ich mehrere Copy-Bots gleichzeitig laufen lassen?**
Ja. Jeder Copy-Bot hat sein eigenes Budget und seine eigenen Slots. Copy-Bots sind budget-isoliert und dürfen auch mit anderen Bot-Typen auf demselben Symbol laufen (der Symbol-Conflict-Check ignoriert sie).

**Was zählt als „30 Tage Aktivität"?**
Der Bot fragt die letzten Fills der Wallet ab und prüft, ob mindestens einer in den letzten 30 Tagen liegt. Eine tote Wallet (letzter Trade vor 60 Tagen) wird markiert, lässt sich aber trotzdem anlegen — du wirst nur gewarnt.

**Was passiert, wenn ich den Bot stoppe und wieder starte?**
Der Bot setzt die Watermark **neu** auf den Zeitpunkt des erneuten Starts. Alle Trades, die während der Downtime passiert sind, werden ignoriert. Positionen, die der Bot bereits geöffnet hatte, bleiben offen (und werden beim nächsten Full-Close der Source trotzdem geschlossen, sofern der Bot läuft).

**Wie rechnet der Bot Hebel um, wenn ich keinen gesetzt habe?**
Er liest den Hebel aus dem Fill der Source und setzt ihn identisch auf der Ziel-Exchange. Ist der Source-Hebel höher als das Exchange-Limit, wird gecappt und du bekommst eine Notification.

### Troubleshooting

| Problem | Ursache | Lösung |
|---|---|---|
| Bot kopiert nichts | Watermark noch nicht passiert — Source hat seit Bot-Start nichts Neues geöffnet | Warten oder eine aktivere Source wählen |
| „Wallet prüfen" schlägt fehl | Falsche Adresse oder Wallet hat nie auf Hyperliquid getradet | Adresse auf dem Hyperliquid-Explorer überprüfen |
| Alle Trades werden geskippt | Keines der Source-Symbole ist auf deiner Ziel-Exchange | Andere Ziel-Exchange wählen oder andere Source |
| Notification „Slot voll" | Alle Slots belegt, Source macht weiter Trades | Mehr Slots konfigurieren oder Budget erhöhen |
| Notification „Hebel gecappt" | Source nutzt höheren Hebel als die Exchange erlaubt | Normal — der Bot handelt trotzdem, nur mit kleinerem Hebel |

---

## English

### What is Copy-Trading?

Copy-trading is a new bot strategy that lets you follow a public Hyperliquid wallet (for example a profitable trader you found on Hyperliquid) and automatically copies their trades onto the exchange of your choice (Bitget, BingX, Bitunix, Weex, or Hyperliquid itself).

You do **not** need access to the source wallet's private key — the public address is enough, because Hyperliquid exposes all positions and fills through its public API.

### What exactly gets copied?

In the first version (v1), the following actions of the source wallet are mirrored on your account:

- **Entries** — When the source opens a new position, your bot opens a corresponding position on the target exchange.
- **Full closes** — When the source fully closes a position, your bot closes its copy in the next tick with `exit_reason=COPY_SOURCE_CLOSED`.

The following is **not** mirrored in v1:

- **Add-ins** (increasing an already-open position)
- **Partial closes** (reducing a position)
- **TP/SL adjustments** of the source after entry

This means your bot creates exactly one trade per source entry and closes it when the source fully exits. Everything in between is ignored.

### How does the budget work? (Slots)

When creating the bot you set two numbers:

- **Budget** — for example `1000 USDT`
- **Max slots** — for example `5`

The bot splits the budget evenly across the slots. In this example:

```
1000 USDT / 5 slots = 200 USDT per trade
```

Every copied trade has a fixed size of 200 USDT notional, regardless of how large the source position is. This protects you from whales who suddenly trade with very high size.

**Important:** If all 5 slots are taken and the source opens a 6th trade, that trade is **skipped**. You get a notification (Telegram / Discord / email, depending on your setup) so you know the bot couldn't copy a trade.

### Cold start — existing positions are not copied

When you start the bot, it does **not** pick up positions that the source wallet **already** has open. On the first tick the bot sets a watermark to the current timestamp and ignores everything that happened before.

**Why?** Because otherwise you'd enter positions the source opened days ago at a much better price — you'd miss the move and only carry the risk.

Concretely:

- Start the bot at 14:00 → it only follows trades the source opens **from 14:00 onwards**.
- Positions the source opened at 13:30 are ignored.
- As soon as the source opens a new position, your bot copies it on the next polling tick.

### Step-by-step: creating a copy bot

#### 1. Open the bot builder

In the dashboard click **"New Bot"** and in the first step pick the **Copy Trading** strategy.

#### 2. Choose the target exchange

Pick the exchange where you want to execute the trades. You need valid API keys on that exchange (see the exchange-specific guide in the `Anleitungen/` folder).

> Note: The source wallet is **always** on Hyperliquid, but the target exchange is free to choose.

#### 3. Enter the source wallet and validate it

Enter the Hyperliquid address of the wallet you want to follow (`0x...`, 42 chars). Then click **"Validate wallet"**.

The bot runs four checks in order:

1. **Format** — Is it a valid EVM address (`0x` + 40 hex chars)?
2. **Existence** — Does the wallet exist on Hyperliquid?
3. **Activity** — Has the wallet traded in the last **30 days**? (If it's dead, the frontend warns you.)
4. **Symbol availability** — Which of the source's symbols are available on your target exchange?

You'll see a preview like this:

```
✓ Wallet valid
✓ 47 trades in the last 30 days
✓ Available on Bitget: BTC, ETH, SOL, ARB
✗ Not available: HYPE, PURR (will be skipped)
```

**Blocker:** If **none** of the source's symbols are available on your target exchange, the frontend refuses to create the bot — nothing would ever be copied.

#### 4. Set budget and slots

Enter your budget (in USDT) and how many slots you want. Recommendation: start conservatively with few large slots (e.g. 3 slots at 300 USDT each) until you trust the source.

#### 5. Optional settings

- **Leverage** — Optional. If you leave it empty, the bot uses the same leverage as the source. If you set a value it's used — **but** capped to the target exchange's maximum (see `src/exchanges/leverage_limits.py` for the static table). If it's capped, you get a notification.

  Example: you set 50x leverage but the target exchange only allows 25x → the bot trades with 25x and sends you a note.

- **Whitelist (symbols)** — Comma-separated list, e.g. `BTC,ETH,SOL`. If set, the bot **only** copies trades on these symbols. Everything else is skipped.

- **Blacklist (symbols)** — Comma-separated list, e.g. `MEME,DOGE`. These symbols are explicitly **not** copied, whatever the source does.

- **Min size (`min_position_size_usdt`)** — Default `10`. Trades that would end up below this threshold after slot sizing are skipped (prevents dust trades that lose money on fees).

- **Polling interval (`schedule_interval_minutes`)** — Default `1` minute. How often the bot polls the source wallet. Shorter = faster reaction, higher API load.

#### 6. Start the bot

Click **"Start bot"**. On the next tick the bot sets its watermark and starts watching the source.

### What happens at runtime?

The bot runs a simple loop (default every 60 seconds):

1. **Poll** — fetch all new fills of the source wallet since the last watermark.
2. **Filter** — drop anything before the watermark, not in the whitelist, on the blacklist, smaller than `min_position_size_usdt`, or whose symbol doesn't exist on the target exchange.
3. **Symbol mapping** — map the Hyperliquid symbol (`BTC`) to the target exchange symbol (`BTCUSDT`).
4. **Entry or exit** — for entries, open a new position (if a slot is free). For full closes, close the associated copy with `exit_reason=COPY_SOURCE_CLOSED`.
5. **Notification** — for skipped trades (slot full, symbol unavailable, leverage capped, too small), you get a notification.

Negative symbol lookups (symbol not on target exchange) are cached for **24 hours** per `(exchange, coin)` pair so the bot doesn't spam the exchange with the same failing requests.

### FAQ

**What if the source makes 30 trades overnight?**
Your bot copies the first *N* until all slots are taken. Any further ones are skipped with a notification. When the source closes a position, a slot frees up and the next new entry can be copied again.

**What if the source scales into a position slowly over hours (add-ins)?**
In v1 only the **first** entry is copied. All add-ins are ignored. You get the original position, not the final size the source ends up with.

**Can I run multiple copy bots at once?**
Yes. Each copy bot has its own budget and slots. Copy bots are budget-isolated and are allowed to run on the same symbol as other bot types (the symbol conflict check skips them).

**What counts as "30 days of activity"?**
The bot queries the wallet's recent fills and checks whether at least one is within the last 30 days. A dead wallet (last trade 60 days ago) is flagged, but you can still create the bot — you're just warned.

**What happens if I stop and restart the bot?**
The bot resets the watermark to the timestamp of the restart. All trades during the downtime are ignored. Positions the bot previously opened stay open and will still be closed whenever the source fully closes (as long as the bot is running).

**How does the bot translate leverage if I didn't set any?**
It reads the leverage from the source's fill and uses the same on the target exchange. If the source leverage exceeds the exchange limit, it gets capped and you receive a notification.

### Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Bot copies nothing | Watermark hasn't been hit — source hasn't opened anything new since startup | Wait or pick a more active source |
| "Validate wallet" fails | Wrong address or wallet never traded on Hyperliquid | Check the address on the Hyperliquid explorer |
| All trades skipped | None of the source's symbols exist on your target exchange | Pick a different target exchange or source |
| "Slot full" notification | All slots taken, source keeps opening | Increase slots or budget |
| "Leverage capped" notification | Source uses higher leverage than the exchange allows | Normal — the bot still trades, just at lower leverage |
