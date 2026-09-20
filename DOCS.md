# Yusufo9 Profil README — Özelleştirme Rehberi

Bu repo, GitHub profilinde görünen animasyonlu SVG kartları **tamamen GitHub üzerinde** (harici sunucu yok) üretir.
Bu doküman "şunu nasıl değiştiririm?" sorularının hepsini kapsar: yazı değiştirme/büyütme, font, renk,
yeni sosyal medya butonu, yeni tech-stack ikonu/kategorisi, yeni metin bölümü, DNA ağırlıkları, terminal mesajları…

---

## 1. Mimari — 2 dakikada

```
config.json                 ← SENİN DÜZENLEYECEĞİN YER: linkler, tech stack, ek bölümler
templates/
  profile.svg               ← Ana tasarım (GitAscii düzeni). Sabit yazılar, renkler, boyutlar burada.
  README.md                 ← README şablonu ({{STACK}}, {{BANDS}}, {{LINK_*}} yer tutucuları)
  band.svg                  ← "Ek metin bölümü" şablonu (ABOUT // DOSSIER stilinde)
  icons/*.svg               ← Tech-stack ikonları (256x256, koyu yuvarlak arka planlı)
  fonts/*.woff2             ← Gömülü font (JetBrains Mono, Regular + Bold)
scripts/update_stats.py     ← GitHub API'den veri çeker, şablonları doldurur, dist/ ve README.md'yi yazar
.github/workflows/update-readme.yml ← Saatte bir (:23) + her push'ta betiği çalıştırır, sonucu commit'ler
dist/                       ← ÜRETİLEN dosyalar. ELLE DÜZENLEME — her çalıştırmada ezilir.
README.md                   ← ÜRETİLEN dosya. ELLE DÜZENLEME — templates/README.md'yi düzenle.
```

**Akış:** `config.json` + `templates/*` → `update_stats.py` → `dist/*.svg` + `README.md` → GitHub profili.

**Altın kural:** `dist/` ve `README.md` dosyalarına asla elle dokunma; kaynağı (`templates/`, `config.json`, `scripts/`) düzenle,
sonra ya push'la (Action otomatik çalışır) ya da yerelde `python scripts/update_stats.py` çalıştırıp sonucu gör.

### Profil hangi görsellerden oluşuyor?

| README'deki sıra | Dosya | İçerik | Link |
|---|---|---|---|
| 1 | `dist/header-avatar.svg` | Avatar kartı | profil |
| 1 | `dist/header-repos.svg` | Kayan repo listesi | `?tab=repositories` |
| 2 | `dist/pill-*.svg` | Sosyal medya butonları | config `links` |
| 3 | `dist/band-*.svg` | (opsiyonel) ek metin bölümleri | config `bands[].url` |
| 4 | `dist/body-top.svg` | ABOUT // DOSSIER + MY DEV TECH STACK başlığı + ayırıcı | — |
| 5 | `dist/stack/*.svg` | Tech stack kartları, ikon başına bir karo | config `stack[].items[].url` |
| 6 | `dist/body-bottom.svg` | GITHUB METRICS, STREAK, DNA, Minecraft terminali | — |

Neden parçalı? GitHub, README'deki `<img>` içindeki SVG linklerini çalıştırmaz. Tıklanabilir olması gereken her şey
ayrı bir görsel olup README'de `<a>` ile sarılır. Görsel bütünlük, her parçanın aynı 800px'lik tuvalden
kesilmesiyle korunur (yüzde genişlikler mobilde de hizayı korur).

---

## 2. Yerelde çalıştırma ve önizleme

```bash
pip install -r requirements.txt
python scripts/update_stats.py        # gh CLI ile giriş yaptıysan token'ı otomatik alır
```
Token yoksa: `GITHUB_TOKEN=ghp_... python scripts/update_stats.py`

Önizleme: `dist/body-bottom.svg` gibi dosyaları tarayıcıda aç (Chrome/Firefox). Animasyonlar ve gömülü font aynen çalışır.

Push sonrası profil hemen değişmezse: GitHub görselleri (camo) birkaç dakika önbellekler → Ctrl+F5 veya gizli pencere.

---

## 3. Yazıları değiştirme

### 3.1 Tech-stack kategori adları ("DEVOPS // BACKEND" vb.)
`config.json` → `stack` → ilgili kartın `"label"` alanı. Örn. `"label": "INFRA // CLOUD"`. Başka bir şeye dokunma;
karo genişliği etikete göre değil kart genişliğine göre sabit, uzun etiketler için 464px kartta ~40 karakter yer var.

### 3.2 ABOUT // DOSSIER, HELLO WORLD!, [ GITHUB METRICS ], STARS/REPOS…, [ GITHUB STREAK STATS ], REPOSITORIES
Bunlar `templates/profile.svg` içinde **düz metin** olarak durur. Dosyada aratıp değiştir:

| Yazı | Nerede aranır |
|---|---|
| `ABOUT // DOSSIER` | `>ABOUT // DOSSIER</text>` |
| `HELLO WORLD!` | `>HELLO WORLD!</text>` |
| `[ GITHUB METRICS ]` | `>[ GITHUB METRICS ]</text>` |
| `STARS`, `REPOS`, `FOLLOWERS`… | `>STARS</text>` … (metrik etiketleri) |
| `[ GITHUB STREAK STATS ]` | aynen ara |
| `Total Contributions`, `Current Streak`, `Longest Streak` | aynen ara |
| `📦 REPOSITORIES` | aynen ara |
| `Yusufo9` / `@Yusufo9` (avatar kartı) | `>Yusufo9</text>` ve `>@Yusufo9</text>` |

`{{BÜYÜK_HARF}}` biçimindeki yer tutuculara (`{{STARS}}`, `{{MC_CHAT_LINES}}`…) **dokunma**; onları betik doldurur.

### 3.3 Minecraft terminali cümleleri
`scripts/update_stats.py` → `event_segments()` fonksiyonu. Her GitHub event tipi için `(metin, renk)` parçaları listesi var.
Örn. push satırı:
```python
seg = [("<", WHITE), (me, GREEN), (f"> pushed {n} commit{'s' if n != 1 else ''} to ", WHITE), (repo, GOLD)]
```
Metni değiştir, renk sabitlerini kullan (`WHITE, GRAY, DARK, GREEN, YELLOW, AQUA, GOLD, RED, PINK`).
Giriş satırı (`joined the game`) ve sistem satırı `render_minecraft()` içinde. Prompt satırı: `prompt = "&gt; /deploy ..."`.

### 3.4 DNA kartı etiketleri
`scripts/update_stats.py` → `TRAITS = ["Builder", "Maintainer", "Open Source", "Community", "Explorer"]`.
Etiketler en fazla 12 karakter (kutu 44 sütun). Adı değiştirirsen `EVENT_TRAITS` ve `LIFETIME_TRAITS` tablolarındaki
anahtarları da aynı isimle güncelle.

### 3.5 Sosyal buton yazıları ("Github", "Discord", "Gmail", "Telegram")
`templates/profile.svg` içinde `>Github</text>`, `>Discord</text>`, `>Gmail</text>`, `>Telegram</text>` satırlarını değiştir.
Yazı uzarsa aynı `<g id="pill-…">` bloğundaki iki `<rect … width="…">` değerini büyüt (yaklaşık 7.5px/karakter).

---

## 4. Yazı boyutu / kalınlık / renk değiştirme

Her yazı bir `<text …>` elemanı; `font-size`, `font-weight`, `fill` (renk), `letter-spacing` nitelikleri doğrudan değiştirilebilir.

| Ne | Nerede | Not |
|---|---|---|
| ABOUT // DOSSIER satırı | `profile.svg`, `x="30" y="24" font-size="12"` | 12 → 14 yap; şerit 40px yüksek, 16'yı geçme |
| Metrik sayıları | `profile.svg`, `font-size="34" font-weight="700"` (6 adet) | 40'a kadar rahat |
| Metrik etiketleri | `font-size="12" font-weight="500"` | |
| Streak kartı | `font-size='34px'` / `'13px'` / `'11px'` | İç SVG 495 birim geniş, 376px'e küçültülür; sütun 165 birim → mono'da ~19 karakter/13px |
| DNA kartı | `#widget_1789914565756 text { … font-size: 14px; }` | Kutu 44 sütun × 0.6em; 15px'te taşar → sütun sayısını `render_dna()` içinde düşür |
| Terminal | `.chat-line { font-size: 13px; }` ve `.prompt-text` | Büyütürsen `MAX_LINE`'ı orantılı düşür (776 / (px×0.6)) |
| Repo kartları | `update_stats.py` → `repo_card()` içindeki `font-size="15"`, `"12"` | Açıklama `clip(..., 50)` ile kesilir |
| Tech-stack etiketleri | `update_stats.py` → `write_stack_tiles()` → `font-size="13"` | |
| Kategori etiketi rengi | aynı yer, `LABEL = "#7a7a7a"` | |
| Ek bölüm (band) satırları | `write_bands()` → `font-size="13"`, `line_h = 22` | |

**Renk paleti (temayı bozmamak için):**
`#0d1117` sayfa · `#060606` kart · `#252525` kenarlık · `#7a7a7a` gri etiket · `#c5ff4a` lime (vurgu) ·
`#ffb454` amber · `#ffbd2e` altın · `#ff5555` kırmızı · `#55ff55` yeşil · `#e5e5e5` açık yazı · `#3e2815` koyu amber (DNA çerçeve).

---

## 5. Font değiştirme

Fontlar SVG'lere **gömülü** (`@font-face` + base64). Bu yüzden telefon dahil her yerde aynı görünür.
Değiştirmek için:

1. Yeni fontun `.ttf`'sini indir (lisansı gömmeye izin vermeli — OFL fontlar uygundur: JetBrains Mono, Fira Code, IBM Plex Mono…).
2. Küçült ve woff2'ye çevir (sadece gereken karakterler; DNA kutusu için kutu çizgileri `U+2500-259F` şart):
   ```bash
   pip install fonttools brotli
   python -m fontTools.subset Font-Regular.ttf --unicodes="U+0020-007E,U+00A0-00FF,U+2010-2027,U+2500-259F,U+2605,U+2442" --flavor=woff2 --output-file=templates/fonts/Font-Regular.woff2 --no-hinting
   ```
   (Bold için aynısını yap.)
3. `scripts/update_stats.py` → `font_css()` içindeki dosya adlarını ve `font-family:'JetBrains Mono'` adını değiştir.
4. `templates/profile.svg` içinde `'JetBrains Mono'` geçen yerleri yeni font adıyla değiştir (`MONO` yığını aynı satırda):
   toplu değiştirme için: `'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace` → `'Yeni Font', …`.
5. `update_stats.py` içindeki `MONO = "…"` sabitini de güncelle.

Orantılı (mono olmayan) bir font seçersen DNA kutusu ve terminal hizası bozulur — bunlar eşit genişlikli font ister.
Sadece başlıklarda farklı font istiyorsan yalnızca o `<text>`'lerin `font-family`'sini değiştir, fontu da `font_css()`'e ikinci `@font-face` olarak ekle.

---

## 6. Sosyal medya butonu ekleme / çıkarma

Butonlar `templates/profile.svg` içindeki pill widget'ında (`id="widget-widget_1789912840027"`) tanımlı; betik her `<g id="pill-AD-X-2">`
bloğunu ayrı bir `dist/pill-AD.svg` olarak keser.

**Yeni buton (örnek: LinkedIn):**

1. `profile.svg` içinde `<linearGradient id="grad-pill-telegram-611-2" …>` bloğunu kopyala, `telegram` → `linkedin`, `611` → yeni X,
   `#2AABEE` → marka rengi (`#0A66C2`).
2. `<g id="pill-telegram-611-2">` bloğunu kopyala; içindeki tüm `telegram`/`611` referanslarını güncelle. Koordinatlar:
   * `X` = önceki butonun `x + width + 18` (Telegram 611+116 → 745; 800'ü aşarsa satır README'de zaten ortalanıyor, sorun değil ama X ≤ 800 olsun; gerekirse eski butonların X'lerini kaydır).
   * dış `<rect x="X" width="W">`, iç iki `<rect x="X+1" width="W-2">`, ikon `translate(X+13, 15)`, yazı `x="X+40"`.
   * `W` ≈ 58 + karakter × 7.5.
   * İkon: 18×18 viewBox'lı tek `<path>` (Simple Icons'tan al: `https://cdn.jsdelivr.net/npm/simple-icons/icons/linkedin.svg`, viewBox 24 → `transform="scale(0.75)"` ekle).
   * Koyu arka plan rengi `fill="#…"`: markanın çok koyu tonu (Telegram `#0e2433`, Discord `#1a1d36`, Gmail `#331010`).
3. `config.json` → `links` → `"linkedin": "https://linkedin.com/in/…"`.
4. `templates/README.md` → pill satırına ekle:
   `<a href="{{LINK_LINKEDIN}}"><img src="./dist/pill-linkedin.svg" alt="LinkedIn" height="48"></a>`
5. Çalıştır; `dist/pill-linkedin.svg` üretilmiş olmalı.

**Çıkarma:** `templates/README.md`'den satırı sil (SVG'deki blok kalsa da zararı yok; istersen onu da sil).

**Sadece linki değiştirme:** `config.json` → `links`. Discord için `discord.com/users/<sayısal ID>` gerekir.

---

## 7. Tech stack: ikon ekleme, çıkarma, sıralama, yeni kategori

Her şey `config.json` → `stack`. Yapı: **satırlar** (`[...]`) → **kartlar** → `items`.

```json
{ "icon": "docker", "name": "Docker", "url": "https://hub.docker.com/" }
```
* `icon`: `templates/icons/<icon>.svg` dosya adı.
* `name`: hover'da görünen isim (alt/title).
* `url`: tıklanınca gidilecek adres.

**Sıralama:** listedeki sırayı değiştir. **Çıkarma:** satırı sil. Karolar ve README otomatik yeniden oluşur.

**Yeni ikon:** `templates/icons/<ad>.svg` oluştur. Format: 256×256, köşeleri 60px yuvarlak `#242938` arka plan (mevcut ikonlarla aynı "skill-icons" stili):
```xml
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" fill="none" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="#242938" rx="60"/>
  <g transform="translate(40, 40) scale(7.333)"><path fill="#RENK" d="…Simple Icons 24x24 path…"/></g>
</svg>
```
Hazır ikon kaynakları: Simple Icons (`cdn.jsdelivr.net/npm/simple-icons/icons/<ad>.svg`, 24×24 viewBox → yukarıdaki `scale(7.333)`),
skill-icons (`github.com/tandpfun/skill-icons/tree/main/icons`, zaten 256×256 — direkt kopyala).

**Kart geometrisi** (kart nesnesinde): `width` (px, satırdaki kartların toplamı 800 olmalı), `height`, `icon` (ikon boyutu),
`pitch` (ikon aralığı), `align: "center"` (ikonları ortala; yoksa soldan 24px).
Bir karta sığan ikon sayısı ≈ `(width - 40) / pitch`.

**Yeni kategori (kart):** Bir satıra ikinci kart eklemek için `width`'leri 800'e tamamla (örn. 400 + 400).
Yeni bir satır için `stack` dizisine yeni bir `[ { … } ]` ekle; tam genişlik için `"width": 800`.
Kart yüksekliği: etiket 44 + ikon alanı; `height` = 44 + icon + ~30.

---

## 8. Yeni metin bölümü ekleme ("band")

Sosyal butonların altına ABOUT // DOSSIER görünümünde bir kutu eklemek için `config.json`'a `bands` ekle:

```json
"bands": [
  {
    "id": "about",
    "title": "ABOUT // ME",
    "right": "İSTANBUL · TR",
    "accent": "#c5ff4a",
    "color": "#e5e5e5",
    "lines": [
      "Backend & DevOps ile ilgileniyorum, Linux üzerinde yaşıyorum.",
      "Şu an: Go öğreniyorum · Homelab kuruyorum",
      "Bana en hızlı Telegram'dan ulaşabilirsin."
    ],
    "url": "https://t.me/yyarom"
  }
]
```
* `id`: dosya adı (`dist/band-about.svg`) — küçük harf, boşluksuz.
* `title` / `right`: sol ve sağ başlık (dossier şeridindeki gibi).
* `accent`: çerçeve ve başlık rengi (lime `#c5ff4a`, amber `#ffb454`, kırmızı `#ff5555`…).
* `lines`: satırlar; ~90 karakteri geçme (800px / 13px mono).
* `url`: opsiyonel, tüm kutu tıklanabilir olur.

Birden fazla band eklenebilir; README'de `{{BANDS}}` yer tutucusunun olduğu yere sırayla gelir.
Yerini değiştirmek için `templates/README.md` içinde `{{BANDS}}` satırını istediğin sıraya taşı
(örn. tech stack'in altına, `body-bottom`'un üstüne).

Kutu tasarımını değiştirmek için `templates/band.svg`'yi düzenle (`{{TITLE}}`, `{{RIGHT}}`, `{{BODY}}`, `{{ACCENT}}`, `{{HEIGHT}}`, `{{INNER_H}}`, `{{FONT_CSS}}` yer tutucuları kalmalı).

---

## 9. Bölümleri yeniden sıralama / gizleme

README'nin iskeleti `templates/README.md`. Satırları taşıyarak sırayı değiştir, silerek gizle.
`{{STACK}}` (tech stack karoları) ve `{{BANDS}}` yer tutucuları tek satır olarak taşınabilir.
`body-top.svg` ve `body-bottom.svg` içindeki widget'ların sırası `templates/profile.svg`'deki `translate(x, y)` konumlarıyla belirlenir;
bir widget'ı gizlemek için ilgili `<g … id="widget-…">…</g>` bloğunu sil (bant yükseklikleri `update_stats.py` → `BODY_TOP`, `BODY_BOTTOM`).

---

## 10. Veriler ve hesaplamalar

| Veri | Kaynak | Değiştirilecek yer |
|---|---|---|
| Stars / Forks | GraphQL, tüm public repoların toplamı | `fetch_user()` |
| Repos / Followers / Following / Gists | REST `/users/<ad>` (profil sayfasıyla birebir) | `fetch_user()` |
| Contributions, streak | GraphQL contribution takvimi, hesap açılışından beri | `fetch_contributions()`, `compute_streaks()` |
| Repo listesi | Pinned repolar önce, sonra son push edilenler, en fazla 8 | `fetch_user()` → `repo_list` (`[:8]`), `render_repos()` |
| Terminal | REST `/users/<ad>/events/public` son 4 event | `render_minecraft()` (`events[:4]`) |
| DNA | Event tipi → karakteristik puanı (`EVENT_TRAITS`) + ömür boyu taban (`LIFETIME_TRAITS`) | ağırlıkları tablodan değiştir |

DNA'da örneğin star vermeyi daha "Explorer" saydırmak: `"WatchEvent": {"Explorer": 3}` → `5`.
Yeni karakteristik eklemek: `TRAITS`'e ekle, tablolara puan yaz (kart 5 satır için tasarlandı; 6. satır için `render_dna()`'daki `y` aralıklarını ve DNA widget yüksekliğini büyüt).

---

## 11. Zamanlama ve otomasyon

* Cron: `.github/workflows/update-readme.yml` → `cron: "23 * * * *"` (saatte bir, :23'te). `:00` dakikası GitHub'da yoğun olduğu için atlanabilir/gecikebilir; başka bir dakika seç ama `:00`'dan kaçın.
* Sıklık: `"*/30 * * * *"` yarım saat (GitHub minimum 5 dk; gereksiz commit üretir, 1 saat yeterli).
* Manuel: Actions sekmesi → "Update README SVGs" → Run workflow.
* Bot commit'leri `[skip ci]` taşır, kendi push'ların Action'ı tetikler (`dist/**` değişiklikleri hariç).

---

## 12. Kısıtlar (neden bazı şeyler böyle)

* README'de JS/CSS yok → tüm animasyon SVG içi CSS/SMIL; hover efektleri **çalışmaz** (img içinde).
* SVG dış kaynak yükleyemez → avatar, ikonlar, fontlar base64 gömülü.
* `<img>` içindeki linkler ölü → tıklanabilir her parça ayrı dosya + README'de `<a>`.
* Karo genişlikleri **yüzde** (`width="6.75%"`) ve `align="top"` — bu iki şey mobil hizayı sağlıyor; README şablonundaki `align="top"`'ları silme.
* Emoji ve özel semboller (`★ ⑂ 📦`) sistem fontundan gelir; her cihazda birebir aynı olmayabilir.

## 13. Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| Profil güncellenmiyor | Camo önbelleği → Ctrl+F5. Actions'ta run yeşil mi? Cron gecikmesi 10-30 dk olabilir. |
| Action `Resource not accessible by integration` | GraphQL'de GITHUB_TOKEN'ın göremediği alan istendi (örn. gists) — REST kullan. |
| Action push edemiyor | Settings → Actions → General → Workflow permissions → Read and write (workflow'da `permissions: contents: write` zaten var). |
| Yazı taşıyor / kesiliyor | Bölüm 4'teki sınırlara bak; mono fontta karakter genişliği = 0.6 × font-size. |
| Yeni ikon boş görünüyor | Dosya adı `config.json`'daki `icon` ile aynı mı? Kök `<svg>`'de `fill="none"` var mı? Path'ler `fill` belirtiyor mu? |
| XML hatası | `python -c "import xml.dom.minidom,sys;xml.dom.minidom.parse('templates/profile.svg')"` ile hatanın satırını bul. `&` → `&amp;`, `<` → `&lt;`. |
