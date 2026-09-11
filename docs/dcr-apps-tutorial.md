# Tutorial: DCR Audience Overlap Console

Aplikasi berbasis UI untuk menjalankan **seluruh siklus Snowflake Data Clean Rooms
(DCR) Collaboration API v2** — dari mendaftarkan tabel, membuat kolaborasi,
menjalankan audience overlap, sampai aktivasi dan impor hasilnya — **tanpa
menulis SQL dan tanpa menulis YAML**.

> **Catatan penting.** Aplikasi ini dibangun **100% di atas Collaboration API v2**.
> Tidak ada satu pun ketergantungan pada DCR legacy (v1 / Native App / web app v1)
> yang akan di-*deprecate*. Lihat [Lampiran C](#lampiran-c--daftar-larangan-v1).

---

## Daftar Isi

1. [Untuk siapa tutorial ini](#1-untuk-siapa-tutorial-ini)
2. [Apa yang dibangun](#2-apa-yang-dibangun)
3. [Arsitektur singkat](#3-arsitektur-singkat)
4. [Prasyarat](#4-prasyarat)
5. [Bagian A — Deploy façade (backend)](#bagian-a--deploy-façade-backend)
6. [Bagian B — Deploy aplikasi Streamlit](#bagian-b--deploy-aplikasi-streamlit)
6. [Bagian B — Deploy aplikasi Streamlit](#bagian-b--deploy-aplikasi-streamlit)
7. [Bagian B2 — Deploy aplikasi React di SPCS](#bagian-b2--deploy-aplikasi-react-di-spcs-track-b)
8. [Bagian C — Menggunakan aplikasi (alur lengkap)](#bagian-c--menggunakan-aplikasi-alur-lengkap)
8. [Bagian D — Verifikasi kebenaran hasil](#bagian-d--verifikasi-kebenaran-hasil)
9. [Troubleshooting](#troubleshooting)
10. [Lampiran](#lampiran-a--daftar-30-operasi-façade)

---

## 1. Untuk siapa tutorial ini

| Peran | Bagian yang perlu dibaca |
|---|---|
| **Admin Snowflake** (sekali setup) | Bagian A, lalu B (Streamlit) dan/atau B2 (React), Troubleshooting |
| **Front-end / app developer** | Bagian B2 — struktur kode, development lokal, cara menambah fitur |
| **Data engineer / SE** | Semua |
| **User bisnis / marketing** | Bagian C saja |

Waktu setup pertama kali: **kurang lebih 45–60 menit per akun**, sebagian besar
menunggu proses provisioning kolaborasi DCR. Tambah ±10 menit kalau juga memasang
Track B.

---

## 2. Apa yang dibangun

**Satu backend (façade) + dua aplikasi UI** yang memakai façade itu:

| | Track A | Track B |
|---|---|---|
| Runtime | Streamlit in Snowflake | React (Next.js) di SPCS via Snowflake App Runtime |
| Objek | `DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE` | `SNOWFLAKE_APPS.PUBLIC.DCR_OVERLAP_CONSOLE_WEB` |
| Cocok untuk | enablement internal, POC, demo, cadangan | aplikasi untuk customer |
| Deploy | Bagian B | Bagian B2 |

Anda tidak wajib memasang keduanya. Kalau harus memilih satu: **Track B untuk
customer**, Track A kalau `FEATURE_SNOWFLAKE_APPS` belum aktif di akun.

Keduanya punya **10 halaman** yang sama, masing-masing memetakan satu tahap siklus
DCR:

| # | Halaman | Fungsi | Tahap DCR |
|---|---|---|---|
| 0 | **Health Check** | Cek prasyarat: versi DCR, mount API, template standar, privilege | (baru) |
| 1 | **My Data** | Pilih tabel/view, tentukan join key + tipe PII, tandai kolom yang boleh diaktivasi, daftarkan sebagai *data offering* | Register resources |
| 2 | **Create Collaboration** | Wizard 4 langkah: nama, kolaborator + account identifier, pemetaan resource, auto-join | Create collaboration |
| 3 | **Invitations** | Lihat undangan masuk, review spec, join dengan nama lokal | Review + Join |
| 4 | **Link Data** | Hubungkan data — **dua jenis link yang berbeda** (lihat catatan di bawah) | Link data offering |
| 5 | **Run Overlap** | Bangun match key waterfall, filter, group-by, jalankan analisis, lihat hasil | Run analysis |
| 6 | **Activate** | Pilih kolom yang diaktivasi, pilih tujuan, beri nama segmen, kirim | Activation |
| 7 | **Activation Inbox** | **Impor** segmen hasil aktivasi dan *flatten* jadi tabel siap pakai | (bagian yang hilang di tutorial resmi) |
| 8 | **History** | Riwayat semua run dan aktivasi, dengan durasi dan status | Monitoring |
| 9 | **Admin** | Approve/reject update request, tambah template, Leave/Teardown, RBAC aplikasi | Manajemen |

### Dua hal yang perlu dipahami sebelum mulai

**Pertama — ada DUA jenis "link data" yang sering tertukar.** Ini penyebab nomor
satu kegagalan "kok overlap-nya tidak bisa jalan":

| | `LINK_DATA_OFFERING` | `LINK_LOCAL_DATA_OFFERING` |
|---|---|---|
| Siapa yang memanggil | **Data provider**, membagikan datanya **ke** analysis runner | **Analysis runner**, melampirkan tabel **miliknya sendiri** |
| Menjadi | `source_table` → alias `p1`, `p2` … | `my_table` → alias `c1`, `c2` … |
| Kena policy DCR | Ya (shared view, join/column policy) | Tidak (data lokal Anda sendiri) |
| Di UI Snowsight resmi | Ada | **Tidak ada** |

Kalau `LINK_LOCAL_DATA_OFFERING` tidak pernah dijalankan, runner tidak punya
`my_table`, overlap **mustahil dijalankan**, dan **tidak bisa diperbaiki dari
dalam AO&A app resmi**. Aplikasi ini menyediakan keduanya di halaman **Link Data**,
lengkap dengan banner merah kalau data lokal belum di-link.

**Kedua — progress bar persentase untuk overlap TIDAK mungkin.** `COLLABORATION.RUN`
bersifat sinkron dan *blocking*: tidak ada callback progres, tidak ada API
persentase. Yang aplikasi ini tampilkan dan semuanya nyata:

| Sinyal | Sumber | Nyata? |
|---|---|---|
| Spinner + waktu berjalan saat RUN | client | Ya (tanpa persen palsu) |
| Status badge pengiriman aktivasi (Pending/Completed/Failed) | `VIEW_ACTIVATIONS` | Ya |
| Riwayat run beserta durasi | `VIEW_ACTIVITY_HISTORY` + audit log | Ya |
| **Persentase impor** = baris masuk ÷ baris diharapkan | hitung `COUNT(*)` tabel target | Ya, persen sungguhan |

Satu-satunya persentase sungguhan di aplikasi ini ada di **Activation Inbox**,
karena di situ barisnya bisa dihitung.

---

## 3. Arsitektur singkat

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  Streamlit in Snowflake  │         │  React on SPCS (Track B) │
│  DCR_CONSOLE.UI          │         │  (belum dibangun)        │
└────────────┬─────────────┘         └────────────┬─────────────┘
             │                                    │
             └──────────────┬─────────────────────┘
                            ▼
              ┌─────────────────────────────┐
              │ DCR_CONSOLE.APP.INVOKE      │  ← SATU pintu masuk
              │ (operation, payload)        │     30 operasi, whitelist
              └─────────────┬───────────────┘
                            │
        ┌───────────────────┼────────────────────┐
        ▼                   ▼                    ▼
 dcr_specs.py        dcr_facade.py         dcr_runs.py
 (bangun YAML)       (setup/lifecycle)     (overlap/aktivasi)
        │                   │                    │
        └───────────────────┼────────────────────┘
                            ▼
              SAMOOHA_BY_SNOWFLAKE_LOCAL_DB
              REGISTRY / COLLABORATION / ADMIN
```

**Mengapa pakai façade (lapisan perantara)?** Karena logika yang mudah salah
hanya ditulis **satu kali**, bukan dua kali di Python dan TypeScript:

- YAML dibangun dengan *serializer* PyYAML, bukan gabungan string → hilang total
  kelas bug "kurang spasi setelah titik dua".
- Spec dikirim sebagai **argumen prosedur**, tidak pernah lewat `SET` (variabel
  sesi SQL dibatasi 256 byte — offering dengan 100+ kolom pasti gagal).
- Aturan *rename* kolom join, whitelist `column_type`, dan bentuk parameter
  (`source_tables`/`my_tables` itu **array**, bukan string) ditegakkan di satu tempat.
- Semua operasi tercatat di `DCR_CONSOLE.META.AUDIT_LOG`.

**Objek yang dibuat:**

```
DCR_CONSOLE
├── APP/
│   ├── INVOKE(operation, payload)   -- satu-satunya pintu masuk
│   └── LIB/                         -- stage berisi 4 modul Python
├── META/
│   ├── AUDIT_LOG                    -- siapa berbagi apa dengan siapa, kapan
│   ├── RUN_CACHE                    -- cache hasil overlap
│   ├── APP_USER_ROLE                -- RBAC level aplikasi
│   ├── SAVED_CONFIG                 -- preset konfigurasi
│   └── ACTIVATION_IMPORT            -- status impor segmen
└── UI/
    ├── STREAMLIT_STAGE
    └── DCR_OVERLAP_CONSOLE          -- objek Streamlit
```

---

## 4. Prasyarat

### 4.1 Wajib dipenuhi

| Syarat | Cara cek | Kalau gagal |
|---|---|---|
| DCR sudah ter-install | `SHOW DATABASES LIKE 'SAMOOHA_BY_SNOWFLAKE_LOCAL_DB'` | Install "Snowflake Data Clean Rooms" dari Marketplace |
| API sudah di-*mount* | `CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.LIBRARY.CHECK_MOUNT_STATUS()` → `true` | Jalankan `PREPARE_MOUNT_SCRIPT()` lalu `dcr_loader.sql` |
| Versi DCR ≥ 14.6 | `SELECT * FROM SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.VERSION` | `CALL ...LIBRARY.ENABLE_LOCAL_DB_AUTO_UPGRADES()` |
| Edisi Snowflake | Standard+ untuk overlap, **Enterprise+ untuk aktivasi** | Upgrade edisi |
| Akun berbayar | — | Trial dan reader account tidak didukung |
| Snowflake CLI | `snow --version` (≥ 3.20) | `pip install snowflake-cli` |

### 4.2 Identitas akun

Jalankan di **setiap** akun yang ikut kolaborasi, dan catat hasilnya:

```sql
SELECT CURRENT_ORGANIZATION_NAME() || '.' || CURRENT_ACCOUNT_NAME() AS ACCOUNT_IDENTIFIER;
SELECT CURRENT_USER() AS MY_USER;
```

> **Peringatan.** Yang dibutuhkan adalah format `ORG.ACCOUNT`, **bukan** account
> locator (`xy12345.ap-southeast-3.aws`) dan bukan URL Snowsight. Kalau salah,
> kolaborasi tetap terbuat tapi **partner tidak akan pernah melihatnya**, dan
> tidak ada pesan error saat pembuatan. Aplikasi ini menolak format yang salah di
> awal.

### 4.3 Dipasang di kedua akun

DCR bekerja per akun. Aplikasi ini **harus di-deploy di kedua akun** (provider dan
consumer). Setiap instance hanya bisa bertindak sebagai akun tempat ia berjalan.

```
  AKUN PROVIDER                            AKUN CONSUMER
 ┌────────────────────┐                   ┌────────────────────┐
 │ DCR Console        │                   │ DCR Console        │
 │ (instance sendiri) │                   │ (instance sendiri) │
 └─────────┬──────────┘                   └─────────┬──────────┘
           │           ── undangan ──▶              │
           │           ◀── hasil ───                │
```

---

## Bagian A — Deploy façade (backend)

Jalankan sebagai `ACCOUNTADMIN`. **Ulangi di setiap akun.**

### A-1. Buat role, database, dan schema

```bash
cd dcr-console/00_facade
snow sql -f 00_setup_role_and_db.sql
```

Script ini membuat:
- Role **`DCR_CONSOLE_ROLE`** — sengaja **bukan** `SAMOOHA_APP_ROLE`, karena
  grant role tersebut bisa ter-*reset* saat DCR di-upgrade dan aplikasi mati
  tanpa sebab yang jelas.
- Privilege akun yang dibutuhkan pembuat kolaborasi: `CREATE APPLICATION`,
  `CREATE DATABASE`, `CREATE SHARE`, `IMPORT SHARE`, `MANAGE SHARE TARGET`,
  `APPLY ROW ACCESS POLICY`, `EXECUTE TASK`.
- Privilege DCR lewat `ADMIN.GRANT_PRIVILEGE_ON_ACCOUNT_TO_ROLE`.
- Database `DCR_CONSOLE` dengan schema `APP`, `META`, `UI`.

### A-2. Buat tabel META dan stage

```bash
snow sql -f 01_meta_tables.sql
```

### A-3. Upload modul Python

```bash
for f in dcr_specs.py dcr_errors.py dcr_facade.py dcr_runs.py; do
  snow stage copy "$f" @DCR_CONSOLE.APP.LIB/ --overwrite
done
snow sql -q "ALTER STAGE DCR_CONSOLE.APP.LIB REFRESH;"
```

| Modul | Isi |
|---|---|
| `dcr_specs.py` | Pembangun YAML: offering, collaboration, analysis, activation. Satu-satunya tempat YAML dibuat. |
| `dcr_errors.py` | Penerjemah error DCR menjadi `{code, cause, remediation, sql_fix}` yang bisa ditindaklanjuti |
| `dcr_facade.py` | Operasi setup & lifecycle: health, register, create, join, link, preflight |
| `dcr_runs.py` | Operasi eksekusi: overlap, aktivasi, impor, history, admin |

### A-4. Deploy prosedur façade

```bash
snow sql -f 03_facade_procs.sql
```

Verifikasi — harus mengembalikan 30 operasi:

```sql
CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL);
```

### A-5. Grant akses ke data sumber

Untuk **setiap** database yang tabelnya akan dibagikan ke clean room. Edit
`91_grants/grants_source_data.sql` lalu jalankan.

> **Ini bagian yang paling sering terlewat.** `LINK_DATA_OFFERING` dan
> `LINK_LOCAL_DATA_OFFERING` tidak sekadar **membaca** data sumber — keduanya
> **memberikan grant** atas data itu kepada aplikasi kolaborasi. Sebuah role
> hanya bisa meneruskan privilege yang ia pegang **`WITH GRANT OPTION`**. Jadi
> `SELECT` biasa tidak cukup:
>
> ```
> 003102 (42501): Grant not executed: Insufficient privileges.
> ```

```sql
USE ROLE ACCOUNTADMIN;

-- Akses baca biasa
GRANT USAGE  ON DATABASE MY_DB              TO ROLE DCR_CONSOLE_ROLE;
GRANT USAGE  ON SCHEMA   MY_DB.MY_SCHEMA    TO ROLE DCR_CONSOLE_ROLE;

-- WITH GRANT OPTION — wajib, karena DCR meneruskan grant atas nama Anda
GRANT USAGE  ON DATABASE MY_DB              TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT USAGE  ON SCHEMA   MY_DB.MY_SCHEMA    TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT SELECT ON ALL TABLES    IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT SELECT ON FUTURE TABLES IN SCHEMA MY_DB.MY_SCHEMA TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;

-- REFERENCE_USAGE untuk REGISTER_DATA_OFFERING
GRANT REFERENCE_USAGE ON DATABASE MY_DB TO ROLE DCR_CONSOLE_ROLE WITH GRANT OPTION;
GRANT REFERENCE_USAGE ON DATABASE MY_DB TO ROLE ACCOUNTADMIN     WITH GRANT OPTION;

-- Schema tujuan hasil aktivasi yang sudah di-flatten
CREATE SCHEMA IF NOT EXISTS MY_DB.ACTIVATED;
GRANT USAGE, CREATE TABLE ON SCHEMA MY_DB.ACTIVATED TO ROLE DCR_CONSOLE_ROLE;
```

### A-6. Uji façade

```sql
CALL DCR_CONSOLE.APP.INVOKE('HEALTH_CHECK', OBJECT_CONSTRUCT('ui_track','sql'));
```

Yang diharapkan: `ready: true`, tanpa `blocking_failures`.

> Satu item akan muncul sebagai **`info`**, bukan `ok`, dan ini normal:
> **DCR privileges**. Prosedur `ADMIN.CHECK_PRIVILEGES` milik DCR menjalankan
> statement `USE` di dalamnya, dan Snowflake menolak itu di dalam *nested stored
> procedure*. Untuk memverifikasi manual, jalankan di worksheet:
>
> ```sql
> USE ROLE DCR_CONSOLE_ROLE;
> CALL SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.ADMIN.CHECK_PRIVILEGES(
>   ['CREATE COLLABORATION','JOIN COLLABORATION','REVIEW COLLABORATION',
>    'VIEW COLLABORATIONS','REGISTER DATA OFFERING','REGISTER TEMPLATE']);
> ```

---

## Bagian B — Deploy aplikasi Streamlit

```bash
cd dcr-console/track_a_streamlit
bash deploy_streamlit.sh
```

Script ini membuat stage, mengunggah 13 file (shell + 10 halaman + 2 lib), lalu
membuat objek Streamlit `DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE`.

Buka lewat Snowsight → **Streamlit** → `DCR_OVERLAP_CONSOLE`.

### Beri akses ke user bisnis

Aplikasi berjalan dengan **owner's rights** (`DCR_CONSOLE_ROLE`). User bisnis
**tidak boleh** diberi `SAMOOHA_APP_ROLE`.

```sql
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS DCR_BUSINESS_USER;

-- Ketiga grant USAGE ini wajib semuanya — hierarki objek harus lengkap
GRANT USAGE ON DATABASE DCR_CONSOLE                              TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON SCHEMA   DCR_CONSOLE.UI                           TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON STREAMLIT DCR_CONSOLE.UI.DCR_OVERLAP_CONSOLE      TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON WAREHOUSE APP_WH                                  TO ROLE DCR_BUSINESS_USER;

GRANT ROLE DCR_BUSINESS_USER TO USER NAMA_USER;   -- username literal, bukan CURRENT_USER()
```

> `GRANT ROLE ... TO USER CURRENT_USER()` adalah *syntax error* — GRANT tidak
> mengevaluasi fungsi. Tulis username-nya secara literal.

Opsional, batasi kemampuan di level aplikasi lewat halaman **Admin → App RBAC**:

| Tier | Bisa apa |
|---|---|
| `VIEWER` | Lihat dashboard dan history |
| `ANALYST` | + jalankan overlap |
| `ACTIVATOR` | + jalankan aktivasi dan impor segmen |
| `BUILDER` | + daftarkan offering, buat/join kolaborasi, teardown |

Ini hanya **mempersempit** apa yang ditawarkan UI. Otoritas final tetap privilege
DCR itu sendiri.

---

## Bagian B2 — Aplikasi React di SPCS (Track B)

Ada **dua aplikasi** yang memakai façade yang sama. Track A (Streamlit) untuk
kecepatan; Track B (React di SPCS) untuk UI yang paling mendekati web app DCR
lama. Pilih salah satu, atau pasang keduanya untuk dibandingkan.

Bagian ini lengkap: prasyarat, struktur kode, cara deploy, development lokal,
cara menambah fitur, kustomisasi, dan troubleshooting khusus Track B.

### B2-1. Prasyarat tambahan (hanya Track B)

| Syarat | Cara cek | Kalau belum ada |
|---|---|---|
| `FEATURE_SNOWFLAKE_APPS` aktif di akun | `SHOW DATABASES LIKE 'SNOWFLAKE_APPS'` | Minta ke tim akun Snowflake Anda |
| Snowflake App Runtime sudah di-setup | database `SNOWFLAKE_APPS` ada | Snowsight → nama Anda → Settings → Account → Apps → **Begin Setup** (sekali saja) |
| `BIND SERVICE ENDPOINT` | `SHOW GRANTS TO ROLE <role>` | `GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE DCR_CONSOLE_ROLE;` |
| Node.js 20+ | `node --version` | Install Node |
| Snowflake CLI 3.20+ | `snow --version` | `pip install -U snowflake-cli` |
| Façade sudah jalan | `CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL)` | Selesaikan Bagian A dulu |

> **Kalau `FEATURE_SNOWFLAKE_APPS` belum aktif, Track B tidak bisa di-deploy sama
> sekali.** Ini alasan nyata kenapa Track A dibangun juga — ia jadi cadangan yang
> tidak butuh prasyarat apa pun di luar DCR.

### B2-2. Struktur kode dan peran tiap berkas

```
track_b_react/                        (~4.280 baris termasuk lib)
├── package.json                      Next.js 14, React 18, recharts, snowflake-sdk
├── tsconfig.json                     strict: true — tipe menangkap perubahan kontrak façade
├── next.config.mjs                   output: "standalone" (wajib untuk SPCS)
├── snowflake.yml                     konfigurasi Snowflake App Runtime
├── app.yml                           executeAsCaller: true (untuk audit trail)
├── deploy.sh                         5 tahap: verifikasi façade → tsc → build → deploy → open
│
├── lib/
│   ├── snowflake.ts     (430)        Auth SPCS + connection pooling. TIDAK ada kode DCR.
│   ├── types.ts         (266)        Kontrak façade sebagai tipe TypeScript
│   └── facade.ts                     Klien ber-tipe: satu fungsi per operasi
│
├── app/api/
│   ├── facade/route.ts               Proxy ke INVOKE — 29 dari 30 operasi
│   └── direct/route.ts               HANYA REVIEW + JOIN (lihat B2-6)
│
├── app/
│   ├── layout.tsx                    Shell + sidebar
│   ├── globals.css                   Styling, tanpa framework CSS
│   ├── page.tsx                      Beranda: ringkasan kolaborasi
│   ├── health/          (0)          Health Check
│   ├── my-data/         (1)          Register offering
│   ├── collaborations/  (2)          Wizard buat kolaborasi
│   ├── invitations/     (3)          Review + join
│   ├── link/            (4)          Link data (dua jenis)
│   ├── analyze/         (5)          Run overlap + grafik
│   ├── activate/        (6)          Aktivasi + pilih kolom
│   ├── inbox/           (7)          Activation Inbox
│   ├── history/         (8)          Audit log
│   └── admin/           (9)          Update request, teardown, RBAC
│
└── components/
    ├── Nav.tsx                       Sidebar, dikelompokkan mengikuti siklus DCR
    ├── CollaborationPicker.tsx       Dipakai bersama semua halaman
    └── ui.tsx                        Card, Metric, StatusBadge, ErrorPanel, Progress
```

**Tiga berkas yang paling penting dipahami sebelum mengubah apa pun:**

| Berkas | Kenapa penting |
|---|---|
| `lib/types.ts` | Cerminan kontrak façade. Kalau façade berubah, di sini yang error saat compile — bukan di depan user. |
| `lib/facade.ts` | Satu-satunya jalan browser menghubungi DCR. Semua halaman memanggil fungsi dari sini. |
| `app/api/direct/route.ts` | Satu-satunya yang sengaja melewati façade. Ada komentar panjang menjelaskan kenapa. |

### B2-3. Alur satu request, dari klik sampai DCR

Penting dipahami karena menentukan di mana Anda mencari saat ada masalah:

```
Browser (client component)
   │  fetch POST /api/facade  { operation, payload }
   ▼
Route handler (Node.js, di dalam container SPCS)
   │  querySnowflake("CALL DCR_CONSOLE.APP.INVOKE(?, PARSE_JSON(?))")
   │  auth: token SPCS dari /snowflake/session/token  →  owner's rights
   ▼
DCR_CONSOLE.APP.INVOKE          ← whitelist 30 operasi
   │  dcr_specs / dcr_facade / dcr_runs
   ▼
SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.{REGISTRY, COLLABORATION}
```

Konsekuensi praktis:
- **Error DCR** muncul di UI sudah diterjemahkan (ada `remediation` dan kadang
  `sql_fix` yang bisa langsung di-copy). Sumbernya `dcr_errors.py`, bukan React.
- **Error transport** (container mati, service restart) muncul sebagai
  `TRANSPORT_ERROR` dari `lib/facade.ts`. Cek `snow app events`.
- **Error tipe** tidak akan sampai runtime — `tsc` menahannya saat build.

### B2-4. Deploy

```bash
cd dcr-console/track_b_react
npm install
bash deploy.sh                          # pakai koneksi default
bash deploy.sh provider-connection  # atau tentukan koneksi
```

Script menjalankan lima tahap dan berhenti di tahap pertama yang gagal:

| Tahap | Perintah | Kalau gagal |
|---|---|---|
| 1 | `CALL ...INVOKE('LIST_OPERATIONS')` | Façade belum ada — selesaikan Bagian A |
| 2 | `npx tsc --noEmit` | Ada error tipe; perbaiki dulu, jangan di-skip |
| 3 | `npm run build` | Biasanya import salah atau server/client component tertukar |
| 4 | `snow app deploy` | Lihat troubleshooting B2-9 |
| 5 | `snow app open` | App sudah jalan, hanya gagal membuka browser |

Deploy pertama butuh **±4 menit** — sebagian besar habis di *endpoint
provisioning*, yang menampilkan `Endpoints provisioning in progress` belasan kali.
Ini normal, bukan hang. Deploy ulang ±2–3 menit.

Kalau sukses:

```
App ready at https://<hash>-<org>-<account>.snowflakecomputing.app
```

> **Jangan pakai `SHOW ENDPOINTS IN SERVICE`** untuk mencari URL-nya — untuk app
> SAR fungsi itu mengembalikan URL yang salah. Gunakan `snow app open` atau
> `SHOW APPLICATION SERVICES`.

Saat pertama dibuka, app mengarahkan ke halaman login Snowflake (OAuth). Ini
memang perilakunya: semua user app wajib punya akun Snowflake.

### B2-5. Beri akses ke user bisnis

```bash
snow sql -f ../91_grants/grants_business_users.sql
```

Script itu memberi akses ke **kedua** aplikasi sekaligus. Untuk Track B, **ketiga**
grant USAGE wajib ada semuanya — hierarki objek harus lengkap atau URL-nya menolak:

```sql
GRANT USAGE ON DATABASE SNOWFLAKE_APPS                  TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON SCHEMA   SNOWFLAKE_APPS.PUBLIC           TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON APPLICATION SERVICE
      SNOWFLAKE_APPS.PUBLIC.DCR_OVERLAP_CONSOLE_WEB     TO ROLE DCR_BUSINESS_USER;
GRANT USAGE ON WAREHOUSE APP_WH                         TO ROLE DCR_BUSINESS_USER;
```

App berjalan dengan **owner's rights**: semua panggilan DCR dieksekusi sebagai
role app, apa pun role user yang login. **User bisnis tidak perlu — dan tidak
boleh — diberi `SAMOOHA_APP_ROLE`.**

> Saat mencabut akses, gunakan `REVOKE USAGE ON APPLICATION SERVICE` — **bukan**
> `REVOKE ON SERVICE`. Yang kedua menyasar objek SPCS yang berbeda dan tidak
> berefek apa pun, tanpa pesan error.

Akses dikontrol di **dua lapis independen**, keduanya harus lolos:

| Lapis | Menentukan | Cara |
|---|---|---|
| Grant application service | Bisa membuka URL app atau tidak | `GRANT USAGE ON APPLICATION SERVICE` |
| Privilege kolaborasi DCR | Kolaborasi mana yang terlihat | `ADMIN.GRANT_PRIVILEGE_ON_OBJECT_TO_ROLE` |

User dengan grant app tapi tanpa privilege kolaborasi akan melihat **daftar
kosong** — bukan error. Ini pertanyaan support paling sering.

### B2-6. Kenapa ada dua route API

Ini bukan pilihan gaya arsitektur, tapi konsekuensi teknis:

| Route | Isi | Kenapa |
|---|---|---|
| `/api/facade` | 29 dari 30 operasi | Proxy ke `DCR_CONSOLE.APP.INVOKE` |
| `/api/direct` | **Hanya REVIEW + JOIN** | `JOIN` memanggil `SYSTEM$ACCEPT_LEGAL_TERMS`; Snowflake menolak fungsi ber-*side effect* di dalam stored procedure |

Error aslinya kalau dipaksa lewat façade:

```
090237 (42601): SQL compilation error:
Query called from a stored procedure contains a function with side effects
[SYSTEM$ACCEPT_LEGAL_TERMS].
```

**Jangan "merapikan" `/api/direct` dengan mengarahkannya ke `INVOKE`** — join akan
langsung rusak. Alasannya sudah ditulis panjang sebagai komentar di berkas itu
supaya tidak ada yang tergoda.

Ada konsekuensi kepemilikan yang juga penting: **role yang menjalankan JOIN
memiliki objek yang dibuat join itu** (`SFDCR_<collab>` dan
`SFDCR_LOCAL_<collab>`). Karena app yang melakukan JOIN, kepemilikan tetap di role
app dan tidak perlu adopsi grant belakangan.

### B2-7. Development lokal

Bisa dijalankan di laptop tanpa deploy ke SPCS. `lib/snowflake.ts` mendeteksi auth
secara berurutan:

1. Token SPCS di `/snowflake/session/token` (kalau di dalam container)
2. `SNOWFLAKE_USER` + `SNOWFLAKE_PASSWORD` dari environment
3. `~/.snowflake/connections.toml` — koneksi default

Jadi di laptop, cukup:

```bash
cd dcr-console/track_b_react
npm run dev
# buka http://localhost:3000
```

App akan memakai koneksi default dari `connections.toml`. Untuk memilih koneksi
lain:

```bash
SNOWFLAKE_CONNECTION_NAME=consumer-connection npm run dev
```

> Yang **tidak** bisa diuji lokal: caller's rights (`sf-context-current-user-token`
> hanya ada di dalam SPCS). Di lokal semua query jalan sebagai koneksi Anda. Untuk
> app ini tidak masalah, karena caller's rights hanya dipakai untuk audit trail.

Perintah lain:

```bash
npx tsc --noEmit      # cek tipe saja, cepat
npm run build         # build produksi, seperti yang dijalankan deploy.sh
```

### B2-8. Menambah fitur

**Menambah operasi façade baru ke UI** — empat langkah, dan tiga di antaranya
dipaksa oleh tipe:

1. Tambahkan operasi ke whitelist di `00_facade/03_facade_procs.sql`, deploy ulang façade.
2. Tambahkan tipe hasilnya di `lib/types.ts`.
3. Tambahkan wrapper di `lib/facade.ts`:
   ```ts
   export const myNewOp = (collaboration: string) =>
     invoke<MyNewOpData>("MY_NEW_OP", { collaboration });
   ```
4. Pakai di halaman. Tidak perlu menyentuh `/api/facade` — route itu meneruskan
   nama operasi apa pun, dan façade yang menolak kalau tidak dikenal.

**Menambah halaman baru:**

1. Buat `app/nama-halaman/page.tsx`, awali dengan `"use client"`.
2. Tambahkan entri di `components/Nav.tsx` pada grup yang sesuai.

**Pola yang dipakai konsisten di semua halaman** — ikuti supaya seragam:

```tsx
"use client";
import { CollaborationPicker } from "@/components/CollaborationPicker";
import { Card, ErrorPanel, PageHeader, Spinner } from "@/components/ui";

export default function MyPage() {
  const [collab, setCollab] = useState("");
  const [error, setError] = useState<DcrError | null>(null);
  // ...
  return (
    <>
      <PageHeader title="..." sub="..." />
      <CollaborationPicker value={collab} onChange={(n) => setCollab(n)} />
      {error ? <ErrorPanel error={error} raw={errorRaw} /> : null}
      <Card title="...">{/* ... */}</Card>
    </>
  );
}
```

`ErrorPanel` sudah merender `title`, `cause`, `remediation`, dan `sql_fix` dari
error façade. Jangan buat penanganan error sendiri — nanti kehilangan `sql_fix`
yang justru paling berguna.

### B2-9. Kustomisasi tampilan

Tidak ada framework CSS — semuanya di `app/globals.css` dengan CSS variables.
Untuk mengganti warna brand:

```css
:root {
  --brand: #29b5e8;        /* Snowflake blue */
  --brand-dark: #11567f;
  --ok: #1a7f37;
  --warn: #bf8700;
  --err: #d1242f;
}
```

Untuk mengganti judul dan label app (yang muncul di daftar Apps Snowsight), edit
`snowflake.yml`:

```yaml
meta:
  title: DCR Audience Overlap Console
```

Grafik ada di `app/analyze/page.tsx` memakai Recharts. Perlu diketahui: Recharts
menyumbang **104 kB** di route `analyze`, dibanding 1–5 kB di route lain. Kalau
ukuran bundle jadi masalah, di situ tempat pertama yang dilihat.

### B2-10. Operasional dan upgrade

```bash
snow app events --last 100    # log build dan runtime
snow app deploy               # deploy ulang setelah ada perubahan kode
snow app teardown             # hapus service saja; data DCR & audit log tetap aman
```

Upgrade cukup `snow app deploy` lagi. Data kolaborasi, audit log, dan cache tidak
terpengaruh karena semuanya ada di `DCR_CONSOLE.META`, bukan di dalam container.

### B2-11. Troubleshooting khusus Track B

| Gejala | Penyebab | Solusi |
|---|---|---|
| **504 / "Could not reach the application backend"** saat klik Join di React app | JOIN dijalankan oleh identitas service SPCS (`MANAGED_SERVICE_n`). DCR menuntut acting user punya `first_name`, `last_name`, `email` — dan identitas service **bukan objek user**, jadi tidak bisa di-`ALTER USER`. Instalasi mandek, request menggantung, gateway timeout | JOIN **tidak bisa** dilakukan dari app. Jalankan `REVIEW` + `JOIN` di worksheet sebagai orang dengan profil lengkap. Halaman Invitations sekarang menyediakan SQL siap-copy |
| `090655 (P0002): Please add your first/last name and email` | Profil acting user tidak lengkap | `ALTER USER <n> SET first_name=…, last_name=…, email=…`. Kalau acting user adalah identitas service, tidak ada yang bisa di-set — pindah ke worksheet |
| Status `INSTALLATION_FAILED`, dan `LEAVE` ditolak | `LEAVE` hanya sah dari `LOCAL_DROP_PENDING`/`LEAVING` | Panggil `REVIEW` ulang dengan source name yang sama, lalu `JOIN`. Baca kolom `DETAILS` dari `GET_STATUS` dulu untuk tahu sebabnya |
| Auto-join owner gagal dengan `SYSTEM$ACCEPT_LEGAL_TERMS` | Task auto-join DCR sendiri menjalankan JOIN di dalam stored procedure | Jangan pakai auto-join. Owner JOIN manual di level sesi. Centang auto-join sudah dihapus dari UI |
| `SecondaryRolesNotSupported: Secondary roles must be disabled` saat register / link | Sesi masih mengaktifkan secondary roles. DCR menolak karena privilege efektifnya jadi ambigu | Jalankan `USE SECONDARY ROLES NONE` di **level sesi**, lalu ulangi. Ini **tidak bisa** ditaruh di dalam `INVOKE` — `USE` dilarang di stored procedure. Kedua UI sudah melakukannya saat startup, jadi cukup reload halaman |
| URL app 404 atau tidak bisa diakses | Grant `BIND SERVICE ENDPOINT` hilang | `GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE <role>;` lalu deploy ulang |
| Deploy gagal "warehouse not found" | `snowflake.yml` menunjuk warehouse yang tidak ada | Edit `query_warehouse:` |
| Deploy gagal permission | App Runtime setup belum selesai | Snowsight → Settings → Account → Apps → Begin Setup |
| Build stuck > 3 menit | `package-lock.json` tidak sinkron, atau error TypeScript | `npm install`, lalu `npx tsc --noEmit` |
| Semua halaman menampilkan `TRANSPORT_ERROR` | Container gagal start | `snow app events --last 100` |
| `FACADE_CALL_FAILED` di semua halaman | Role app tidak punya USAGE pada `INVOKE`, atau façade belum ada | `CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL)` untuk memastikan |
| Sidebar kolaborasi kosong padahal ada | Privilege DCR bersifat per-role | Lihat `91_grants/adopt_joined_collaboration.sql` |
| Setelah sesi browser expired, state hilang | Re-auth OAuth mengembalikan user ke halaman awal | Pilih ulang kolaborasi. Keterbatasan yang diketahui. |
| `tsc` error `account is missing` | `@types/snowflake-sdk` menjadikan `account` wajib | Sudah ditangani: `baseConfig()` memakai `Partial<>` lalu cast |

Log app:

```bash
snow app events --last 100
snow app events --last 100 | grep -i error
```

### B2-12. Perbandingan singkat kedua track

Detail lengkap ada di [`COMPARISON.md`](COMPARISON.md), ditulis setelah keduanya
benar-benar dibangun dan di-deploy. Ringkasnya:

| | Track A (Streamlit) | Track B (React/SPCS) |
|---|---|---|
| Berkas | 14 | 24 |
| Baris kode aplikasi | ±640 | ±2.600 |
| Deploy pertama | ±25 detik | ±4 menit |
| Deploy ulang | ±20 detik | ±2–3 menit |
| Prasyarat akun | tidak ada | `FEATURE_SNOWFLAKE_APPS`, App Runtime, `BIND SERVICE ENDPOINT` |
| Analisis lama (blocking) | halaman membeku saat rerun | tetap responsif, ada penghitung waktu |
| Wizard multi-langkah | perlu `st.session_state`, tiap widget memicu rerun | wajar, *derived state* biasa |
| Kontrak façade | ketahuan salah saat runtime | ketahuan salah saat compile |
| JOIN yang nest-unsafe | otomatis benar (statement level sesi) | perlu route API terpisah |
| Biaya idle | warehouse saja | warehouse + compute pool |
| Yang bisa merawat | tim data (Python/SQL) | perlu yang paham TypeScript/React |
| Debug | stack trace muncul di app | perlu `snow app events` |
| Cocok untuk | enablement internal, POC, demo, cadangan | aplikasi untuk customer |

**Rekomendasi:** Track A untuk internal dan demo, **Track B untuk customer** —
karena permintaan awalnya adalah pengganti web app DCR lama untuk user bisnis, dan
yang menentukan bukan tampilannya melainkan `COLLABORATION.RUN` yang blocking
25–40 detik. Di Streamlit itu membekukan halaman karena model rerun; di React tetap
responsif.

Track A tetap berguna dan bukan pekerjaan terbuang: ia **cadangan** bila
`FEATURE_SNOWFLAKE_APPS` tidak tersedia di akun target, dan **implementasi
referensi** yang paling singkat dibaca.

Yang **tidak** berbeda antara keduanya: seluruh logika DCR, penerjemahan error,
preflight, penegakan kolom aktivasi, audit log, cache, dan angka overlap-nya
sendiri (249.778, sama persis dengan ground truth SQL). Itu memang tujuan façade —
membangun UI kedua tidak menyentuh logika DCR sama sekali.

---

## Bagian C — Menggunakan aplikasi (alur lengkap)

Contoh kasus: **Provider telco** membagikan atribut pelanggan, **Consumer bank**
mencocokkan dengan audiens marketing-nya, lalu hasil match dikirim ke bank.

### Langkah 1 — Health Check (kedua akun)

Buka halaman **0. Health Check** → klik **Run health check**.

Kalau **Standard overlap templates** merah, klik **Register standard templates**.
Kedua template `standard_audience_overlap_v0` dan
`standard_audience_overlap_activation_v0` **tidak** ter-install otomatis bersama
DCR — harus didaftarkan sekali per akun, **di setiap akun peserta**.

### Langkah 2 — Daftarkan data (kedua akun)

Halaman **1. My Data** → tab **Register new offering**.

1. **Pilih tabel**: Database → Schema → Table.
2. **Konfigurasi kolom.** Untuk setiap kolom tentukan:

   | Category | Kapan dipakai | Efek pada nama kolom |
   |---|---|---|
   | `join_standard` | Kunci pencocokan ber-PII | **Diganti nama** menjadi nilai `column_type` |
   | `join_custom` | Kunci pencocokan non-PII (mis. loyalty ID) | Nama asli dipertahankan |
   | `passthrough` | Atribut, dimensi, tanggal, partisi | Nama asli dipertahankan |
   | `timestamp` | Kolom waktu event | Diganti menjadi `TIMESTAMP` |
   | `event_type` | Penanda jenis baris | Nama asli |

   Untuk `join_standard`, `column_type` **wajib** dan hanya boleh dari daftar PII:

   ```
   email, hashed_email_sha256, hashed_email_b64_encoded,
   phone, hashed_phone_sha256, hashed_phone_b64_encoded,
   device_id, hashed_device_id_sha256, hashed_device_b64_encoded,
   ip_address, hashed_ip_address_sha256, hashed_ip_address_b64_encoded,
   first_name, hashed_first_name_sha256, hashed_first_name_b64_encoded,
   last_name, hashed_last_name_sha256, hashed_last_name_b64_encoded
   ```

   Nilai `dimension`, `date`, `partition`, `custom` **tidak valid** dan akan
   ditolak. Kalau tidak ada yang cocok, pakai `join_custom`.

   > **Aturan paling penting untuk diingat.** Kolom `join_standard` **berganti
   > nama** di shared view. `HASHED_MSISDN` yang dideklarasikan sebagai
   > `hashed_phone_sha256` akan muncul ke partner sebagai **`HASHED_PHONE_SHA256`**.
   > Aplikasi menampilkan nama hasil rename ini setelah pendaftaran — pakai nama
   > itu di join clause, bukan nama aslinya. Ini penyebab nomor satu error
   > "unauthorized column".

3. **Activation allowed.** Centang hanya kolom yang boleh keluar dari akun Anda.
   Default-nya **tidak dicentang** — ini disengaja, karena aktivasi kolom PII
   tidak bisa ditarik kembali setelah datanya keluar.

4. Beri **nama** + **versi** (mis. `telco_provider_offering` / `v1_0`) → **Register**.

   ID offering = `<nama>_<versi>`, mis. `telco_provider_offering_v1_0`.
   Mendaftar ulang dengan nama+versi yang sama akan **menimpa** yang lama.

### Langkah 3 — Buat kolaborasi (akun provider)

Halaman **2. Create Collaboration**.

1. **Nama** dan deskripsi.
2. **Kolaborator**: alias + account identifier `ORG.ACCOUNT` untuk masing-masing.
   Pilih **owner**.
3. **Analysis runners** — siapa yang boleh menjalankan overlap.

   > **Keputusan yang tidak bisa diubah dengan mudah.** Kalau Anda ingin **kedua
   > pihak** bisa menjalankan overlap, **keduanya harus terdaftar sebagai
   > `analysis_runners` sekarang**. Kolaborator yang tidak terdaftar di sini
   > **tidak akan pernah** bisa menjalankan analisis.

   > **Setiap kolaborator wajib punya peran.** API menolak spec yang punya
   > kolaborator tanpa peran (owner / analysis runner / data provider):
   > ```
   > SpecValidationError: The following collaborators are declared in
   > collaborator_identifier_aliases but have no role: PARTNER
   > ```
   > Untuk partner yang datanya menyusul, aplikasi otomatis menambahkannya
   > sebagai data provider dengan daftar offering kosong sebagai *placeholder*.

4. **Activation destinations** — siapa yang boleh menerima hasil aktivasi. Ini
   daftar terpisah dari analysis runner.
5. Centang **Auto-join**, isi warehouse (mis. `APP_WH`) → **Create collaboration**.

   Provisioning butuh **3–5 menit**. Status berjalan `CREATING → JOINING → JOINED`.

   > **Auto-join bisa gagal tanpa suara.** Pernah terjadi: panggilan
   > `INITIALIZE` sukses, tapi task auto-join gagal, dan status berhenti di
   > `CREATED` dengan kegagalannya terkubur di dalam JSON DETAILS:
   > ```json
   > {"auto_join": {"enabled": false, "failure_summary": "Unable to auto join...", "phase": "failed"}}
   > ```
   > Kalau status berhenti di `CREATED`, owner harus JOIN manual. Façade
   > menyediakan operasi `ENSURE_JOINED` yang memeriksa kondisi ini dan memanggil
   > JOIN bila perlu.

### Langkah 4 — Join kolaborasi (akun consumer)

Halaman **3. Invitations**. Undangan muncul di daftar.

1. Buka **Collaboration spec** untuk membaca apa yang Anda setujui.
2. Isi **nama lokal** (boleh berbeda dari nama aslinya).
3. Klik **Review and join**. Butuh 1–2 menit.

> **Detail teknis.** `REVIEW` dan `JOIN` dijalankan **di level sesi**, bukan lewat
> façade. Alasannya: `JOIN` memanggil `SYSTEM$ACCEPT_LEGAL_TERMS`, dan Snowflake
> menolak fungsi ber-*side effect* di dalam stored procedure:
> ```
> SQL compilation error: Query called from a stored procedure contains a function
> with side effects [SYSTEM$ACCEPT_LEGAL_TERMS].
> ```
> Di Streamlit ini transparan karena statement Streamlit berjalan di level sesi.
>
> **Konsekuensi penting:** role yang menjalankan JOIN **memiliki** semua objek
> yang dibuat oleh join itu (`SFDCR_<collab>` dan `SFDCR_LOCAL_<collab>`). Jadi
> biarkan aplikasi yang melakukan JOIN. Kalau admin JOIN dari worksheet dengan
> role lain, aplikasi tidak akan bisa mengoperasikan kolaborasi itu — perbaikannya
> ada di `91_grants/adopt_joined_collaboration.sql`.

### Langkah 5 — Link data (pihak yang menjalankan analisis)

Halaman **4. Link Data**. Pilih kolaborasi.

Halaman menampilkan dua daftar:
- **Partner offerings (source tables)** — data partner, sisi `p1`.
- **Your linked data (my tables)** — data Anda sendiri, sisi `c1`.

Kalau daftar kedua kosong, muncul banner merah. **Ini wajib diselesaikan.**

Tab **Link my own data** → pilih offering Anda → **Link my data**.

> **Kenapa `SHARED_WITH`, bukan nama view.** Aplikasi membedakan data partner dan
> data sendiri dari kolom `SHARED_WITH` (`["LOCAL"]` = milik sendiri), **bukan**
> dari awalan nama view. Dalam skenario satu akun (akun yang sama jadi provider
> sekaligus runner), **kedua** offering mendapat awalan `PROVIDER.`, sehingga
> pembedaan berdasarkan nama view akan salah.

### Langkah 6 — Jalankan overlap

Halaman **5. Run Overlap**.

Aplikasi menjalankan **preflight** lebih dulu dan akan menolak dengan alasan yang
spesifik daripada membiarkan Anda mengisi wizard lalu gagal:

- Belum ada data partner → provider harus share dulu.
- Belum link data sendiri → langkah 5.
- Template overlap tidak tersedia.
- **Tidak ada join key yang sama** — dengan penjelasan bahwa kolom `join_standard`
  di-*rename* jadi `column_type`, sehingga kedua sisi harus memakai `column_type`
  **yang sama** agar bisa cocok.

Konfigurasi:

1. **Data sources** — pilih dataset partner dan dataset Anda.
2. **Match keys** — logika *waterfall*:
   - Setiap **level** dicoba berurutan, yang cocok pertama menang (logika OR).
   - Beberapa key **dalam satu level** digabung dengan AND.
   - Contoh: level 1 = email, level 2 = phone → "cocokkan dengan email dulu,
     sisanya coba dengan phone".
3. **Filters** dan **group-by** (opsional) — hanya kolom yang diizinkan pemilik
   data yang ditawarkan.
4. **Run overlap analysis**.

Hasil: kartu metrik (Matched / Unmatched / Total / Match rate), tabel detail
waterfall, dan raw rows.

> Kalau hasil disembunyikan karena *privacy threshold* (< 5 baris cocok), itu
> jaminan privasi bekerja, **bukan** error. Perluas audiens: tambah level
> waterfall, kurangi filter, atau pakai data lebih besar.

Hasil identik akan dilayani dari **cache** agar tidak menagih ulang biaya scan.
Hilangkan centang **Use cached result** untuk memaksa run baru.

### Langkah 7 — Aktivasi

Halaman **6. Activate**.

1. **Data sources** dan **match keys** — otomatis terisi dari overlap terakhir.
2. **Columns to activate** — hanya kolom yang ditandai `activation_allowed` oleh
   pemiliknya yang muncul. Hilangkan centang kolom yang ingin Anda tahan.

   Penegakan berlapis tiga: UI hanya menawarkan kolom legal, façade memeriksa
   ulang permintaan terhadap `ACTIVATION_ALLOWED_COLUMNS` yang hidup, dan policy
   filter DCR sendiri adalah gerbang terakhir. Pemanggil yang melewati UI tetap
   tidak bisa menyelundupkan kolom yang ditahan pemiliknya.

3. **Destination** — hanya tujuan yang dideklarasikan saat pembuatan kolaborasi.
4. **Segment name** — **tidak boleh ada spasi**. Pakai underscore atau hyphen.
5. **Activate**.

### Langkah 8 — Impor hasil (akun penerima)

Halaman **7. Activation Inbox**.

**Ini langkah yang hilang di tutorial resmi.** Tanpa langkah ini aktivasi tampak
"berhasil" padahal marketer tidak mendapat apa pun yang bisa dipakai: datanya
masih berupa kolom VARIANT di dalam sebuah share.

1. Pilih batch aktivasi.
2. Isi **Target table** (`DB.SCHEMA.TABLE`).
3. **Import and flatten**.

Aplikasi melakukan tiga hal: `PROCESS_ACTIVATION`, mendeteksi nama kolom hasil
aktivasi dari payload VARIANT, lalu me-*flatten* `SEGMENT_RECORDS` menjadi tabel
datar yang sudah dibersihkan prefiks alias-nya.

Hasilnya berubah dari:

```json
{"ID": {"p1.TOP_GENRE": "Action", "c1.CUSTOMER_SEGMENT": "Medium Buyer", "join_clause": "..."}}
```

menjadi tabel biasa:

| TOP_GENRE | SUB_TYPE | VIEWER_TYPE | CUSTOMER_SEGMENT | MATCH_CRITERIA | BATCH_ID | SEGMENT_NAME | UPDATED_ON |
|---|---|---|---|---|---|---|---|
| Action | Mature | Standard | Medium Buyer | p1.HASHED_EMAIL_SHA256 = c1.HASHED_EMAIL_SHA256 | 202ba43b… | e2e_test_segment | 2026-09-08 17:08 |

Progress bar di sini menampilkan **persentase sungguhan** (baris masuk ÷ baris
diharapkan), karena di titik ini barisnya memang bisa dihitung.

### Langkah 9 — Monitoring

Halaman **8. History** — dua tab: audit log aplikasi (siapa melakukan apa, durasi,
status, error yang sudah diterjemahkan) dan activity history milik DCR.

### Langkah 10 — Selesai / bersihkan

Halaman **9. Admin** → tab **Leave / Teardown**.

| Aksi | Siapa | Efek |
|---|---|---|
| **Teardown** | Owner | Menghapus kolaborasi untuk **semua** pihak. Tidak bisa dibatalkan. |
| **Leave** | Kolaborator | Data Anda dilepas. **Tidak bisa join ulang.** |

Keduanya bersifat **asinkron dan harus dipanggil dua kali** di API mentah (panggil,
tunggu sampai `LOCAL_DROP_PENDING`, panggil lagi). Aplikasi menyembunyikan detail
ini — satu klik sudah cukup.

---

## Bagian D — Verifikasi kebenaran hasil

Jangan percaya aplikasi hanya karena ia melaporkan sukses. Bandingkan dengan SQL
biasa yang dihitung **di luar** clean room.

Konfigurasi yang sudah diverifikasi pada pembangunan aplikasi ini:

```
Dataset provider : DEMO_PROVIDER_DB.PUBLIC.C360_DEMO             (10.000.000 baris)
Dataset runner   : DEMO_CONSUMER_DB.DATA.MARKETING_AUDIENCE   (1.000.000 baris)
Join key         : HASHED_EMAIL → hashed_email_sha256
```

Ground truth dengan SQL biasa:

```sql
SELECT
  (SELECT COUNT(DISTINCT HASHED_EMAIL) FROM DEMO_CONSUMER_DB.DATA.MARKETING_AUDIENCE)
    AS CONSUMER_DISTINCT,
  (SELECT COUNT(*) FROM (
     SELECT DISTINCT c.HASHED_EMAIL
     FROM DEMO_CONSUMER_DB.DATA.MARKETING_AUDIENCE c
     JOIN DEMO_PROVIDER_DB.PUBLIC.C360_DEMO p ON p.HASHED_EMAIL = c.HASHED_EMAIL))
    AS TRUE_OVERLAP;
```

| Metrik | SQL langsung | Hasil aplikasi | Cocok |
|---|---|---|---|
| Consumer distinct | 1.000.000 | 1.000.000 | Ya |
| Overlap | **249.778** | **249.778** | **Ya, persis** |
| Match rate | 24,98% | 24,98% | Ya |
| Baris hasil aktivasi terimpor | 249.778 | **249.778** | **Ya, persis** |

Kalau angka aplikasi berbeda dari SQL, **aplikasinya yang salah** — bukan SQL-nya.

> **Catatan cara membaca hasil overlap.** Template mengembalikan beberapa baris:
> `METRIC_TYPE = OVERLAP`, `NON_OVERLAP`, dan sebuah baris ringkasan di
> `WATERFALL_LEVEL = 999`. Hanya baris `OVERLAP` yang boleh dijumlahkan. Kesalahan
> menjumlahkan semuanya menghasilkan angka lebih besar dari total — ini pernah
> terjadi saat pembangunan dan sudah diperbaiki.

---

## Troubleshooting

Façade menerjemahkan error DCR menjadi penjelasan yang bisa ditindaklanjuti,
lengkap dengan SQL perbaikannya bila ada. Tabel di bawah untuk rujukan.

| Gejala | Penyebab | Solusi |
|---|---|---|
| `Grant not executed: Insufficient privileges` saat link | Role tidak punya `WITH GRANT OPTION` pada data sumber | Jalankan grant di Bagian A-5 |
| `DatasetReferenceUsageWithGrantOptionMissingError` | Kurang `REFERENCE_USAGE ... WITH GRANT OPTION` | `GRANT REFERENCE_USAGE ON DATABASE <db> TO ROLE <role> WITH GRANT OPTION` |
| `ReferenceUsageGrantMissingException` saat JOIN | Normal saat pertama kali share sebuah database | Grant ke **share** yang disebut di pesan error. **Jangan** ke `SAMOOHA_BY_SNOWFLAKE_APP_SHARE` (itu milik v1 dan tidak ada di v2) |
| `Templates 'standard_audience_overlap_v0' do not exist` | Template standar belum didaftarkan | Halaman Health Check → **Register standard templates** |
| Sidebar kosong, tidak ada kolaborasi | Privilege DCR bersifat **per-role**. Kolaborasi dibuat role lain | Grant privilege object-level, lihat `91_grants/adopt_joined_collaboration.sql` |
| `Database 'SFDCR_LOCAL_<collab>' does not exist` | JOIN dijalankan role lain, yang kemudian memiliki objeknya | Biarkan aplikasi yang JOIN, atau jalankan script adopsi |
| `Unauthorized columns: p1.HASHED_MSISDN` | Memakai nama kolom asli, bukan nama hasil rename | Pakai nama yang ditampilkan di Link Data (`HASHED_PHONE_SHA256`) |
| `no role` saat create collaboration | Ada kolaborator tanpa peran | Tambahkan sebagai data provider dengan offering kosong |
| Status berhenti di `CREATED`, tidak pernah `JOINED` | Auto-join gagal tanpa suara | Owner JOIN manual, atau pakai operasi `ENSURE_JOINED` |
| `CollaborationInvitationNotFound` padahal undangan terlihat | Sudah pernah join, **atau** `LEAVE` tertahan di `LOCAL_DROP_PENDING` | Cek `GET_STATUS`. Kalau `LOCAL_DROP_PENDING`, panggil `LEAVE` sekali lagi untuk menuntaskan; undangan baru akan muncul kembali |
| Hasil overlap NULL / disuppress | Kurang dari 5 baris cocok — jaminan privasi | Perluas audiens, kurangi filter, hapus satu dimensi group-by |
| Aktivasi sukses tapi tabel tidak ada | Belum diimpor | Halaman **Activation Inbox** → Import and flatten |
| `Current session is restricted. USE ROLE not allowed` | Token akses membatasi sesi ke satu role | Tidak perlu ganti role — prosedur façade sudah berjalan dengan privilege ownernya |
| Overlap lebih besar dari total | Menjumlahkan baris `NON_OVERLAP` juga | Hanya jumlahkan `METRIC_TYPE = 'OVERLAP'` |
| `Listing ... not fulfilled to your current region` | Instalasi DCR usang, atau cross-region tanpa Cross-Cloud Auto-Fulfillment | Update DCR di kedua akun; aktifkan Cross-Cloud Auto-Fulfillment |

Audit log adalah tempat pertama untuk melihat apa yang terjadi:

```sql
SELECT EVENT_TS, ACTOR_USER, OPERATION, OUTCOME, DURATION_MS,
       ERROR_DECODED:title::STRING  AS ERROR_TITLE,
       ERROR_DECODED:remediation::STRING AS FIX
FROM DCR_CONSOLE.META.AUDIT_LOG
ORDER BY EVENT_TS DESC
LIMIT 20;
```

---

## Lampiran A — Daftar 30 operasi façade

```sql
CALL DCR_CONSOLE.APP.INVOKE('LIST_OPERATIONS', NULL);
```

| Kelompok | Operasi |
|---|---|
| Health | `HEALTH_CHECK`, `REGISTER_STANDARD_TEMPLATES` |
| Data | `LIST_DATA_OBJECTS`, `DESCRIBE_COLUMNS`, `REGISTER_OFFERING`, `LIST_OFFERINGS`, `UNREGISTER_OFFERING` |
| Kolaborasi | `CREATE_COLLABORATION`, `LIST_COLLABORATIONS`, `GET_STATUS`, `ENSURE_JOINED` |
| Join | `REVIEW_COLLABORATION`, `JOIN_COLLABORATION` |
| Link | `LINK_DATA`, `UNLINK_DATA`, `GET_COLLABORATION_DETAIL`, `PREFLIGHT` |
| Overlap | `RUN_OVERLAP` |
| Aktivasi | `RUN_ACTIVATION`, `LIST_ACTIVATIONS` |
| Impor | `IMPORT_ACTIVATION`, `GET_IMPORT_PROGRESS` |
| History | `ACTIVITY_HISTORY` |
| Admin | `LIST_UPDATE_REQUESTS`, `APPROVE_UPDATE_REQUEST`, `REJECT_UPDATE_REQUEST`, `ADD_TEMPLATE`, `TEARDOWN_OR_LEAVE` |
| RBAC | `GET_APP_ROLE`, `SET_APP_ROLE` |

Contoh pemanggilan langsung dari SQL:

```sql
CALL DCR_CONSOLE.APP.INVOKE('RUN_OVERLAP', PARSE_JSON('{
  "collaboration": "telco_audience_overlap",
  "config": {
    "source_tables": ["PROVIDER.telco_provider_offering_v1_0.subscribers"],
    "my_tables":     ["LOCAL.marketing_consumer_offering_v1_0.audience"],
    "match_levels": [[{"provider": "HASHED_PHONE_SHA256",
                       "consumer": "HASHED_PHONE_SHA256"}]]
  },
  "use_cache": false
}'));
```

---

## Lampiran B — Operasi yang aman & tidak aman di dalam stored procedure

Diverifikasi pada DCR **17.5**. Ini menentukan batas façade.

| Aman di dalam procedure | Tidak aman |
|---|---|
| `REGISTER_DATA_OFFERING` * | **`COLLABORATION.JOIN`** — memanggil `SYSTEM$ACCEPT_LEGAL_TERMS` |
| `INITIALIZE` | **`ADMIN.CHECK_PRIVILEGES`** — menjalankan statement `USE` |
| `LINK_DATA_OFFERING`, `LINK_LOCAL_DATA_OFFERING` * | **`USE SECONDARY ROLES NONE`** — statement `USE` |
| `RUN` (overlap dan aktivasi) | **Auto-join task DCR** — menjalankan JOIN, jadi kena batasan yang sama |
| `VIEW_*` (semua) | |
| `PROCESS_ACTIVATION` | |
| `TEARDOWN`, `LEAVE`, `GET_STATUS` | |

\* Aman untuk *dijalankan* di dalam procedure, tapi menuntut sesi pemanggilnya
sudah mematikan secondary roles. Jadi prasyaratnya berada di luar façade
meskipun operasinya sendiri di dalam. Lihat baris `USE SECONDARY ROLES NONE`.

### JOIN tidak cukup "di level sesi" — harus manusia

`JOIN` punya syarat kedua yang lebih keras daripada nest-safety, dan ini menutup
semua jalur dari app yang ter-deploy:

DCR menuntut acting user punya `first_name`, `last_name`, dan `email`, karena
JOIN menerima syarat hukum dan perjanjian butuh orang yang bisa disebut namanya.

| Model | Punya privilege DCR? | Punya profil user? | JOIN |
|---|---|---|---|
| Owner's rights (identitas service SPCS) | ya | **tidak** — bukan objek user, `ALTER USER` tidak ada sasarannya | gagal saat instalasi → 504 |
| Caller's rights (business user) | **tidak** — sengaja tanpa `SAMOOHA_APP_ROLE` | ya | gagal karena privilege |

Kesimpulannya JOIN adalah **tindakan administratif satu kali per kolaborasi**,
dijalankan orang di worksheet — bukan aktivitas business user. Halaman
Invitations di Track B karena itu tidak punya tombol Join; ia menampilkan spec
untuk ditelaah lalu menyerahkan SQL siap-copy. Ini batasan platform, bukan fitur
yang belum dibuat.

Yang tidak aman harus dijalankan **di level sesi** oleh lapisan UI. Di Streamlit
in Snowflake ini otomatis. Di React/SPCS, handler API harus memanggil `CALL`
secara langsung, bukan lewat `DCR_CONSOLE.APP.INVOKE`.

---

## Lampiran C — Daftar larangan v1

DCR legacy (v1) akan di-*deprecate*. Aplikasi ini tidak boleh bergantung padanya.

| Dilarang (v1 / legacy) | Yang dipakai (v2) |
|---|---|
| Web app DCR v1 | Aplikasi ini, di atas Collaboration API |
| `GRANT REFERENCE_USAGE ... TO SHARE SAMOOHA_BY_SNOWFLAKE_APP_SHARE` | Grant ke **share bikinan SCO** yang disebut di pesan error |
| Prosedur `PROVIDER.*` / `CONSUMER.*` (`provider.register_table`, `consumer.request_template`, `register_db`) | `SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.REGISTRY.*` dan `...COLLABORATION.*` |
| Model clean-room / template-request v1 | Spec `data_offering` / `collaboration` / `template` / `code_spec` dengan `api_version: 2.0.0` |
| Fork kode app legacy | Kode baru; hanya plumbing Snowflake generik yang boleh dipakai ulang |

Penegakan: façade adalah **satu-satunya** hal yang menyentuh DCR, dan ia hanya
memanggil `SAMOOHA_BY_SNOWFLAKE_LOCAL_DB.{REGISTRY, COLLABORATION, ADMIN, LIBRARY}`.

Perhatikan: pesan error DCR sendiri kadang **menyarankan** `register_db()` — itu
prosedur v1. Jangan diikuti. Pakai `GRANT REFERENCE_USAGE` biasa seperti di
Bagian A-5.

---

## Lampiran D — Struktur berkas

```
dcr-console/                              (repo git — commit setelah tiap perubahan)
├── 00_facade/                            BACKEND — dipakai kedua track
│   ├── 00_setup_role_and_db.sql          role, grant, database, schema
│   ├── 01_meta_tables.sql                tabel META + stage LIB
│   ├── 03_facade_procs.sql               prosedur INVOKE (dispatcher, 30 operasi)
│   ├── dcr_specs.py                      pembangun YAML — satu-satunya tempat YAML dibuat
│   ├── dcr_errors.py                     penerjemah error → {code, cause, remediation, sql_fix}
│   ├── dcr_facade.py                     operasi setup & lifecycle
│   ├── dcr_runs.py                       operasi eksekusi (overlap, aktivasi, impor)
│   ├── test_dcr_specs.py                 golden-file test terhadap spec yang terbukti jalan
│   └── test_dcr_errors.py                test dengan pesan error asli dari DCR 17.5
│
├── track_a_streamlit/                    TRACK A — Streamlit in Snowflake
│   ├── streamlit_app.py                  beranda
│   ├── environment.yml
│   ├── deploy_streamlit.sh
│   ├── lib/{facade.py, ui.py}
│   └── pages/0_…9_*.py                   10 halaman
│
├── track_b_react/                        TRACK B — React di SPCS
│   ├── package.json  tsconfig.json  next.config.mjs
│   ├── snowflake.yml                     konfigurasi Snowflake App Runtime
│   ├── app.yml                           executeAsCaller
│   ├── deploy.sh                         5 tahap dengan verifikasi façade lebih dulu
│   ├── lib/
│   │   ├── snowflake.ts                  auth SPCS + connection pooling (tanpa kode DCR)
│   │   ├── types.ts                      kontrak façade sebagai tipe
│   │   └── facade.ts                     klien ber-tipe
│   ├── app/api/
│   │   ├── facade/route.ts               proxy ke INVOKE (29 operasi)
│   │   └── direct/route.ts               HANYA REVIEW + JOIN (nest-unsafe)
│   ├── app/                              layout, globals.css, 11 halaman
│   └── components/                       Nav, CollaborationPicker, ui
│
├── 91_grants/
│   ├── grants_source_data.sql            grant data sumber (WITH GRANT OPTION!)
│   ├── grants_business_users.sql         akses user bisnis ke kedua app
│   └── adopt_joined_collaboration.sql    kalau JOIN dilakukan role lain
│
└── docs/
    ├── dcr-apps-tutorial.md              dokumen ini
    └── COMPARISON.md                     perbandingan kedua track, dari pengalaman
```

Jalankan test façade:

```bash
cd dcr-console/00_facade
python3 -m venv .venv && .venv/bin/pip install -q pytest pyyaml
.venv/bin/python -m pytest -q          # 62 test
```

---

## Ringkasan alur (TL;DR)

```
[Setup backend, sekali per akun]
  00_setup_role_and_db.sql → 01_meta_tables.sql → upload 4 modul Python
  → 03_facade_procs.sql → grant data sumber (WITH GRANT OPTION!)
  → uji: CALL DCR_CONSOLE.APP.INVOKE('HEALTH_CHECK', NULL)
        ↓
[Setup UI — pilih satu atau keduanya]
  Track A:  cd track_a_streamlit && bash deploy_streamlit.sh      (±25 detik)
  Track B:  cd track_b_react && npm install && bash deploy.sh     (±4 menit)
  → grant user bisnis: snow sql -f 91_grants/grants_business_users.sql
        ↓
[Provider]  Health Check → My Data (daftarkan) → Create Collaboration
        ↓                                              │ undangan
[Consumer]  Health Check → My Data (daftarkan) → Invitations (join)
        ↓
[Runner]    Link Data — WAJIB link data sendiri juga
        ↓
[Runner]    Run Overlap → lihat match rate
        ↓
[Runner]    Activate → pilih kolom, pilih tujuan, beri nama segmen
        ↓
[Penerima]  Activation Inbox → Import and flatten → tabel siap pakai
        ↓
[Semua]     History untuk audit · Admin untuk Leave/Teardown
```

Tiga hal yang paling sering membuat orang tersangkut, urut dari yang paling sering:

1. **Lupa link data sendiri** (`LINK_LOCAL_DATA_OFFERING`) — overlap mustahil jalan.
2. **Grant data sumber tanpa `WITH GRANT OPTION`** — `Grant not executed`.
3. **Memakai nama kolom asli, bukan nama hasil rename** — `Unauthorized columns`.
