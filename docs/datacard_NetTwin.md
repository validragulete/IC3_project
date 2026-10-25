# Data card — NetTwin CP1

## 1. Sursa și scop
Sursă: Cisco Innovation Edge, [Cisco Network Telemetry Dataset](https://github.com/cisco-ie/telemetry), arhiva `telemetry-master`.
Scop CP1: audit și pregătire a telemetriei publice pentru detectarea anomaliilor de rețea. Datele nu sunt colectate din PNETLab.

## 2. Subset ales
Au fost extrase experimentele Cisco: `0/baseline_no_anomaly.csv.gz` (baseline), `2/bgpclear.csv.zip` (BGP Clear), `4/portflaptypes.csv.gz` (Port Flap) și `9/admin_down_20180724_45m.csv.zip` (Port Admin Shut). Numerele declarate de evenimente (0, 11, 5, 5) descriu scenariile, nu etichete validate pentru fiecare rând. Arhivele interioare au fost extrase în `data/raw/{0,2,4,9}/`.

## 3. Perioada și rezoluția
Intervale UTC măsurate din coloana `time` (epoch Unix în nanosecunde; parserul a fost actualizat pentru formatul de 19 cifre):

| Experiment | Prima observație UTC | Ultima observație UTC | Acoperire măsurată | Interval median pozitiv între rânduri |
|---|---|---|---:|---:|
| 0 — baseline | 2017-08-18 01:29:28.251 | 2017-08-18 02:29:33.032 | 60 min 05 s | 2 ms |
| 2 — BGP Clear | 2017-06-29 16:34:32.913 | 2017-06-29 17:24:32.817 | 50 min | 2 ms |
| 4 — Port Flap | 2017-09-01 17:08:57.222 | 2017-09-01 18:09:02.622 | 60 min 05 s | 2 ms |
| 9 — Port Admin Shut | 2018-07-26 22:49:41.053 | 2018-07-26 23:34:40.519 | 45 min | 2 ms |

Intervalul de 2 ms este între rânduri consecutive într-un CSV cu producători/serii multiple; nu reprezintă frecvența garantată per dispozitiv sau metrică. Timestamp-urile repetate sunt așteptate în date multi-serie. Acoperirea observată poate diferi de durata incidentului din documentația scenariului.

## 4. Variabile și unități
CSV-urile au 87 coloane (0 și 2), 99 coloane (4) și 161 coloane (9). Câmpurile includ dispozitiv/producător, calea de telemetrie, timestamp și metrici eterogene pentru interfețe, BGP, drop-uri, resurse și starea porturilor. Câmpurile diferă între experimente.
Unitățile sunt specifice câmpului și modelului Cisco IOS XR. Se consultă `baseline_header_definitions.pdf` / `baseline_header.txt` (0 și 2), `portflap_header_definitions.pdf` / `portflap_header.txt` (4) și documentația/headerul experimentului 9. Nu se deduce unitatea din numele coloanei. `time` este epoch Unix în nanosecunde.

## 5. Goluri și calitate
| Fișier | Rânduri | Coloane | Celule lipsă raportate* |
|---|---:|---:|---:|
| `baseline_no_anomaly.csv` | 976.821 | 87 | 67.123.425 |
| `bgpclear.csv` | 743.514 | 87 | 51.085.151 |
| `portflaptypes.csv` | 1.227.576 | 99 | 99.667.076 |
| `admin_down_20180724_45m.csv` | 592.539 | 161 | 84.760.460 |

*Suma celulelor goale/NA textual pe coloane. Lipsurile sunt frecvente deoarece rândurile combină căi de telemetrie diferite, cu câmpuri aplicabile doar anumitor serii. Vezi `results/audit_report.md` și `results/audit.json` pentru defalcarea completă. Coloana `time` a fost identificată și parsată în toate fișierele. Timestamp-urile repetate nu indică automat duplicate.
Limitări: etichetele incidentelor trebuie aliniate cu fișierele Cisco ground truth/case; auditul nu validează etichetele la nivel de rând. Datele publice nu acoperă direct starea MPLS L2VPN/L3VPN din laboratorul propriu.

## 6. Protocol train/test propus pentru CP2
Împărțire temporală pe sesiuni/experimente distincte, fără amestecarea ferestrelor între train și test. Definirea finală și prevenirea leakage-ului se validează în CP2; în CP1 nu se antrenează model.

## 7. Proveniență și licență
Cisco Innovation Edge, [repository](https://github.com/cisco-ie/telemetry). Arhiva conține `LICENSE.CDLA`: Community Data License Agreement — Permissive, Version 1.0 (CDLA-Permissive-1.0). Respectă termenii și păstrează atribuirea.

## 8. Pipeline și reproductibilitate
Comandă: `python src/load_data.py --input data/raw --output results`.
Output: `results/audit.json` și `results/audit_report.md`.
Parserul din `src/load_data.py` suportă timestamp-uri epoch în secunde, milisecunde, microsecunde și nanosecunde.
Repo personal: [adaugă linkul după publicare].

## 9. Date proprii PNETLab
Neimplementate la CP1. Colectarea SNMP/Syslog și evaluarea MPLS VPN sunt obiective ulterioare.
