// Kurulum sihirbazı (6 aşama). Yeni bilgisayarda (USB başka PC'ye takıldığında) kısa akış çalışır.
const Wizard = {
  step: 0, steps: [], data: { mode: "portable", location: "usb", team: [] },
  async start(newMachine) {
    this.steps = newMachine ? ["machine", "hardware", "engine", "test"] : ["welcome", "hardware", "engine", "deps", "team", "test"];
    this.newMachine = newMachine;
    document.getElementById("wizard").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
    this.step = 0;
    this.render();
  },
  frame(inner, { next = "İLERLE", nextDisabled = false, back = true } = {}) {
    const bars = this.steps.map((_, i) => `<i class="${i <= this.step ? "on" : ""}"></i>`).join("");
    document.getElementById("wizard").innerHTML = `<div class="wiz"><div class="wiz-steps">${bars}</div>${inner}
      <div class="foot"><button class="btn sec" ${back && this.step > 0 ? "" : "style='visibility:hidden'"} onclick="Wizard.prev()">← Geri</button>
      <button class="btn big" id="wizNext" ${nextDisabled ? "disabled" : ""} onclick="Wizard.next()">${next} →</button></div></div>`;
  },
  prev() { this.step = Math.max(0, this.step - 1); this.render(); },
  async next() {
    const name = this.steps[this.step];
    if (name === "team") {
      await this.saveTeam();
    }
    if (this.step >= this.steps.length - 1) return this.finish();
    this.step++;
    this.render();
  },
  async finish() {
    const r = await API.post("/api/setup/complete", { mode: this.data.mode, hired_agents: [] });
    document.getElementById("wizard").classList.add("hidden");
    toast(r.message);
    App.boot();
  },
  render() { return this["r_" + this.steps[this.step]](); },

  r_welcome() {
    const ch = (v, t, d) => `<div class="choice ${this.data.mode === v ? "on" : ""}" onclick="Wizard.data.mode='${v}';Wizard.render()"><h3>${t}</h3><small>${d}</small></div>`;
    this.frame(`<div class="row" style="gap:18px"><div class="logo big-logo">AI</div><div><h1>AI OFFICE – Autonomous AI Workforce</h1>
      <p class="muted">"Ofisini kur. Yapay zekâ çalışanlarını seç. İşlerini yönet."</p></div></div>
      <p>AI OFFICE, bilgisayarınızda yerel yapay zekâ modelleriyle çalışan bir dijital şirkettir. Ücretli API anahtarı gerekmez;
      modeller bu klasörün içinde çalışır ve internet olmadan da kullanılabilir.</p>
      <h3>Nasıl kullanacaksınız?</h3>
      <div class="grid g2">${ch("installed", "💻 Bilgisayara kur", "Program ve veriler bu bilgisayarda kalır.")}
      ${ch("portable", "🔌 USB / Taşınabilir modda kullan", "Ajanlar, hafıza, projeler ve ayarlar USB'de taşınır. Sürücü harfi değişse de çalışır.")}</div>`,
      { next: "Başla" });
  },
  r_machine() {
    this.frame(`<h1>🔌 Yeni bilgisayar algılandı</h1><p>AI OFFICE bu bilgisayarda ilk kez çalışıyor. USB'deki ajanlarınız, hafızanız ve projeleriniz korunuyor.</p>
      <p>Donanım yeniden analiz edilecek, GPU uyumluluğu kontrol edilecek ve bu bilgisayara uygun model ayarı oluşturulacak.
      (Bir bilgisayarda kurulan GPU sürücüsünün diğerinde olduğu varsayılmaz.)</p>`, { next: "Analize başla", back: false });
  },
  async r_hardware() {
    this.frame(`<h1>🖥️ Bilgisayar analizi</h1><p class="muted">Donanımınız inceleniyor…</p>`, { nextDisabled: true });
    try {
      const r = await API.get("/api/hardware?refresh=true");
      const h = r.hardware, rec = r.recommendation;
      const gpus = h.gpus.length ? h.gpus.map((g) => `${esc(g.name)} <span class="badge">${g.vendor}</span> ${g.vram_gb ? g.vram_gb + " GB VRAM" : "VRAM bilinmiyor/paylaşımlı"}`).join("<br>") : "Bulunamadı";
      this.frame(`<h1>🖥️ Bilgisayar analizi</h1><div class="grid g2"><div class="kv">
        <b>Windows</b><span>${esc(h.os)}</span><b>İşlemci</b><span>${esc(h.cpu)} (${h.cores_physical} çekirdek)</span>
        <b>RAM</b><span>${h.ram_total_gb} GB (boş ${h.ram_available_gb} GB)</span><b>Ekran kartı</b><span>${gpus}</span>
        <b>Vulkan</b><span>${h.vulkan_runtime ? "✔ var" : "✖ yok"}</span><b>Disk (${esc(h.drive)})</b><span>${h.disk_free_gb} GB boş</span>
        <b>Python</b><span>${h.python} ${h.python_embedded ? "(paket içi)" : ""}</span><b>İnternet</b><span>${h.internet ? "✔ bağlı" : "✖ yok (yerel çalışma devam eder)"}</span></div>
        <div class="card" style="background:#f0fdfa"><h3>Önerilen çalışma modu</h3><div class="stat">${esc(rec.tier_label)}</div>
        <p>Model: <b>${esc(rec.model_id)}</b> · ${rec.gpu_mode ? "GPU hızlandırma (Vulkan)" : "CPU modu"} · ${rec.threads} iş parçacığı · bağlam ${rec.ctx}</p>
        <ul>${rec.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div>`);
    } catch (e) { this.frame(`<h1>Analiz hatası</h1><p>${esc(e.message)}</p>`); }
  },
  async r_engine() {
    const r = await API.get("/api/models");
    const st = (await API.get("/api/engine/status")).engine;
    const loc = this.data.location;
    const rows = r.models.map((m) => `<tr><td><b>${esc(m.name)}</b> ${m.recommended ? '<span class="badge turq">ÖNERİLEN</span>' : ""}<br><small>${esc(m.note)}<br>Lisans: ${esc(m.license)} · Türkçe: ${esc(m.turkish)}</small></td>
      <td>${m.size_gb} GB</td><td>${m.ram_gb} GB ${m.fits_ram ? "" : '<span class="badge err">RAM yetersiz</span>'}</td>
      <td>${m.fits_disk ? "✔" : '<span class="badge err">disk yetersiz</span>'}</td>
      <td>${m.installed && m.broken ? `<span class="badge err" title="${esc(m.problems.join("; "))}">Dosya sorunlu</span> <button class="btn sm" onclick="Wizard.redl('${m.id}')">Yeniden indir</button>`
        : m.installed ? '<span class="badge ok">Pakette var</span>' : `<button class="btn sm" onclick="Wizard.dl('${m.id}')">İndir</button>`}<div id="job-${m.id}"></div>
        ${m.installed && m.broken ? `<small class="muted">${esc(m.problems.join("; "))}</small>` : ""}</td></tr>`).join("");
    const eng = r.engine_files;
    const lc = (v, t) => `<label class="row"><input type="radio" name="loc" style="width:auto" ${loc === v ? "checked" : ""} onchange="Wizard.data.location='${v}'"> ${t}</label>`;
    const hasModel = r.models.some((m) => m.installed);
    this.frame(`<h1>🧠 Yerel AI motoru</h1>
      <p>Motor: <b>llama.cpp</b> (paket içinde, kurulum ve yönetici yetkisi gerektirmez). Bilgisayarda <b>Ollama</b> kuruluysa o da otomatik kullanılabilir.</p>
      <div class="row">${eng.vulkan ? '<span class="badge ok">Vulkan GPU motoru pakette</span>' : '<span class="badge warn">Vulkan motoru yok</span>'}
        ${eng.cpu ? '<span class="badge ok">CPU motoru pakette</span>' : '<span class="badge warn">CPU motoru yok</span>'}
        ${!eng.vulkan || !eng.cpu ? '<button class="btn sm" onclick="Wizard.dlEngine()">Motoru indir (~60 MB)</button> <button class="btn sec sm" onclick="Wizard.scanEngine()">Klasörleri tara</button>' : ""}<span id="job-engine"></span></div>
      ${!eng.vulkan && !eng.cpu ? `<details class="msg" style="margin-top:8px"><summary><b>Motor inmiyorsa: elle kurulum (2 dakika)</b></summary>
        <ol><li><a href="${esc(r.releases_page)}" target="_blank">${esc(r.releases_page)}</a> sayfasını açın.</li>
        <li>En üstteki sürümde <b>Assets</b> bölümünü açın (gerekirse "Show all assets").</li>
        <li><code>llama-bXXXX-bin-win-vulkan-x64.zip</code> (ekran kartı için) ve <code>llama-bXXXX-bin-win-cpu-x64.zip</code> dosyalarını indirin. Sürümde yoksa bir alttaki sürüme bakın.</li>
        <li>Dosyaları <b>İndirilenler</b> klasöründe bırakın (açmanıza gerek yok) ve <b>Klasörleri tara</b>'ya basın.</li></ol></details>` : ""}
      <h3 style="margin-top:14px">Model konumu</h3><div class="row" style="gap:18px">${lc("usb", "USB üzerinde (tam taşınabilir)")}${lc("local", "Bu bilgisayarda (hızlı, az USB alanı)")}${lc("hybrid", "Karma (küçük model USB'de, büyük bilgisayarda)")}</div>
      <table style="margin-top:10px"><tr><th>Model</th><th>Dosya</th><th>RAM ihtiyacı</th><th>Disk</th><th></th></tr>${rows}</table>
      <div class="row" style="margin-top:10px"><button class="btn navy" onclick="Wizard.testEngine()">Motoru başlat ve test et</button><button class="btn sec" onclick="Diag.open()">🩺 Motor tanılama</button><span id="engTest">${st.status === "hazir" ? '<span class="badge ok">Motor hazır: ' + esc(st.model_name) + "</span>" : ""}</span></div>
      ${hasModel ? "" : '<p class="todo">Paket içinde model yok. Önerilen modeli indirin ya da INSTALL_AI_OFFICE.bat ile paketi bir kez hazırlayın; sonrasında internet gerekmez.</p>'}`);
  },
  jobMap: {},
  async dl(id) { const r = await API.post("/api/models/download", { model_id: id, location: this.data.location }); this.jobMap[r.job.id] = "job-" + id; this.watchJobs(); },
  async dlEngine() { const r = await API.post("/api/engine/download"); this.jobMap[r.job.id] = "job-engine"; this.watchJobs(); },
  watchJobs() {
    if (this._w) return;
    this._w = true;
    WS.on("job", (m) => {
      const j = m.job;
      const target = document.getElementById(this.jobMap[j.id] || "");
      if (!target) return;
      const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
      target.innerHTML = j.status === "hata" ? `<span class="badge err">${esc(j.error)}</span>` :
        j.status === "tamamlandı" ? '<span class="badge ok">Tamamlandı</span>' :
        `<div class="bar" style="width:140px"><i style="width:${pct}%"></i></div><small>${fmtBytes(j.done)} / ${fmtBytes(j.total)} (%${pct})</small>`;
      if (j.status === "tamamlandı" && this.steps[this.step] === "engine") setTimeout(() => this.render(), 800);
    });
  },
  async redl(id) {
    if (!confirm("Sorunlu model dosyası silinip yeniden indirilecek. Devam?")) return;
    const r = await API.post("/api/models/redownload", { model_id: id, location: this.data.location });
    this.jobMap[r.job.id] = "job-" + id; this.watchJobs();
  },
  async scanEngine() {
    const r = await API.post("/api/engine/scan");
    toast(r.found.length ? "Motor bulundu ve kuruldu: " + r.found.join(", ") : "İndirilenler/engines klasöründe llama.cpp ZIP'i bulunamadı.", 6000);
    this.render();
  },
  async testEngine() {
    const el = document.getElementById("engTest");
    el.innerHTML = '<span class="badge turq">Model yükleniyor (USB\'den 1-3 dk sürebilir)…</span>';
    const r = await API.post("/api/engine/test");
    el.innerHTML = r.ok ? `<span class="badge ok">✔ ${esc(r.engine.model_name)} · ${r.seconds} sn</span> <i>"${esc(r.answer)}"</i>`
      : `<div class="msg hata" style="margin-top:8px">${esc(r.error).split(" | ").join("<br>")}</div><button class="btn sm" style="margin-top:6px" onclick="Diag.open()">🩺 Motor tanılama raporunu aç</button>`;
  },
  async r_deps() {
    const r = await API.get("/api/setup/deps");
    const missing = r.packages.filter((p) => !p.installed);
    this.frame(`<h1>📦 Bağımlılıklar</h1><p>Python ${esc(r.python)} · <small>${esc(r.executable)}</small></p>
      <div class="row">${r.packages.map((p) => `<span class="badge ${p.installed ? "ok" : "err"}">${p.installed ? "✔" : "✖"} ${p.name}</span>`).join("")}</div>
      ${missing.length ? `<p class="todo">Eksik paketler var.</p><button class="btn" onclick="Wizard.installDeps()">Eksikleri kur</button><pre id="depLog" class="hidden"></pre>` : '<p><span class="badge ok">Bütün bileşenler hazır.</span></p>'}`);
  },
  async installDeps() {
    const log = document.getElementById("depLog");
    log.classList.remove("hidden"); log.textContent = "Kuruluyor… (yarıda kalırsa tekrar basın, kaldığı yerden devam eder)";
    const r = await API.post("/api/setup/install-deps");
    log.textContent = r.log;
    if (r.returncode === 0) setTimeout(() => this.render(), 1000);
  },
  async r_team() {
    const r = await API.get("/api/agents");
    const builtins = r.agents.filter((a) => a.builtin);
    if (!this.data.counts) {
      this.data.counts = {};
      this.data.names = {};
      builtins.forEach((a) => {
        this.data.counts[a.id] = r.recommended.includes(a.id) ? 1 : 0;
        this.data.names[a.id] = [a.name];
      });
      this.data.counts.ceo = 1;
    }
    const byCat = {};
    builtins.forEach((a) => (byCat[a.category] ||= []).push(a));
    const total = Object.values(this.data.counts).reduce((x, y) => x + y, 0);
    const html = Object.entries(byCat).map(([cat, list]) => `<h3>${esc(cat)}</h3><div class="grid g3">${list.map((a) => {
      const n = this.data.counts[a.id] || 0;
      const names = this.data.names[a.id] || [];
      const inputs = Array.from({ length: n }, (_, i) => `<input class="nm-in" value="${esc(names[i] || "")}" placeholder="${i + 1}. kişinin adı"
        oninput="Wizard.setName('${a.id}',${i},this.value)" style="margin-top:4px;padding:5px 8px">`).join("");
      return `<div class="agent-card ${n ? "on" : ""}"><div class="av">${a.avatar}</div><div style="flex:1"><b>${esc(a.title)}</b><br><small>${esc(a.expertise)}</small>
        <div class="row" style="margin-top:6px"><button class="btn sec sm" onclick="Wizard.count('${a.id}',-1)" ${a.id === "ceo" ? "disabled" : ""}>−</button>
        <b style="min-width:24px;text-align:center">${n}</b><button class="btn sec sm" onclick="Wizard.count('${a.id}',1)" ${a.id === "ceo" ? "disabled" : ""}>+</button><small>kişi</small></div>${inputs}</div></div>`;
    }).join("")}</div>`).join("");
    this.frame(`<h1>🏢 Dijital ofisinizi oluşturun</h1>
      <p>Her uzmanlıktan kaç kişi çalışacağını ve adlarını siz belirleyin (toplam <b>${total}</b> çalışan). CEO tektir.
      Kişi sayısı modeli büyütmez: hepsi aynı yerel modeli sırayla kullanır; aynı uzmanlıktan birden fazla kişi varsa CEO işi aralarında bölüştürür.</p>
      <div class="row"><button class="btn sec sm" onclick="Wizard.preset('rec')">Önerilen ekip</button><button class="btn sec sm" onclick="Wizard.preset('all')">Her uzmanlıktan 1 kişi</button>
      <button class="btn sec sm" onclick="Wizard.preset('none')">Sadece CEO</button></div>${html}`);
  },
  count(id, d) {
    const n = Math.max(0, Math.min(10, (this.data.counts[id] || 0) + d));
    this.data.counts[id] = n;
    const names = (this.data.names[id] ||= []);
    while (names.length < n) names.push("");
    this.render();
  },
  setName(id, i, v) { (this.data.names[id] ||= [])[i] = v; },
  async preset(kind) {
    const r = await API.get("/api/agents");
    r.agents.filter((a) => a.builtin).forEach((a) => {
      this.data.counts[a.id] = a.id === "ceo" ? 1 : kind === "all" ? 1 : kind === "rec" && r.recommended.includes(a.id) ? 1 : 0;
    });
    this.render();
  },
  async saveTeam() {
    const ids = Object.keys(this.data.counts).filter((k) => this.data.counts[k] > 0);
    await API.post("/api/agents/team", { ids });
    for (const [id, n] of Object.entries(this.data.counts)) {
      const names = (this.data.names[id] || []).slice(0, n).map((x) => (x || "").trim());
      await API.post(`/api/agents/${id}/count`, { count: n, names: names.some((x) => x) ? names : [] });
    }
  },
  async r_test() {
    this.frame(`<h1>🧪 Sistem testi</h1><p class="muted">Servisler ve modüller test ediliyor… (model yükleme birkaç dakika sürebilir)</p>`, { nextDisabled: true });
    const r = await API.post("/api/setup/system-test");
    const rows = r.results.map((x) => `<tr><td>${x.ok ? "✅" : "❌"}</td><td>${esc(x.name)}</td><td><small>${esc(x.detail)}</small></td></tr>`).join("");
    this.frame(`<h1>🧪 Sistem testi</h1><table>${rows}</table>
      ${r.all_ok ? '<h2 style="margin-top:18px;color:var(--turq2)">AI OFFICE hazır. Dijital çalışanlarınız görev bekliyor.</h2>' :
      '<p class="todo">Bazı testler başarısız. AI motoru hazır değilse ofisi yine açabilirsiniz; komutlar motor hazır olunca çalışır. "Geri" ile AI motoru adımına dönebilirsiniz.</p>'}`,
      { next: "Ofise gir" });
  },
};

// Motor tanılama penceresi (kurulum sihirbazı ve Ayarlar'dan açılır)
const Diag = {
  async open() {
    const dr = document.getElementById("drawer");
    dr.classList.remove("hidden");
    dr.innerHTML = `<div class="row between"><h2>🩺 Motor tanılama</h2><button class="btn sec sm" onclick="document.getElementById('drawer').classList.add('hidden')">✕</button></div><p class="muted">Kontrol ediliyor… (30 sn sürebilir)</p>`;
    const r = (await API.get("/api/engine/diagnose")).report;
    this.last = r;
    const v = (name, x) => !x.found ? `<tr><td>${name}</td><td colspan=2><span class="badge warn">yok</span></td></tr>` :
      `<tr><td>${name}</td><td>${x.version.ok ? '<span class="badge ok">çalışıyor</span>' : '<span class="badge err">' + esc(x.version.explain || "çalışmıyor") + "</span>"}<br><small>${esc(x.version.output.split("\n").slice(-2).join(" "))}</small></td>
       <td>${x.vcrt_ok ? '<span class="badge ok">VC++ ✔</span>' : '<span class="badge err">VC++ eksik</span>'}${x.vcrt_copied.length ? "<br><small>" + x.vcrt_copied.length + " DLL eklendi</small>" : ""}</td></tr>`;
    dr.innerHTML = `<div class="row between"><h2>🩺 Motor tanılama</h2><button class="btn sec sm" onclick="document.getElementById('drawer').classList.add('hidden')">✕</button></div>
      <h3>Öneriler</h3>${r.advice.map((a) => `<div class="msg">${esc(a)}</div>`).join("")}
      <h3 style="margin-top:12px">Motor dosyaları</h3><table>${v("Vulkan (ekran kartı)", r.variants.vulkan)}${v("CPU (işlemci)", r.variants.cpu)}</table>
      <div class="kv" style="margin-top:8px"><b>Windows msvcp140.dll</b><span>${esc(r.windows_msvcp140 || "—")}</span><b>Paketteki VC++</b><span>${r.bundled_vcrt ? "14.44 ✔" : "yok"}</span>
      <b>RAM</b><span>${r.ram_total_gb} GB (boş ${r.ram_free_gb} GB)</span></div>
      <h3 style="margin-top:12px">Model dosyaları</h3>${r.models.map((m) => `<div class="row between"><span>${esc(m.id)} · ${m.size_gb} GB</span>${m.ok ? '<span class="badge ok">sağlam</span>' : '<span class="badge err">' + esc(m.problems.join("; ")) + "</span>"}</div>`).join("") || "<small>Model yok</small>"}
      <h3 style="margin-top:12px">Motor kaydı (logs/engine.log, son kısım)</h3><pre>${esc(r.log_tail || "(boş)")}</pre>
      <div class="row"><button class="btn" onclick="Diag.copy()">📋 Raporu kopyala</button><button class="btn sec" onclick="Wizard.testEngine && document.getElementById('engTest') ? Wizard.testEngine() : API.post('/api/engine/start').then(x=>toast(x.started?'Motor hazır':'Başlatılamadı',5000))">Tekrar dene</button></div>`;
  },
  copy() {
    const t = JSON.stringify(this.last, null, 2);
    navigator.clipboard?.writeText(t).then(() => toast("Rapor kopyalandı; bana yapıştırabilirsiniz."), () => { prompt("Raporu kopyalayın:", t); });
  },
};
