# D&D Telegram-botti

Venäjänkielinen Telegram-botti D&D-tyyliseen ryhmäpeliin. Claude toimii pelinjohtajan
apuna: se generoi maailman, hahmovaihtoehdot, NPC:t, viholliset, saaliin ja sceneet, ja
pitää tarinan johdonmukaisena. Botti itse hoitaa säännöt: attribuutit ja modifikaattorit,
nopanheitot, HP:n, taistelun vuorojärjestyksineen, kuolonheitot, tasonnousut ja tavarat.

Yksi kampanja per Telegram-chat. Tila tallentuu SQLite-tietokantaan (`game.db`).

## Pelin kulku

1. **Pelinjohtaja** luo maailman: `/world <teema>`. Luoja on kampanjan mastеr (GM).
2. Jokainen pelaaja luo hahmon säännöillä (D&D 5e Basic Rules): `/hero` → rotu (+alarotu) →
   luokka → tausta → ominaisuudet (4d6 tai vakiosarja 15,14,13,12,10,8; parhaat arvot menevät
   luokan pääominaisuuksiin, rotubonukset lisätään) → taidot → (kolmiovaras: asiantuntemus,
   soturi: taistelutyyli) → 3 nimi/kuvaus-ehdotusta Claudelta. Rodut: kääpiö, haltia, hobitti,
   ihminen. Luokat: pappi (Elämä), soturi (Mestari), kolmiovaras (Varas), velho (Evokaatio).
3. `/scene` generoi tilanteen. Se voi pyytää heittoja — silloin viestin alle tulee napit,
   joita vain kyseinen pelaaja voi painaa.
4. Pelaajat ilmoittavat toimensa `/do <teksti>` ja heittävät tarvittaessa `/roll`.
5. Seuraava `/scene` on suora seuraus ilmoitetuista toimista ja **kaikista heitoista,
   taisteluista ja vahingoista** — noppatulokset ohjaavat tarinaa.

Taistelu: GM luo vihollisen (`/enemy`, myös `3x hiisi`), botti näyttää kohtaamisen vaikeuden
säännöistä (XP-kynnykset × kerroin), `/fight` heittää aloitteet. Vuorolla on toiminto, bonus-
toiminto ja reaktio; napit tai komennot. Sisältää: etu/haitta, kriittiset, lisähyökkäys,
hiipivä isku, tajuttomuus, kuolemanheitot, hetkellinen kuolema, keskittyminen, tilat, uupumus,
loitsupaikat ja ~50 mekaanisesti toteutettua loitsua. Voitosta XP jaetaan tasan ja tasot
nousevat automaattisesti (`/asi`, `/learn`, `/cantrip` kun valintoja on kertynyt).

## Komennot

Täydellinen lista: `/help` botissa. Tärkeimmät:

| Komento | Kuka | Mitä tekee |
|---|---|---|
| `/world <teema>` | kuka vain (kerran) | Luo maailman; luojasta tulee GM |
| `/hero`, `/sheet`, `/skills`, `/delete_hero` | pelaaja | Hahmonluonti, lomake, taidot, poisto |
| `/scene`, `/do`, `/say`, `/actions`, `/party`, `/npc` | pelaaja | Tarina (`/do` ja `/say` julkaistaan hahmon nimissä) |
| `/roll`, `/roll 2d6+1`, `/roll Ketteryys 15 haitta`, `/sroll`, `/save` | pelaaja | Taito-/ominaisuusheitot, salainen heitto, pelastusheitto |
| `/attack`, `/endturn`, `/order`, `/enemies` | pelaaja | Taistelu (napit ilmestyvät vuorolla) |
| `/dodge`, `/hide`, `/assist`, `/shove`, `/stabilize` | pelaaja | Yleiset toiminnot |
| `/secondwind`, `/surge`, `/cunning`, `/channel`, `/inspire` | pelaaja | Luokkakyvyt |
| `/spells`, `/cast`, `/prepare`, `/learn`, `/cantrip`, `/recover` | pelaaja | Taikuus |
| `/hp`, `/damage`, `/heal`, `/temp`, `/hitdice` | pelaaja / GM toisille | Terveys |
| `/take`, `/equip`, `/unequip`, `/drop`, `/inventory` | pelaaja | Varusteet (säännöistä: `/take Pitkämiekka`, `/take Rengashaarniska +1`) |
| `/asi`, `/expertise` | pelaaja | Tasonnousun valinnat |
| `/enemy`, `/fight`, `/endfight`, `/loot`, `/xp`, `/rest`, `/condition`, `/exhaustion`, `/inspiration` | GM | Vihollinen, taistelu, saalis, XP, lepo, tilat |
| `/gm`, `/tone`, `/difficulty`, `/backup`, `/usage`, `/reset` | GM | Kampanjan hallinta |

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
- `srd.py`, `spelldata.py` — sääntötaulukot (rodut, luokat, aseet, haarniskat, loitsut, tilat, CR/XP)
- `rules.py`, `dice.py` — puhtaat säännöt ja nopat (ei Telegramia, ei tietokantaa)
- `engine.py`, `combat.py`, `spells.py`, `features.py`, `creation.py`, `items.py` — pelilogiikka
- `db.py` — SQLite ja migraatiot (schema_version 3, vanhat kampanjat siirtyvät automaattisesti)
- `ai.py` — Claude-kutsut (maailma, hahmoehdotukset, viholliset, saalis, sceneet)
- `handlers/` — Telegram-kerros: `setup`, `hero`, `story`, `checks`, `items`, `magic`, `fight`, `turns`, `common`
- `bot.py` — käynnistys ja komentovalikko

Tietoiset yksinkertaistukset: ei paikannusta (hiipivä isku: mikä tahansa tajuissaan oleva liittolainen,
aluevaikutukset osuvat rajattuun määrään vihollisia), ei kamppailua/Dash/Ready-toimintoja,
Suojelu- ja Kahden aseen taistelutyylejä ei ole, Vahvistus vain tekstinä, XP jaetaan tasan.

## Miten AI pidetään johdonmukaisena

Scenegeneraattorille syötetään: maailma, hahmot terveydentiloineen, NPC:t, journalin
faktat, nykyinen sijainti, tiivistelmä vanhoista sceneistä, viimeiset 5 sceneä
sanatarkasti, pelaajien ilmoittamat toimet sekä kaikki edellisen scenen jälkeiset
tapahtumat (heitot, hyökkäykset, vahinko, tasonnousut). Kun sceneja kertyy, vanhimmat
tiivistetään automaattisesti, joten pitkäkään kampanja ei unohda alkuaan.
