# D&D Telegram-botti

Venäjänkielinen Telegram-botti D&D-tyyliseen ryhmäpeliin. Claude toimii pelinjohtajan
apuna: se generoi maailman, hahmovaihtoehdot, NPC:t, viholliset, saaliin ja sceneet, ja
pitää tarinan johdonmukaisena. Botti itse hoitaa säännöt: attribuutit ja modifikaattorit,
nopanheitot, HP:n, taistelun vuorojärjestyksineen, kuolonheitot, tasonnousut ja tavarat.

Yksi kampanja per Telegram-chat. Tila tallentuu SQLite-tietokantaan (`game.db`).

## Pelin kulku

1. **Pelinjohtaja** luo maailman: `/world <teema>`. Luoja on kampanjan mastеr (GM).
2. Jokainen pelaaja luo hahmon: `/hero` → valitsee 4 pääattribuuttia → botti ehdottaa
   3 hahmoa → pelaaja valitsee. Sama hahmo ei voi olla kahdella pelaajalla.
   Attribuuteille arvotaan numeroarvot (4d6, huonoin pois); valitut attribuutit saavat
   parhaat arvot ja mastery-bonuksen heittoihin.
3. `/scene` generoi tilanteen. Se voi pyytää heittoja — silloin viestin alle tulee napit,
   joita vain kyseinen pelaaja voi painaa.
4. Pelaajat ilmoittavat toimensa `/do <teksti>` ja heittävät tarvittaessa `/roll`.
5. Seuraava `/scene` on suora seuraus ilmoitetuista toimista ja **kaikista heitoista,
   taisteluista ja vahingoista** — noppatulokset ohjaavat tarinaa.

Taistelu: GM luo vihollisen (`/enemy`), aloittaa taistelun (`/fight`), botti heittää
aloitteet ja vetää vuorot. Pelaaja hyökkää omalla vuorollaan napista tai `/attack`-
komennolla, viholliset hyökkäävät automaattisesti. Voitosta saa XP:tä; `/loot` generoi
saaliin.

## Komennot

| Komento | Kuka | Mitä tekee |
|---|---|---|
| `/world <teema>` | kuka vain (kerran) | Luo maailman; luojasta tulee GM |
| `/hero`, `/sheet`, `/delete_hero` | pelaaja | Hahmon luonti, hahmolomake, poisto |
| `/scene` | kuka vain | Seuraava scene (20 s cooldown, ei taistelun aikana) |
| `/do <teksti>` | pelaaja | Ilmoita toimi — botti poistaa viestisi ja julkaisee sen hahmon nimissä |
| `/say <teksti>` tai viesti `"lainausmerkeissä"` | pelaaja | Hahmon repliikki, julkaistaan hahmon nimissä |
| `/actions`, `/party` | kuka vain | Ilmoitetut toimet ja tapahtumat / kuka on kuka (tulee myös automaattisesti 1. scenen alussa) |
| `/roll [attr] [DC]`, `/roll 2d6+1` | pelaaja | Heitto; attribuuttiheitot kirjautuvat tarinaan |
| `/sroll <attr> [DC]` | pelaaja | Salainen heitto — tulos yksityisviestinä pelaajalle ja GM:lle |
| `/hp`, `/damage N [nimi]`, `/heal N [nimi]` | pelaaja / GM toisille | Terveys |
| `/take Nimi 1d8` · `/take Nimi +2` · `/take Nimi` | pelaaja | Ase / haarniska / esine |
| `/equip`, `/drop`, `/inventory` | pelaaja | Varusteet |
| `/attack [vihollinen]`, `/pass` | pelaaja | Hyökkäys / vuoron ohitus |
| `/enemies`, `/status`, `/recap`, `/journal` | kuka vain | Tilannekuvat |
| `/npc` | kuka vain | Uusi NPC |
| `/enemy <kuvaus>` tai `/enemy Nimi HP KD +atk 1d6` | GM | Vihollinen (AI tai käsin) |
| `/fight`, `/endfight`, `/loot`, `/xp N` | GM | Taistelu, saalis, kokemus |
| `/gm` | GM | Näytä / siirrä GM-rooli (vastaa pelaajan viestiin) |
| `/tone <kuvaus>`, `/difficulty лёгкая\|обычная\|сложная` | GM | Tarinan sävy ja vaikeus |
| `/backup`, `/usage` | GM | Tietokantakopio yksityisviestinä / tokenkulutus |
| `/reset` | GM | Tyhjentää kampanjan |

Yksityischatissa käyttäjä on aina GM. Ryhmässä, jos GM:ää ei ole asetettu (vanha
kampanja), rajoituksia ei ole ennen kuin joku ajaa `/gm`.

## Asennus paikallisesti (Windows)

1. Luo botti [@BotFather](https://t.me/BotFather):ssa (`/newbot`) ja kopioi token.
   Kytke **Group Privacy pois** (`/mybots` → botti → Bot Settings → Group Privacy →
   Turn off), muuten botti ei näe ryhmän komentoja. Tee botista ryhmän ylläpitäjä
   oikeudella **poistaa viestejä** — silloin `/do` ja `/say` korvaavat pelaajan viestin
   hahmon nimissä julkaistulla versiolla. Ilman oikeutta botti vain reagoi ✍-emojilla.
2. Hanki Anthropic API-avain: https://platform.claude.com/ → API Keys.
3. Asenna:

   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. Kopioi `.env.example` → `.env` ja täytä `BOT_TOKEN` ja `ANTHROPIC_API_KEY`.
5. Käynnistä: `python bot.py` (Git Bashissa `venv/Scripts/python.exe bot.py`).

Palvelimelle vienti: [deploy/DEPLOY.md](deploy/DEPLOY.md).

## Testit

```
pip install -r requirements-dev.txt
python -m pytest tests
```

## Rakenne

- `bot.py` — käynnistys, reitittimien kytkentä, komentovalikko
- `handlers/setup.py` — maailma, GM, sävy, vaikeus, status, reset, backup, usage
- `handlers/hero.py` — hahmonluonti (välitila tietokannassa, napit omistajalukittuja), lomake
- `handlers/story.py` — sceneet, toimet, AI:n pyytämät heitot, NPC, recap, journal
- `handlers/fight.py` — heitot, HP, XP, tavarat, viholliset, taistelu
- `handlers/common.py` — viestien pilkkominen, virheenkäsittely, oikeudet
- `ai.py` — Claude-kutsut (rakenteiset vastaukset sceneille, hahmoille, vihollisille, saaliille)
- `combat.py` — aloite, vuorot, hyökkäykset, kuolonheitot
- `rules.py` — modifikaattorit, mastery, AC, HP, tasot (puhtaat funktiot)
- `dice.py` — noppanotaatio ja heitot
- `db.py` — SQLite ja migraatiot
- `config.py` — säädettävät vakiot (HP, XP, cooldown, attribuutit…)

## Miten AI pidetään johdonmukaisena

Scenegeneraattorille syötetään: maailma, hahmot terveydentiloineen, NPC:t, journalin
faktat, nykyinen sijainti, tiivistelmä vanhoista sceneistä, viimeiset 5 sceneä
sanatarkasti, pelaajien ilmoittamat toimet sekä kaikki edellisen scenen jälkeiset
tapahtumat (heitot, hyökkäykset, vahinko, tasonnousut). Kun sceneja kertyy, vanhimmat
tiivistetään automaattisesti, joten pitkäkään kampanja ei unohda alkuaan.
