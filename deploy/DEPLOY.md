# Botin vienti Google Cloudiin (Always Free e2-micro)

Lopputulos: botti pyörii 24/7 ilmaisella virtuaalikoneella, käynnistyy automaattisesti
uudelleen kaatumisen ja reboottien jälkeen. Aikaa noin 30 min.

---

## 1. Projekti ja laskutus

1. Google Cloud Console → projektivalitsin → **New project** → nimeksi esim. `dnd-bot`.
2. Ota laskutus käyttöön (**Billing** → Link a billing account). Luottokortti vaaditaan,
   mutta Always Free -rajoissa siitä ei veloiteta.
3. **Aseta budjettihälytys heti**: Billing → Budgets & alerts → Create budget →
   summa esim. 1 €, hälytys 50 % ja 100 %. Tämä on turvaverkko konfiguraatiovirheiden varalle.

## 2. Luo virtuaalikone

Compute Engine → VM instances → **Create instance**. Nämä asetukset ovat pakollisia,
jotta kone pysyy ilmaisena:

| Asetus | Arvo | Huom |
|---|---|---|
| Region | `us-central1` (tai `us-west1` / `us-east1`) | **Muilla alueilla veloitetaan normaalihinta** |
| Machine type | `e2-micro` | Series E2 → Preset: Shared core |
| Boot disk type | **Standard persistent disk** | Oletus on usein Balanced — se EI ole ilmainen |
| Boot disk size | 30 GB | Ilmaisraja |
| Boot disk image | Ubuntu 24.04 LTS | |
| Firewall | Älä avaa mitään portteja | Botti ei tarvitse sisääntulevaa liikennettä |

Compute Engine API pitää ottaa käyttöön ensimmäisellä kerralla (konsoli kysyy tämän).

## 3. Yhdistä koneeseen

VM instances -listassa koneen rivillä **SSH** → Open in browser window.
Selainpohjainen SSH riittää, erillistä avainten säätöä ei tarvita.

## 4. Asenna botti

Aja koneella komennot järjestyksessä:

```bash
# Perustyökalut
sudo apt update && sudo apt install -y python3-venv git

# Oma käyttäjä botille (ei root-oikeuksia)
sudo useradd -r -m -d /opt/dnd_tg_bot dndbot
sudo mkdir -p /opt/dnd_tg_bot
```

Kopioi projektin tiedostot koneelle. Helpoin tapa ilman Gitiä on selain-SSH:n
**upload file** -painike (rataskuvake oikeassa yläkulmassa) — lataa `bot.py`, `ai.py`,
`db.py`, `config.py`, `requirements.txt`. Ne päätyvät kotihakemistoosi, siirrä ne sitten:

```bash
sudo mv ~/bot.py ~/ai.py ~/db.py ~/config.py ~/requirements.txt /opt/dnd_tg_bot/
```

Luo `.env`-tiedosto koneelle (**älä** lataa sitä selaimen kautta, kirjoita se käsin):

```bash
sudo nano /opt/dnd_tg_bot/.env
```

Sisältö — huomaa että systemd vaatii rivit ilman lainausmerkkejä:

```
BOT_TOKEN=1234567890:AA...
ANTHROPIC_API_KEY=sk-ant-...
```

Tallenna `Ctrl+O`, `Enter`, poistu `Ctrl+X`.

Asenna riippuvuudet ja aseta oikeudet:

```bash
cd /opt/dnd_tg_bot
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
sudo chown -R dndbot:dndbot /opt/dnd_tg_bot
sudo chmod 600 /opt/dnd_tg_bot/.env
```

## 5. Käynnistä palveluna

Lataa `dnd-bot.service` koneelle (tai luo `sudo nano /etc/systemd/system/dnd-bot.service`
ja liitä sisältö tästä repositorion `deploy/`-kansiosta), sitten:

```bash
sudo mv ~/dnd-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dnd-bot
sudo systemctl status dnd-bot
```

Statuksen pitäisi näyttää `active (running)`. Testaa botti Telegramissa komennolla `/start`.

## 6. Ylläpito

```bash
sudo journalctl -u dnd-bot -f      # lokit reaaliajassa
sudo systemctl restart dnd-bot     # uudelleenkäynnistys
sudo systemctl stop dnd-bot        # pysäytys
```

**Koodin päivitys** (Git-työnkulku): työnnä muutokset GitHubiin omalta koneelta ja aja
palvelimella `sudo /opt/dnd_tg_bot/deploy/update.sh`. Skripti hakee koodin, päivittää
riippuvuudet, korjaa oikeudet ja käynnistää botin uudelleen.

**Varmuuskopiot**: pelitila on tiedostossa `/opt/dnd_tg_bot/game.db`. Kaksi tapaa:

- Telegramissa GM ajaa `/backup` — botti lähettää kopion yksityisviestinä.
- Automaattinen päivittäinen kopio kansioon `/opt/dnd_tg_bot/backups/` (14 viimeisintä
  säilytetään). Lisää cron-ajo kerran:

  ```bash
  sudo chmod +x /opt/dnd_tg_bot/deploy/backup.sh && (sudo crontab -l 2>/dev/null; echo "0 4 * * * /opt/dnd_tg_bot/deploy/backup.sh") | sudo crontab -
  ```

Palautus: pysäytä botti, kopioi haluttu tiedosto nimelle `/opt/dnd_tg_bot/game.db`,
aja `sudo chown dndbot:dndbot /opt/dnd_tg_bot/game.db` ja käynnistä botti.

Huom: tietokanta käyttää WAL-tilaa, joten kansiossa on myös `game.db-wal` ja `game.db-shm`.
Älä kopioi pelkkää `game.db`-tiedostoa käsin kesken ajon — käytä yllä olevia tapoja.

---

## Muistilista ilmaisena pysymiseen

- Kone on alueella `us-west1`, `us-central1` tai `us-east1`
- Konetyyppi on `e2-micro` (ei e2-small tai suurempi)
- Levy on **Standard persistent disk**, enintään 30 GB (ei Balanced eikä SSD)
- Vain yksi tällainen kone tilillä kerrallaan
- Budjettihälytys on asetettu

Botin oma liikenne on pelkkää tekstiä, joten ilmainen 1 GB/kk ulosmenevää liikennettä
riittää helposti. Anthropic API -kutsut laskutetaan erikseen Anthropicin kautta,
niillä ei ole tekemistä Google Cloudin kanssa.
