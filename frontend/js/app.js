// Uygulama çekirdeği: yönlendirme, WebSocket olayları, onay pencereleri, ajan detay çekmecesi
const NAV = [
  ["home", "🏠", "Ana Sayfa"], ["office", "🏢", "Sanal Ofis"], ["agents", "👥", "Ajanlarım"], ["market", "🛒", "Ajan Marketi"],
  ["tasks", "📋", "Görev Merkezi"], ["meetings", "🤝", "Toplantılar"], ["memory", "🧠", "Hafıza Merkezi"], ["kb", "📚", "Bilgi Bankası"],
  ["files", "📁", "Dosyalarım"], ["tools", "🧰", "Araçlar"], ["usb", "🔌", "USB / Taşınabilir Mod"], ["backup", "💾", "Yedekleme"],
  ["audit", "📜", "İşlem Geçmişi"], ["settings", "⚙️", "Ayarlar"],
];

const App = {
  view: "home", agents: [], states: {}, status: null, liveMessages: [],
  async init() {
    WS.connect();
    this.bindWS();
    const st = await API.get("/api/status");
    this.status = st;
    if (st.locked) return this.unlockScreen();
    if (!st.setup_complete) return Wizard.start(false);
    if (!st.machine_known) return Wizard.start(true);
    this.boot();
  },
  async boot() {
    document.getElementById("wizard").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    this.status = await API.get("/api/status");
    document.getElementById("nav").innerHTML = NAV.map(([id, ic, t]) => `<a href="#${id}" data-v="${id}">${ic} ${t}</a>`).join("");
    window.onhashchange = () => this.go(location.hash.slice(1) || "home");
    await this.loadAgents();
    this.updateBadges(this.status.engine);
    const p = this.status.portable;
    document.getElementById("usbBadge").innerHTML = p ? `🔌 USB modu · ${esc(this.status.drive)}` : "💻 Bilgisayar modu";
    const ap = await API.get("/api/approvals");
    ap.items.forEach((a) => this.showApproval(a));
    this.go(location.hash.slice(1) || "home");
  },
  unlockScreen() {
    document.getElementById("wizard").classList.remove("hidden");
    document.getElementById("wizard").innerHTML = `<div class="wiz" style="max-width:460px"><div class="logo big-logo">🔒</div><h1>AI OFFICE kilitli</h1>
      <p>Verileriniz şifreli kasada. Açmak için parolanızı girin.</p><input id="upw" type="password" placeholder="Parola" onkeydown="if(event.key==='Enter')App.unlock()">
      <div class="foot"><span id="uerr"></span><button class="btn big" onclick="App.unlock()">Kilidi aç →</button></div></div>`;
  },
  async unlock() {
    const pw = document.getElementById("upw").value;
    try { await API.post("/api/vault/unlock", { password: pw }); toast("Kasa açıldı."); location.reload(); }
    catch (e) { document.getElementById("uerr").innerHTML = `<span class="badge err">${esc(e.message)}</span>`; }
  },
  async loadAgents() {
    const r = await API.get("/api/agents");
    this.agents = r.agents;
    this.meta = r;
    r.agents.forEach((a) => { if (a.state) this.states[a.id] = a.state; });
  },
  agent(id) { return this.agents.find((a) => a.id === id) || { id, title: id === "kullanici" ? "Siz (Yönetici)" : id, name: id, avatar: id === "kullanici" ? "👤" : "🤖" }; },
  go(v) {
    if (!NAV.some((n) => n[0] === v)) v = "home";
    this.view = v;
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.v === v));
    document.getElementById("viewTitle").textContent = NAV.find((n) => n[0] === v)[2];
    document.body.classList.remove("nav-open");
    document.getElementById("drawer").classList.add("hidden");
    Views[v](document.getElementById("view"));
  },
  refresh() { if (Views[this.view]) Views[this.view](document.getElementById("view")); },
  updateBadges(engine) {
    if (!engine) return;
    const map = { hazir: "ok", hata: "err", baslatiliyor: "warn", durdu: "" };
    const label = { hazir: "Hazır", hata: "Hata", baslatiliyor: "Başlatılıyor…", durdu: "Kapalı" }[engine.status] || engine.status;
    const el = document.getElementById("engineBadge");
    el.className = "badge " + (map[engine.status] || "");
    el.innerHTML = `🧠 Motor: ${label}${engine.model_name ? "<br><small>" + esc(engine.model_name) + "</small>" : ""}${engine.queue ? " · sırada " + engine.queue : ""}`;
    el.title = engine.error || "";
  },
  bindWS() {
    WS.on("agent_state", (m) => {
      this.states[m.agent_id] = m.state;
      if (["office", "home"].includes(this.view)) Views.updateDesk?.(m.agent_id);
    });
    WS.on("agent_states", (m) => Object.assign(this.states, m.states));
    WS.on("message", (m) => {
      this.liveMessages.push(m.message);
      if (this.liveMessages.length > 200) this.liveMessages.shift();
      Views.onMessage?.(m.message);
    });
    WS.on("task", (m) => Views.onTask?.(m.task));
    WS.on("engine", (m) => this.updateBadges(m.engine));
    WS.on("resources", (m) => {
      const r = m.resources;
      document.getElementById("resBadge").textContent = `CPU %${Math.round(r.cpu_percent)} · RAM %${Math.round(r.ram_percent)}${r.gpu ? " · GPU %" + Math.round(r.gpu.percent) : ""} · Disk ${r.disk.free_gb} GB boş`;
      this.updateBadges(m.engine);
      Views.onResources?.(r);
    });
    WS.on("approval_request", (m) => this.showApproval(m.approval));
    WS.on("approval_closed", (m) => document.getElementById("ap-" + m.id)?.remove());
    WS.on("safe_exit", (m) => {
      if (m.step === "done") {
        window.__exiting = true;
        document.body.innerHTML = `<div id="wizard" style="display:grid"><div class="wiz"><h1>⏏ ${esc(m.message)}</h1><ul>${m.steps.map((s) => `<li>✔ ${esc(s)}</li>`).join("")}</ul></div></div>`;
      } else toast(m.step);
    });
  },
  showApproval(a) {
    const ag = this.agent(a.agent);
    const d = document.createElement("div");
    d.className = "approval"; d.id = "ap-" + a.id;
    d.innerHTML = `<b>⚠ Onay gerekiyor: ${esc(a.action)}</b><p><small>${esc(ag.avatar)} ${esc(ag.title)} şu işlemi yapmak istiyor:</small><br><code>${esc(a.detail)}</code></p>
      <div class="row"><button class="btn" onclick="App.answer('${a.id}',true)">Onayla</button><button class="btn danger" onclick="App.answer('${a.id}',false)">Reddet</button></div>`;
    document.getElementById("approvals").appendChild(d);
  },
  async answer(id, approve) { await API.post(`/api/approvals/${id}`, { approve }); document.getElementById("ap-" + id)?.remove(); },
  async openAgent(id) {
    const r = await API.get(`/api/agents/${id}`);
    const a = r.agent, st = a.state || {};
    const dr = document.getElementById("drawer");
    dr.classList.remove("hidden");
    const msgs = r.messages.map((m) => Views.msgHtml(m)).join("") || "<small>Henüz konuşma yok.</small>";
    dr.innerHTML = `<div class="row between"><h2>${a.avatar} ${esc(a.name)}</h2><button class="btn sec sm" onclick="document.getElementById('drawer').classList.add('hidden')">✕</button></div>
      <p><b>${esc(a.title)}</b> · ${esc(a.department)}<br><small>${esc(a.expertise)}</small></p>
      <div class="kv"><b>Durum</b><span>${Views.statusPill(st.status)}</span><b>Ne yapıyor</b><span>${esc(st.bubble || "—")}</span>
      <b>Görüştüğü ajan</b><span>${st.with ? esc(this.agent(st.with).title) : "—"}</span><b>Görev</b><span>${st.task_id ? `<a href="#tasks" onclick="Views.openTask('${st.task_id}')">${st.task_id}</a>` : "—"}</span>
      <b>Görev tanımı</b><span>${esc(a.duty)}</span><b>Yetki</b><span>${["", "Okuma", "Düzenleme", "İşlem"][a.permission]}</span>
      <b>Araçlar</b><span>${a.tools.map((t) => `<span class="pill">${t}</span>`).join(" ")}</span><b>Hafıza</b><span>${r.memory.length} kayıt</span></div>
      <h3 style="margin-top:14px">Doğrudan konuş</h3><div class="row"><input id="dchat" placeholder="${esc(a.name)} ile konuşun…" onkeydown="if(event.key==='Enter')App.chat('${a.id}')"><button class="btn" onclick="App.chat('${a.id}')">Gönder</button></div>
      <div class="row" style="margin-top:6px"><button class="btn sec sm" onclick="Views.useAgent('${a.id}')">Bu ajana görev ver</button></div>
      <h3 style="margin-top:14px">Son konuşmalar</h3><div class="feed" id="dfeed">${msgs}</div>
      <h3 style="margin-top:14px">Çalışma geçmişi</h3>${r.tasks.map((t) => `<div class="row between"><a href="#tasks" onclick="Views.openTask('${t.id}')">${esc(t.title)}</a>${taskBadge(t.status)}</div>`).join("") || "<small>Yok</small>"}`;
  },
  async chat(id) {
    const inp = document.getElementById("dchat");
    const text = inp.value.trim(); if (!text) return;
    inp.value = ""; inp.disabled = true;
    try { await API.post(`/api/agents/${id}/chat`, { message: text }); } catch (e) { toast("Hata: " + e.message); }
    inp.disabled = false;
    this.openAgent(id);
  },
};

async function stopAll() {
  if (!confirm("Bütün ajanlar ve görevler durdurulsun mu?")) return;
  await API.post("/api/system/stop-all");
  toast("Bütün ajanlar durduruldu.");
}
async function safeExit() {
  if (!confirm("Aktif görevler durdurulacak, veriler diske yazılacak ve program kapanacak. Devam?")) return;
  await API.post("/api/system/safe-exit");
}

App.init().catch((e) => { document.body.innerHTML = `<div style="padding:40px"><h2>AI OFFICE sunucusuna bağlanılamadı</h2><p>${esc(e.message)}</p><p>START_AI_OFFICE.bat penceresinin açık olduğundan emin olun.</p></div>`; });
