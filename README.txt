=====================================================================
  AI OFFICE – Autonomous AI Workforce            (sürüm 1.2)
  "Ofisini kur. Yapay zekâ çalışanlarını seç. İşlerini yönet."
=====================================================================

API ANAHTARI GEREKMEZ. Yapay zekâ modeli bu klasörün içinde, bilgisayarınızda çalışır.
İnternet yalnızca İLK paketleme (model indirme) ve isteğe bağlı web araştırması için gerekir.

---------------------------------------------------------------------
HIZLI BAŞLANGIÇ (Windows 10/11)
---------------------------------------------------------------------
1) Bu klasörü istediğiniz yere (masaüstü veya USB bellek) kopyalayın.
2) INSTALL_AI_OFFICE.bat dosyasına çift tıklayın  (yönetici yetkisi GEREKMEZ).
   - Paket içi Python kurulur (runtime\python)
   - Yerel AI motoru llama.cpp indirilir (Vulkan GPU + CPU sürümü, engines\)
   - Bilgisayarınızın donanımı analiz edilir ve EN VERİMLİ model OTOMATİK seçilip indirilir (models\)
   Yarıda kalırsa tekrar çalıştırın; kaldığı yerden devam eder.
3) START_AI_OFFICE.bat (veya AI_OFFICE.exe) ile başlatın. Tarayıcıda arayüz açılır.
4) Kurulum sihirbazını izleyin: donanım → AI motoru → bağımlılıklar → ajan seçimi → sistem testi.

Paketleme bir kez yapıldıktan sonra klasör TAMAMEN ÇEVRİMDIŞI çalışır.
Tüm modelleri pakete eklemek için (farklı güçteki bilgisayarlar için):
   runtime\python\python.exe backend\cli.py prepare --all-models

---------------------------------------------------------------------
OTOMATİK MODEL SEÇİMİ
---------------------------------------------------------------------
  RAM < 7 GB                    → Qwen2.5 1.5B  (~1.0 GB)  Düşük donanım (çok zayıf)
  7–14 GB RAM (ör. 8 GB + AMD)  → Qwen2.5 3B    (~1.9 GB)  Düşük donanım
  14+ GB RAM veya 6+ GB VRAM    → Qwen2.5 7B    (~4.7 GB)  Dengeli performans
  30+ GB RAM ve 10+ GB VRAM     → Qwen2.5 14B   (~9.0 GB)  Yüksek performans
GPU (AMD/NVIDIA/Intel, ≥3 GB VRAM) varsa Vulkan ile hızlandırılır; yoksa CPU modu.
Ajan sayısı modeli büyütmez: 26 ajanın hepsi TEK modeli farklı rollerle, sırayla kullanır.
Bilgisayarda Ollama kuruluysa o da otomatik kullanılabilir.

Anlamsal arama modeli (bge-m3, 438 MB, MIT, çok dilli) da paketlemede otomatik iner.

---------------------------------------------------------------------
ÖZELLİKLER
---------------------------------------------------------------------
- 26 hazır ajan + kendi ajanını oluştur; CEO planlar, siz onaylarsınız, ekip çalışır
- Hareketli sanal ofis: ajanlar toplantı odasına yürür, birbirinin masasına gider, konuşma balonları
- Araçlar: dosya işlemleri, Word/Excel/PowerPoint/PDF üretimi, yerel OCR, görüntü analizi, veri analizi
  + grafik, yerel çeviri, web araması, sayfa okuma, PDF indirme, tarayıcı otomasyonu (Playwright),
  Python kodu çalıştırma (kapalı; açılırsa her seferinde onay), e-posta (taslak; SMTP + onayla gönderim)
- Hafıza: kullanıcı, ajan, ortak ofis, proje + bilgi bankası (anahtar kelime + anlamsal vektör arama)
- Görev kuyruğu, GPU/CPU/RAM/disk izleme, RAM'e sığmayan modeli otomatik küçültme
- Yedekleme (şifreli), USB veri kasası, bilgisayarlar arası senkronizasyon (çakışma ekranı),
  model taşıma/silme, "Bilgisayara kur" (kısayollu), Inno Setup kurulum paketi (GitHub Actions)

YENİ (1.2)
- Motor çökmesi (kod 3221225477 / 0xC0000005) onarıldı: güncel Visual C++ çalışma zamanı (14.44) pakette;
  motor klasörüne otomatik kopyalanır (yönetici yetkisi gerekmez). Çökerse güvenli mod ve daha küçük model denenir.
- Eksik inmiş model dosyaları tespit edilir: 'Dosya sorunlu → Yeniden indir'.
- 🩺 Motor tanılama: motor, VC++, model ve kayıt raporu; 'Raporu kopyala'.

YENİ (1.1)
- Ajan adlarını ve her uzmanlıktan kaç kişi çalışacağını siz belirlersiniz (Kurulum > Ekip, Ajanlarım, Ajan Marketi).
- Bilgi Bankası > İnternet kaynaklarım: ajanların önce bakacağı siteler; istenirse içerik (alt sayfalarla) indirilip
  internetsiz aranabilir hale getirilir.
- Motor indirme düzeltildi: llama.cpp'nin Windows paketi olan en yeni sürümü bulunur. İnemezse elle indirilen ZIP
  İndirilenler klasöründe "Klasörleri tara" ile otomatik kurulur.

---------------------------------------------------------------------
USB / TAŞINABİLİR MOD
---------------------------------------------------------------------
- PORTABLE_MODE.json varsa taşınabilir mod açıktır. Tüm yollar dinamiktir (E:, F:, G: fark etmez).
- Ajanlar, hafıza, projeler, ayarlar ve (seçerseniz) modeller USB'de taşınır.
- Başka bilgisayara takınca donanım yeniden analiz edilir; o PC'ye özel ayar oluşturulur.
- USB'yi çıkarmadan önce: arayüzde "Güvenli Kapat ve Çıkar" veya SAFE_EXIT_AI_OFFICE.bat
- USB kaybolma riskine karşı: USB ekranında "Şifrele ve kapat" (açılışta parola sorulur)
- İki kopyayı birleştirmek: USB ekranında "Senkronizasyon" → çakışmaları tarihleriyle görüp seçin
- Model konumu: USB'de / bu bilgisayarda (%LOCALAPPDATA%\AI_OFFICE\models) / karma
- USB için en az 8 GB (3B model) önerilir; 7B için 16 GB; hız için USB 3.0 veya harici SSD.

---------------------------------------------------------------------
BAT DOSYALARI
---------------------------------------------------------------------
  START_AI_OFFICE.bat       Başlat (pencereyi kapatmayın)
  INSTALL_AI_OFFICE.bat     Kurulum + paketleme (Python, motor, model)
  UPDATE_AI_OFFICE.bat      Otomatik yedek + paket güncelleme
  BACKUP_AI_OFFICE.bat      Yedek al (isteğe bağlı parola ile şifreli)
  RESTORE_AI_OFFICE.bat     Yedekten geri yükle (program kapalıyken)
  SAFE_EXIT_AI_OFFICE.bat   Güvenli kapat ve USB'yi çıkarmaya hazırla

---------------------------------------------------------------------
GÜVENLİK
---------------------------------------------------------------------
- Sunucu yalnızca 127.0.0.1'de çalışır; dış ağa açık değildir.
- Ajanlar yalnızca workspace\AI_OFFICE_WORKSPACE ve sizin izin verdiğiniz klasörlere erişir.
- Taşıma / yeniden adlandırma / silme işlemleri sizin ONAYINIZI ister. Silme kalıcı değildir (cache\trash).
- Keyfi komut (shell) çalıştırma kapalıdır. Web içerikleri güvenilmeyen veri olarak işaretlenir.
- İşlem geçmişinde hangi ajanın ne yaptığı tutulur; dosya içerikleri kayda yazılmaz.

---------------------------------------------------------------------
SORUN GİDERME
---------------------------------------------------------------------
- "Motor başlatılamadı": logs\engine.log dosyasına bakın. Vulkan başarısız olursa CPU sürümü
  otomatik denenir. Ayarlar > AI motoru > Model indir/kurulum ile daha küçük model seçin.
- Model ilk yüklemede USB'den 1–3 dakika sürebilir.
- DuckDuckGo araması geçici olarak engellenirse Wikipedia araması kullanılır (kayıt/anahtar gerekmez,
  resmi kota yoktur ama çok sık istekte geçici sınırlama olabilir).
