Käytä aina `ponytail`-skilliä koodaustehtävissä.

# Projekti

Venäjänkielinen Telegram-botti D&D-ryhmäpeliin. Claude generoi maailman, hahmoehdotukset, NPC:t, viholliset, saaliin ja sceneet. Botti hoitaa säännöt (D&D 5e Basic Rules, lähde `C:\Users\NikitaEssine\Downloads\DnD_BasicRules_2018.pdf`). Käyttäjä puhuu suomea, botin tekstit ovat venäjäksi, README on suomeksi.

Stack: Python (paikallinen venv 3.12, palvelimella 3.14), aiogram 3.x, anthropic SDK, SQLite (`game.db`), pytest.

# Rakenne

- Puhdas logiikka, ei Telegramia: `srd.py` (taulukot), `spelldata.py` (loitsut), `dice.py`, `rules.py`
- Pelilogiikka: `engine.py` (tarkistukset, vahinko, XP), `combat.py`, `spells.py`, `features.py` (luokkakyvyt, lepo), `creation.py`, `items.py`
- `db.py`: skeema + migraatiot (`SCHEMA_VERSION = 3`). Vanhat kampanjat migroituvat automaattisesti.
- `ai.py`: Claude-kutsut. `handlers/`: Telegram-kerros (`setup`, `hero`, `story`, `checks`, `items`, `magic`, `fight`, `turns`, `common`). `bot.py`: käynnistys.
- Kaikki HTML-viestit: käyttäjän tai mallin teksti aina `esc()`:n läpi, ja kulmasulut ohjeteksteissä muodossa `&lt;…&gt;` (muuten Telegram hylkää viestin). `answer_long`/`edit_long` putoavat pelkkään tekstiin jos jäsennys epäonnistuu.

# Ajaminen ja testit

Testit (BOT_TOKEN pitää olla asetettu, arvolla ei ole väliä):

    $env:BOT_TOKEN='1:a'; $env:ANTHROPIC_API_KEY='x'; .\venv\Scripts\python.exe -m pytest -q

Tila viimeksi: 207 testiä läpi. Testit eivät lähetä Telegramiin mitään, joten HTML-jäsennysvirheet eivät näy niissä.

# Deploy

Google Cloud e2-micro VM, systemd-palvelu `dnd-bot`, kansio `/opt/dnd_tg_bot`.

1. Paikallisesti: `git add . && git commit && git push`
2. VM:llä (SSH Compute Enginen kautta): `sudo /opt/dnd_tg_bot/deploy/update.sh`
3. Lokit: `sudo journalctl -u dnd-bot -n 50 --no-pager`

Tuotannon tietokanta on tehty vanhalla skeemalla (esim. `characters.attributes` on NOT NULL ilman oletusta). Siksi uusi koodi kohtaa vanhan skeeman, ei vain tuoreen. Testaa migraatiot vanhaa skeemaa vastaan.

# Tila

- Sääntöuudistus (rodut, luokat, taistelu, loitsut, varusteet) on koodattu ja deployattu (commit `95f3e32`).
- Korjattu tuotantoa kokeillessa: (1) HTML-jäsennysvirhe ohjeviesteissä (deployattu), (2) hahmon tallennus kaatui vanhan skeeman `attributes`-sarakkeeseen ja näkyi väärällä viestillä "hahmo varattu" (korjaus `db.py`:ssä, commit `9c1523f`, **deploy palvelimelle ei vahvistettu**, tarkista että `git push` ja `update.sh` on ajettu).
- Hahmonluonti, taistelu ja loitsut on testattu vain yksikkötesteillä, ei vielä oikeassa Telegram-ryhmässä. Ensimmäinen oikea koe tehty vain `/hero`-polulle.
- Avoin kysymys: voiko pelinjohtajalla olla hahmo? Nyt voi (botti ei estä). Tarjottu vaihtoehtoja (esto tai tila jossa GM ei näe salaisia heittoja), käyttäjä ei ole vielä päättänyt.

# Tietoiset yksinkertaistukset

- Ei sijaintien seurantaa: hiipivä isku vaatii vain tajuissaan olevan liittolaisen, aluevaikutukset osuvat rajattuun määrään vihollisia.
- Ei kamppailua eikä Dash/Disengage/Ready-toimintoja. Ei Protection- eikä Two-Weapon Fighting -tyylejä.
- XP jaetaan tasan koko ryhmälle. Vain Basic Rulesin alaluokat (Life, Champion, Thief, Evocation).
- Vain noin 50 loitsulla on mekaniikka, muut kuluttavat paikan ja kirjautuvat tarinaan.
- Luokkakyvyt n. tasolta 10 ylöspäin enimmäkseen vain kuvauksina.
