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
      await API.post("/api/agents/team", { ids: this.data.team });
    }
    if (this.step >= this.steps.length - 1) return this.finish();
    this.step++;
    this.render();
  },
  async finish() {
    const r = await API.post("/api/setup/complete", { mode: this.data.mode, hired_agents: this.newMachine ? [] : this.data.team });
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
      <td>${m.installed ? '<span class="badge ok">Pakette var</span>' : `<button class="btn sm" onclick="Wizard.dl('${m.id}')">İndir</button>`}<div id="job-${m.id}"></div></td></tr>`).join("");
    const eng = r.engine_files;
    const lc = (v, t) => `<label class="row"><input type="radio" name="loc" style="width:auto" ${loc === v ? "checked" : ""} onchange="Wizard.data.location='${v}'"> ${t}</label>`;
    const hasModel = r.models.some((m) => m.installed);
    this.frame(`<h1>🧠 Yerel AI motoru</h1>
      <p>Motor: <b>llama.cpp</b> (paket içinde, kurulum ve yönetici yetkisi gerektirmez). Bilgisayarda <b>Ollama</b> kuruluysa o da otomatik kullanılabilir.</p>
      <div class="row">${eng.vulkan ? '<span class="badge ok">Vulkan GPU motoru pakette</span>' : '<span class="badge warn">Vulkan motoru yok</span>'}
        ${eng.cpu ? '<span class="badge ok">CPU motoru pakette</span>' : '<span class="badge warn">CPU motoru yok</span>'}
        ${!eng.vulkan || !eng.cpu ? '<button class="btn sm" onclick="Wizard.dlEngine()">Motoru indir (~60 MB)</button>' : ""}<span id="job-engine"></span></div>
      <h3 style="margin-top:14px">Model konumu</h3><div class="row" style="gap:18px">${lc("usb", "USB üzerinde (tam taşınabilir)")}${lc("local", "Bu bilgisayarda (hızlı, az USB alanı)")}${lc("hybrid", "Karma (küçük model USB'de, büyük bilgisayarda)")}</div>
      <table style="margin-top:10px"><tr><th>Model</th><th>Dosya</th><th>RAM ihtiyacı</th><th>Disk</th><th></th></tr>${rows}</table>
      <div class="row" style="margin-top:10px"><button class="btn navy" onclick="Wizard.testEngine()">Motoru başlat ve test et</button><span id="engTest">${st.status === "hazir" ? '<span class="badge ok">Motor hazır: ' + esc(st.model_name) + "</span>" : ""}</span></div>
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
  async testEngine() {
    const el = document.getElementById("engTest");
    el.innerHTML = '<span class="badge turq">Model yükleniyor (USB\'den 1-3 dk sürebilir)…</span>';
    const r = await API.post("/api/engine/test");
    el.innerHTML = r.ok ? `<span class="badge ok">✔ ${esc(r.engine.model_name)} · ${r.seconds} sn</span> <i>"${esc(r.answer)}"</i>` : `<span class="badge err">${esc(r.error)}</span>`;
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
    if (!this.data.team.length) this.data.team = r.recommended.slice();
    const byCat = {};
    r.agents.filter((a) => a.builtin).forEach((a) => (byCat[a.category] ||= []).push(a));
    const html = Object.entries(byCat).map(([cat, list]) => `<h3>${esc(cat)}</h3><div class="grid g3">${list.map((a) => {
      const on = this.data.team.includes(a.id);
      return `<div class="agent-card ${on ? "on" : ""}" onclick="Wizard.toggle('${a.id}')"><div class="av">${a.avatar}</div><div><b>${esc(a.title)}</b><br><small>${esc(a.name)} · ${esc(a.expertise)}</small></div></div>`;
    }).join("")}</div>`).join("");
    this.frame(`<h1>🏢 Dijital ofisinizi oluşturun</h1><p>Çalışanlarınızı seçin (${this.data.team.length} seçili). CEO her zaman ofistedir. Ajan sayısı modeli büyütmez: hepsi aynı yerel modeli sırayla kullanır.</p>
      <div class="row"><button class="btn sec sm" onclick="Wizard.data.team=${JSON.stringify(r.recommended).replace(/"/g, "'")};Wizard.render()">Önerilen ekip</button>
      <button class="btn sec sm" onclick="Wizard.data.team=${JSON.stringify(r.agents.filter((a) => a.builtin).map((a) => a.id)).replace(/"/g, "'")};Wizard.render()">Hepsini seç</button></div>${html}`);
  },
  toggle(id) {
    if (id === "ceo") return toast("CEO her zaman ofiste.");
    const t = this.data.team;
    const i = t.indexOf(id);
    i >= 0 ? t.splice(i, 1) : t.push(id);
    this.render();
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
