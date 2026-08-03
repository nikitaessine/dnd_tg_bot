# D&D Telegram-botti (raakile)

Venäjänkielinen Telegram-botti D&D-tyyliseen peliin. Claude generoi maailman,
hahmovaihtoehdot, NPC:t ja sceneet. Pelitila tallentuu SQLite-tietokantaan
(`game.db`), yksi kampanja per Telegram-chat.

## Komennot (botissa, venäjäksi)

| Komento | Mitä tekee |
|---|---|
| `/world <teema>` | Luo pelimaailman annetusta teemasta |
| `/hero` | Hahmonluonti: valitse 4 attribuuttia → botti ehdottaa 3 hahmoa → valitse yksi. Sama hahmo ei voi olla kahdella pelaajalla. |
| `/npc` | Generoi uuden NPC:n (ei toista olemassaolevia) |
| `/scene` | Generoi seuraavan tilanteen — ottaa huomioon aiemmat sceneet, hahmot ja NPC:t |
| `/roll` | Noppa: pelkkä `/roll` = d20, `/roll Сила` = d20 + bonus jos attribuutti on valittu, `/roll Сила 15` lisää vaikeusasteen, `/roll 2d6` = vapaa heitto |
| `/status` | Näyttää maailman, hahmot ja NPC:t |
| `/delete_hero` | Poistaa oman hahmon |
| `/reset` | Nollaa koko kampanjan tässä chatissa |

## Asennus (Windows)

1. **Luo Telegram-botti**: avaa Telegramissa [@BotFather](https://t.me/BotFather),
   lähetä `/newbot`, anna nimi ja käyttäjänimi. Kopioi saamasi token.

2. **Hanki Anthropic API-avain**: https://platform.claude.com/ → API Keys → Create Key.

3. **Asenna riippuvuudet** (projektikansiossa):

   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Konfiguroi**: kopioi `.env.example` nimelle `.env` ja täytä `BOT_TOKEN` ja
   `ANTHROPIC_API_KEY`.

5. **Käynnistä**:

   ```
   python bot.py
   ```

6. Lisää botti ryhmächattiin (tai käytä yksityischatissa). Jos haluat että botti
   näkee ryhmän komennot, poista BotFatherissa privacy mode:
   `/mybots` → botti → Bot Settings → Group Privacy → Turn off.

## Rakenne

- `bot.py` — Telegram-käsittelijät (aiogram 3), hahmonluonnin tilakone
- `ai.py` — Claude API -kutsut (maailma, hahmot, NPC, sceneet)
- `db.py` — SQLite: maailma, hahmot (uniikkius per chat), NPC:t, sceneet
- `config.py` — asetukset ja attribuuttilista
