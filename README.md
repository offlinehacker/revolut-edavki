# Revolut -> FURS eDavki konverter
_Skripta, ki prevede Revolut CSV poročilo trgovalnih poslov, dividend in obresti (Flexible Cash Funds) v XML format primeren za uvoz v obrazce:_
* _Doh-KDVP - Napoved za odmero dohodnine od dobička od odsvojitve vrednostnih papirjev in drugih deležev ter investicijskih kuponov,_
* _D-IFI - Napoved za odmero davka od dobička od odsvojitve izvedenih finančnih instrumentov in_
* _Doh-Div - Napoved za odmero dohodnine od dividend_
* _Doh-Obr - Napoved za odmero dohodnine od obresti_
_v eDavkih Finančne uprave._

Poleg pretvorbe vrednosti skripta naredi še konverzijo iz tujih valut v EUR po tečaju Banke Slovenije na dan posla (če za ta dan tečaja ni, uporabi zadnji predhodni razpoložljiv tečaj).

## Izjava o omejitvi odgovornosti

Davki so resna stvar. Avtor(ji) skripte si prizadevam(o) za natančno in ažurno delovanje skripte in jo tudi sam(i)
uporabljam(o) za napovedi davkov. Kljub temu ne izključujem(o) možnosti napak, ki lahko vodijo v napačno oddajo davčne
napovedi. Za pravilnost davčne napovedi si odgovoren sam in avtor(ji) skripte za njo ne prevzema(mo) nobene odgovornosti.

Če ti je skripta prihranila nekaj ur, nam največ veselja narediš s tem, da nekaj dobička podariš v dober namen. Slikaj priloženo QR kodo s svojo priljubljeno bančno aplikacijo ali klikni na njo:

[![revolut-davki / ZPM donacija](https://www.zveza-anitaogulin.si/wp-content/uploads/2024/07/QR-koda-za-BOTRSTVO-115.jpg)](https://www.zveza-anitaogulin.si/donatorji/donacija/)

## Uporaba

### Namestitev skripte

Na računalniku imej [zadnjo verzijo Python 3](https://www.python.org/downloads/) in [git](https://git-scm.com/downloads).

#### Namestitev `uv` (priporočeno)

`uv` je hiter upravljalnik Python okolij in paketov.

Linux/macOS:
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Preveri namestitev:
```
uv --version
```

Namestitev orodja z `uv`:
```
uv tool install https://github.com/offlinehacker/revolut-edavki.git
```

Lahko pa ga zaženeš tudi brez trajne namestitve:
```
uvx --from https://github.com/offlinehacker/revolut-edavki.git revolut_davki --help
```

#### Namestitev s `pip` (alternativa)

```
pip install --upgrade https://github.com/offlinehacker/revolut-edavki.git
```

```
revolut_davki
```

Odpri datoteko **taxpayer.xml** in vnesi svoje davčne podatke.

### Izvoz poročila v Revolut

1. V Revolut odpri **Investments** in nato **Statements** (oziroma enakovreden meni za izvoz poročil).
1. Izberi letno obdobje (od **1. 1.** do **31. 12.** za leto napovedi).
1. Izberi **Consolidated statement** in format **CSV**.
1. Preveri, da poročilo vsebuje sekcije:
   - `Transactions for Brokerage Account sells`
   - `Transactions for Brokerage Account dividends`
   - `Transactions for Flexible Cash Funds`
1. Datoteko shrani lokalno (npr. `consolidated-statement_2025-01-01_2025-12-31.csv`).

**Pozor**:
Če uporabljaš starejši Revolut izvoz ali CSV brez zgornjih sekcij, pretvorba ne bo popolna.

### Konverzija Revolut poročila v popisne liste primerne za uvoz v eDavke

```
revolut_davki --csv revolut-izvoz.csv [-y report-year] [-t] [--ignore-foreign-tax]
```
Primer:
```
revolut_davki --csv consolidated-statement_2025-01-01_2025-12-31.csv -y 2025
```
Primer brez uveljavljanja tujega davka pri dividendah:
```
revolut_davki --csv consolidated-statement_2025-01-01_2025-12-31.csv -y 2025 --ignore-foreign-tax
```

Skripta po uspešni konverziji v lokalnem direktoriju ustvari štiri datoteke:
* Doh-KDVP.xml (datoteka namenjena uvozu v obrazec Doh-KDVP - Napoved za odmero dohodnine od dobička od odsvojitve vrednostnih papirjev in drugih deležev ter investicijskih kuponov)
* D-IFI.xml (datoteka namenjena uvozu v obrazec D-IFI - Napoved za odmero davka od dobička od odsvojitve izvedenih finančnih instrumentov)
* Doh-Div.xml (datoteka namenjena uvozu v obrazec Doh-Div - Napoved za odmero dohodnine od dividend)
* Doh-Obr.xml (datoteka namenjena uvozu v obrazec Doh-Obr - Napoved za odmero dohodnine od obresti)

#### -y <leto> (opcijsko)
Leto za katerega se izdelajo popisni listi. Privzeto preteklo leto.

#### -t (opcijsko)
eDavki ne omogočajo dodajanje popisnih listov za tekoče leto, temveč le za preteklo. Parameter *-t* spremeni datume vseh poslov v preteklo leto, kar omogoča uvoz popisnih listov in **informativni izračun davka** že za tekoče leto. Konverzija iz tuje valute v EUR je kljub temu opravljena na pravi datum posla.

**Pozor: namenjeno informativnemu izračunu, ne oddajaj obrazca napolnjenega s temi podatki!**

### Testiranje

Repo vsebuje sintetičen testni CSV (`tests/fixtures/revolut_synthetic_2025.csv`) z izmišljenimi podatki in majhnimi zneski, ki preveri osnovni end-to-end tok generiranja XML-jev v začasnem direktoriju.

Zagon testa:
```
python -m unittest tests/test_synthetic_revolut_pipeline.py
```

#### Dodatni podatki o podjetju za obrazec Doh-Div (opcijsko)
Obrazec Doh-Div zahteva dodatne podatke o podjetju, ki je izplačalo dividende (identifikacijska številka, naslov, ...), ki jih v izvirnih podatkih Revoluta pogosto ni. Ob prvi uporabi skripta prenese datoteko `companies.xml`, ki že vsebuje nekaj podjetij. Manjkajoča podjetja lahko dodaš v `companies-local.xml` ali pa manjkajoče podatke po uvozu obrazca vneseš v eDavkih.
*Če boš v `companies-local.xml` vnesel več novih podjetij, jih bomo avtomatično prenesli v `companies.xml` - prosimo, naredi pull request.*

Če je v Doh-Div izpolnjeno polje `ForeignTax` (tuji davek), eDavki zahtevajo obvezno prilogo `Dokazilo o plačilu tujega davka`. To je poslovno pravilo eDavkov (ne napaka XML strukture). Priloži izpis brokerja/statement, iz katerega so razvidni bruto dividenda, odtegnjeni tuji davek in datum izplačila.

#### --ignore-foreign-tax (opcijsko)
Ta parameter nastavi `ForeignTax` v `Doh-Div.xml` na `0.00` za vse dividende. Uporabno, če ne želiš uveljavljati odbitka tujega davka in se želiš izogniti obvezni prilogi `Dokazilo o plačilu tujega davka`.

**Pozor**: pri uporabi tega parametra ne uveljavljaš odbitka tujega davka (lahko pomeni višjo slovensko davčno obveznost pri dividendah).

#### Opomba za Doh-Obr (Flexible Cash Funds)
Za obresti iz Flexible Cash Funds skripta v Doh-Obr vpiše:
- bruto obresti iz vrstic `Interest PAID` (vrstice `Service Fee Charged` se ne štejejo med obresti),
- pretvorbo v EUR po tečaju Banke Slovenije,
- vrsto dohodka `7`,
- izplačevalca `Revolut Securities Europe UAB`.

### Referenčni dokumenti (sheme in navodila)
Pri implementaciji in preverjanju mapiranja so bili uporabljeni naslednji uradni eDavki/FURS dokumenti:

- XML sheme obrazcev:
  - `https://edavki.durs.si/Documents/Schemas/Doh_KDVP_9.xsd`
  - `https://edavki.durs.si/Documents/Schemas/D_IFI_4.xsd`
  - `https://edavki.durs.si/Documents/Schemas/Doh_Div_3.xsd`
  - `https://edavki.durs.si/Documents/Schemas/Doh_Obr_2.xsd`
  - `https://edavki.durs.si/Documents/Schemas/EDP-Common-1.xsd`
- Portal z dokumenti za Doh-Obr (druge obresti):
  - `https://edavki.durs.si/EdavkiPortal/OpenPortal/CommonPages/Opdynp/PageD.aspx?category=odmera_dohodnine_od_drugih_obresti`
- Navodila in tehnični dokumenti za Doh-Obr:
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_dr_obr20.n.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_dr_obr20.i.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_obr_xml.n.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_obr_xml.i.xlsx`
- Portal z dokumenti za Doh-Div (dividende):
  - `https://edavki.durs.si/EdavkiPortal/OpenPortal/CommonPages/Opdynp/PageD.aspx?category=odmera_dohodnine_od_dividend`
- Navodila in tehnični dokumenti za Doh-Div:
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_div20.n.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_div.n.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_div_xml.n.sl.pdf`
  - `https://edavki.durs.si/OpenPortal/Dokumenti/doh_odm_div_xml.i.xlsx`

Iz teh dokumentov izhajajo ključne odločitve v skripti:
- pri Doh-Obr se poroča bruto obresti (v EUR),
- za Flexible Cash Funds se uporablja vrsta dohodka `7`,
- za Doh-Div sta v shemi predvidena tudi `CorpData` in `CorpDataDetail` (posebni primeri odsvojitve delnic/deležev), ki nista del običajnega mapiranja navadnih dividend,
- pri Doh-Div eDavki zahtevajo prilogo `Dokazilo o plačilu tujega davka`, kadar je vpisan `ForeignTax` (tuji davek).

### Uvoz v eDavke
>**Pozor**: Obrazec Doh-Div v eDavkih omogoča tudi uvoz podatkov v CSV obliki. `revolut-davki` ne generira obrazca Doh-Div v CSV obliki. Namesto uvoza CSV datoteke, se posluži uvoza XML datoteke, kot je opisan v nadaljevanju.

![Dokumenti > Uvoz](readme-uvoz.png)

1. V meniju **Dokument** klikni **Uvoz**. Izberi eno izmed generiranih datotek (Doh-KDVP.xml, D-IFI.xml, Doh-Div.xml, Doh-Obr.xml) in jo **Prenesi**.
1. Preveri izpolnjene podatke in dodaj manjkajoče.
1. Pri obrazcih Doh-KDVP in D-IFI je na seznamu popisnih listov po en popisni list za vsak vrednostni papir (ticker).
1. Klikni na ime vrednostnega papirja in odpri popisni list.
1. Klikni **Izračun**.
1. Preveri če vse pridobitve in odsvojitve ustrezajo dejanskim. Zaloga pri zadnjem vnosu mora biti **0**.

ali

1. V meniju **Dokumenti > Nov dokument** izberi obrazec Doh-KDVP (za trgovanje z vrednostnimi papirji na dolgo) ali D-IFI (za trgovanje z vrednostnimi papirji na kratko in trgovanje z izvedenimi finančnimi inštrumenti).
1. Izbira obdobja naj bo lansko leto.
1. Vrsta dokumenta naj bo **O**. Če si za preteklo leto že oddal obrazec, pa želiš le testno narediti izračun davka za tekoče leto, izberi **I**.
1. Izberi **Nov prazen dokument**.
1. Klikni **Uvoz popisnih listov** in izberi ustrezno datoteko (Doh-KDVP.xml za obrazec Doh-KDVP, D-IFI.xml za obrazec D-IFI) in klikni **Uvozi**.
1. Preveri izpolnjene podatke in dodaj manjkajoče.
1. Na seznamu popisnih listov se bo pojavil po en popisni list za vsak vrednostni papir (ticker).
1. Klikni na ime vrednostnega papirja in odpri popisni list.
1. Klikni **Izračun**.
1. Preveri če vse pridobitve in odsvojitve ustrezajo dejanskim. Zaloga pri zadnjem vnosu mora biti **0**.
