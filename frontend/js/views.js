// Ekranlar
const WORKING = ["Düşünüyor", "Araştırıyor", "Yazıyor", "Dosya inceliyor", "Kontrol yapıyor", "Başka ajanla görüşüyor"];
const Views = {
  statusPill(s) {
    s = s || "Müsait";
    const cls = "s-" + s.split(" ")[0];
    return `<span class="pill ${cls}">${esc(s)}</span>`;
  },
  msgHtml(m) {
    const a = App.agent(m.sender), b = App.agent(m.receiver);
    const to = m.receiver === "ofis" ? "" : m.receiver === "ekip" ? " → Ekip" : ` → ${esc(b.title)}`;
    return `<div class="msg ${esc(m.kind)} ${m.sender === "kullanici" ? "kullanici" : ""}"><span class="k">${esc(m.kind)} · ${fmtTime(m.ts)}</span>
      <div class="who">${a.avatar || ""} ${esc(a.title)}${to}</div>${esc(m.content)}</div>`;
  },
  onMessage(m) {
    const feed = document.getElementById("liveFeed");
    if (feed) { feed.insertAdjacentHTML("beforeend", this.msgHtml(m)); feed.scrollTop = feed.scrollHeight; }
    const tf = document.getElementById("taskFeed");
    if (tf && tf.dataset.task === m.task_id) { tf.insertAdjacentHTML("beforeend", this.msgHtml(m)); tf.scrollTop = tf.scrollHeight; }
  },
  onTask(t) {
    if (App.view === "home") this.renderActiveTask(t);
    if (App.view === "tasks") { if (document.getElementById("taskFeed")?.dataset.task === t.id) this.openTask(t.id, true); else this.tasks(document.getElementById("view")); }
  },
  onResources(r) {
    const el = document.getElementById("resCard");
    if (el) el.innerHTML = this.resHtml(r);
  },
  resHtml(r) {
    const b = (l, v) => `<div style="margin-bottom:8px"><div class="row between"><small>${l}</small><small>%${Math.round(v)}</small></div><div class="bar"><i style="width:${v}%"></i></div></div>`;
    return b("CPU", r.cpu_percent) + b(`RAM (${r.ram_used_gb}/${r.ram_total_gb} GB)`, r.ram_percent) + (r.gpu ? b(`GPU${r.gpu.vram_total_gb ? ` (${r.gpu.vram_used_gb}/${r.gpu.vram_total_gb} GB VRAM)` : ""}`, r.gpu.percent) : "<small>GPU kullanımı: ölçülemedi / GPU yok</small><br>") + b(`Disk (${r.disk.free_gb} GB boş)`, r.disk.percent);
  },

  // ---------------------------------------------------------------- Ana sayfa
  async home(el) {
    const hired = App.agents.filter((a) => a.hired);
    const [tasks, mem, res, msgs] = await Promise.all([API.get("/api/tasks"), API.get("/api/memory"), API.get("/api/system/resources"), API.get("/api/messages?limit=30")]);
    const opts = hired.map((a) => `<option value="${a.id}">${a.avatar} ${esc(a.title)}${a.id === "ceo" ? " (plan + ekip)" : " (doğrudan)"}</option>`).join("");
    el.innerHTML = `<div class="card command"><h2>Komut Merkezi</h2>
      <textarea id="cmd" placeholder="Örn: Belgeler klasörümdeki PDF dosyalarını incele, yapay sinir ağlarıyla ilgili olanları ayır ve kaynakçalı Word raporu hazırla."></textarea>
      <div class="row" style="margin-top:8px"><select id="cmdAgent" style="width:auto">${opts}</select><button class="btn big" onclick="Views.send()">Gönder ▶</button>
      <small class="muted">CEO komutu analiz eder, plan çıkarır; onayınızdan sonra ekip çalışır.</small></div>
      <div class="row" style="margin-top:8px">${["İnternette araştırma yap ve Word raporu hazırla: ", "Çalışma klasörümdeki dosyaları listele ve sınıflandır", "Bir konu hakkında 5 slaytlık sunum oluştur: ", "Excel tablosu oluştur: "].map((s) => `<button class="btn sec sm" onclick="document.getElementById('cmd').value='${s}';document.getElementById('cmd').focus()">${s.replace(/: $/, "")}</button>`).join("")}</div></div>
      <div id="activeTask"></div>
      <div class="grid g3"><div class="card" style="grid-column:span 2"><h3>Sanal ofis (canlı)</h3><div id="miniOffice"></div></div>
      <div class="card"><h3>Sistem kaynakları</h3><div id="resCard">${this.resHtml(res.resources)}</div>
      <h3 style="margin-top:12px">Hafıza durumu</h3><div class="row">${Object.entries(mem.layers).map(([k, v]) => `<span class="badge">${v}: ${mem.stats[k]}</span>`).join("")}<span class="badge">Bilgi bankası: ${mem.stats.kb_docs} belge</span></div>
      <h3 style="margin-top:12px">USB modu</h3><span class="badge ${App.status.portable ? "turq" : ""}">${App.status.portable ? "Taşınabilir · " + esc(App.status.drive) : "Bilgisayar modu"}</span></div></div>
      <div class="grid g2"><div class="card"><h3>Son konuşmalar</h3><div class="feed" id="liveFeed">${msgs.messages.map((m) => this.msgHtml(m)).join("") || "<small>Henüz mesaj yok.</small>"}</div></div>
      <div class="card"><h3>Görevler</h3>${this.taskTable(tasks.tasks.slice(0, 8))}</div></div>`;
    this.renderMiniOffice();
    const feed = document.getElementById("liveFeed"); feed.scrollTop = feed.scrollHeight;
    const active = tasks.tasks.find((t) => ["onay_bekliyor", "calisiyor", "plan_hazirlaniyor", "sirada"].includes(t.status) || t.id === this.currentTask);
    if (active) this.renderActiveTask(active);
    else if (this.currentTask) API.get(`/api/tasks/${this.currentTask}`).then((r) => this.renderActiveTask(r.task)).catch(() => {});
  },
  async send() {
    const text = document.getElementById("cmd").value.trim();
    if (!text) return toast("Lütfen bir komut yazın.");
    const agent = document.getElementById("cmdAgent").value;
    try {
      const r = await API.post("/api/command", { text, agent_id: agent === "ceo" ? null : agent });
      document.getElementById("cmd").value = "";
      this.renderActiveTask(r.task);
    } catch (e) { toast("Hata: " + e.message); }
  },
  useAgent(id) { document.getElementById("drawer").classList.add("hidden"); location.hash = "#home"; setTimeout(() => { const s = document.getElementById("cmdAgent"); if (s) s.value = id; }, 300); },
  renderActiveTask(t) {
    const el = document.getElementById("activeTask");
    if (!el) return;
    if (this.currentTask && t.id !== this.currentTask && !["onay_bekliyor", "calisiyor", "plan_hazirlaniyor"].includes(t.status)) return;
    this.currentTask = t.id;
    const steps = (t.plan?.adimlar || []).map((s) => {
      const a = App.agent(s.ajan);
      const st = { bekliyor: "⏳", calisiyor: "🔄", tamamlandi: "✅", hata: "❌" }[s.durum] || "";
      return `<div class="plan-step"><div class="n">${s.id}</div><div style="flex:1"><b>${a.avatar} ${esc(a.title)}</b> – ${esc(s.baslik)} <span class="pill">${esc(s.cikti)}</span> ${st}<br><small>${esc(s.talimat)}</small></div></div>`;
    }).join("");
    const actions = t.status === "onay_bekliyor" ? `<button class="btn big" onclick="Views.approve('${t.id}')">✔ Planı onayla ve başlat</button><button class="btn sec" onclick="Views.cancel('${t.id}')">İptal</button>`
      : t.status === "calisiyor" ? `<input id="note" placeholder="Görev sırasında yeni talimat ver…" style="max-width:420px" onkeydown="if(event.key==='Enter')Views.note('${t.id}')"><button class="btn sec" onclick="Views.note('${t.id}')">Talimat gönder</button><button class="btn danger" onclick="Views.cancel('${t.id}')">Durdur</button>`
      : t.status === "sirada" ? `<span class="badge queue">Sırada – önceki görev bitince başlayacak</span><button class="btn danger" onclick="Views.cancel('${t.id}')">İptal</button>`
      : ["hata", "iptal", "durduruldu"].includes(t.status) && t.plan ? `<button class="btn" onclick="Views.approve('${t.id}')">Devam ettir</button>` : "";
    const files = (t.files || []).map((f) => this.fileLink(f)).join(" ");
    el.innerHTML = `<div class="card"><div class="row between"><h3>${esc(t.title)}</h3>${taskBadge(t.status)}</div>
      ${t.status === "plan_hazirlaniyor" ? '<p class="muted">CEO komutu analiz ediyor ve plan hazırlıyor… (yerel model hızına bağlıdır)</p>' : ""}
      ${t.plan?.ozet ? `<p><b>CEO planı:</b> ${esc(t.plan.ozet)}</p>` : ""}${steps}
      <div class="bar" style="margin:10px 0"><i style="width:${t.progress || 0}%"></i></div>
      ${files ? `<p><b>Oluşturulan dosyalar:</b> ${files}</p>` : ""}${t.result ? `<div class="msg sonuc">${esc(t.result)}</div>` : ""}
      ${(t.errors || []).length ? `<div class="msg hata">${t.errors.map(esc).join("<br>")}</div>` : ""}
      <div class="row" style="margin-top:8px">${actions}<a href="#tasks" onclick="setTimeout(()=>Views.openTask('${t.id}'),200)">Ayrıntılar →</a></div></div>`;
  },
  fileLink(f) {
    const name = f.split(/[\\/]/).pop();
    return `<span class="badge turq">📄 <a href="/api/files/download?path=${encodeURIComponent(f)}">${esc(name)}</a> · <a href="#" onclick="Views.openFile('${encQ(f)}',true);return false">konum</a></span>`;
  },
  async openFile(enc, reveal) { const r = await API.post("/api/files/open", { path: decodeURIComponent(enc), reveal }); if (r.note) toast(r.note + " Konum: " + r.path, 6000); },
  async approve(id) { try { await API.post(`/api/tasks/${id}/approve`); } catch (e) { toast(e.message); } },
  async cancel(id) { await API.post(`/api/tasks/${id}/cancel`); toast("Görev durduruluyor…"); },
  async note(id) { const i = document.getElementById("note"); if (!i.value.trim()) return; await API.post(`/api/tasks/${id}/note`, { message: i.value }); i.value = ""; toast("Talimat sıradaki ajana iletilecek."); },

  // ---------------------------------------------------------------- Sanal ofis
  deskHtml(a) {
    const st = App.states[a.id] || { status: "Müsait" };
    const working = WORKING.includes(st.status);
    const bubble = st.bubble && st.status !== "Müsait" ? `<div class="bubble">${esc(st.bubble)}</div>` : "";
    return `<div class="desk ${working ? "working" : ""}" id="desk-${a.id}" onclick="App.openAgent('${a.id}')">${bubble}
      <div class="pc"><div class="av" style="border-color:${a.color}">${a.avatar}</div></div>
      <div class="nm">${esc(a.name)}</div><div class="st"><small>${esc(a.title)}</small><br>${this.statusPill(st.status)}</div></div>`;
  },
  officeHtml(compact) {
    const hired = App.agents.filter((a) => a.hired);
    const depts = App.meta.departments;
    const inMeeting = (a) => ["meeting"].includes((App.states[a.id] || {}).zone);
    return `<div class="office">${depts.map((d) => {
      const list = d === "Toplantı Odası" ? hired.filter(inMeeting) : hired.filter((a) => a.department === d && !inMeeting(a));
      if (compact && !list.length && d !== "Toplantı Odası") return "";
      return `<div class="dept ${d === "Toplantı Odası" ? "meeting" : ""}" data-dept="${esc(d)}"><h4>${esc(d)} <small>${list.length}</small></h4><div class="desks">${list.map((a) => this.deskHtml(a)).join("") || "<small class='muted'>Boş</small>"}</div></div>`;
    }).join("")}</div>`;
  },
  renderMiniOffice() { const el = document.getElementById("miniOffice"); if (el) el.innerHTML = `<div class="floor-wrap">${Office.html(520)}</div>`; },
  updateDesk(id) {
    if (App.view === "office" && this._list) return this.office(document.getElementById("view"));
    Office.update(id);
  },
  async office(el) {
    const hired = App.agents.filter((a) => a.hired);
    const list = `<table><tr><th></th><th>Ajan</th><th>Departman</th><th>Durum</th><th>Ne yapıyor</th></tr>${hired.map((a) => {
      const st = App.states[a.id] || {};
      return `<tr class="click" onclick="App.openAgent('${a.id}')"><td>${a.avatar}</td><td><b>${esc(a.name)}</b><br><small>${esc(a.title)}</small></td><td>${esc(a.department)}</td><td>${this.statusPill(st.status)}</td><td><small>${esc(st.bubble || "")}</small></td></tr>`;
    }).join("")}</table>`;
    el.innerHTML = `<div class="row between" style="margin-bottom:12px"><small class="muted">Ajan hareketleri ve konuşma balonları gerçek görev olaylarına bağlıdır. Ajana tıklayın.</small>
      <div class="row"><button class="btn ${this._list ? "sec" : ""} sm" onclick="Views._list=false;Views.office(document.getElementById('view'))">🏢 Ofis görünümü</button>
      <button class="btn ${this._list ? "" : "sec"} sm" onclick="Views._list=true;Views.office(document.getElementById('view'))">☰ Liste görünümü</button></div></div>
      <div id="officeArea">${this._list ? `<div class="card">${list}</div>` : `<div class="floor-wrap">${Office.html(720)}</div>`}</div>
      <div class="card" style="margin-top:16px"><h3>Ofis konuşmaları (canlı)</h3><div class="feed" id="liveFeed">${App.liveMessages.slice(-40).map((m) => this.msgHtml(m)).join("") || "<small>Bir görev başlatın; ajanların konuşmaları burada görünür.</small>"}</div></div>`;
  },

  // ---------------------------------------------------------------- Ajanlar
  async agents(el) {
    await App.loadAgents();
    const hired = App.agents.filter((a) => a.hired);
    const groups = {};
    hired.forEach((a) => (groups[a.instance_of || a.id] ||= []).push(a));
    el.innerHTML = `<div class="card"><h2>Ofisteki çalışanlar (${hired.length})</h2>
      <p class="muted">Adları değiştirebilir, her uzmanlıktan kaç kişi çalışacağını − / + ile ayarlayabilirsiniz. Yeni kişiler aynı uzmanlık profiliyle çalışır.</p>
      <div class="grid g3">${Object.entries(groups).map(([base, list]) => {
        const b = App.agents.find((x) => x.id === base) || list[0];
        return `<div class="agent-card on"><div class="av">${b.avatar}</div><div style="flex:1"><b>${esc(b.title)}</b><br><small>${esc(b.department)}</small>
        <div class="row" style="margin:6px 0">${base === "ceo" ? '<small>CEO tektir</small>' : `<button class="btn sec sm" onclick="Views.setCount('${base}',${list.length - 1})">−</button>
        <b>${list.length}</b><button class="btn sec sm" onclick="Views.setCount('${base}',${list.length + 1})">+</button><small>kişi</small>`}</div>
        ${list.map((a) => `<div class="row" style="margin-top:4px"><span>${a.avatar}</span><input id="nm-${a.id}" value="${esc(a.name)}" style="flex:1;padding:5px 8px"
          onkeydown="if(event.key==='Enter')Views.rename('${a.id}')"><button class="btn sm" title="Adı kaydet" onclick="Views.rename('${a.id}')">✓</button>
          <button class="btn sec sm" title="Aç / konuş" onclick="App.openAgent('${a.id}')">💬</button>${Views.statusPill((App.states[a.id] || {}).status)}</div>`).join("")}
        <div class="row" style="margin-top:6px">${!b.builtin && !b.copy ? `<button class="btn danger sm" onclick="Views.delCustom('${b.id}')">Özel ajanı sil</button>` : ""}</div></div></div>`;
      }).join("")}</div></div>`;
  },
  async rename(id) {
    const v = document.getElementById("nm-" + id).value.trim();
    if (!v) return toast("Ad boş olamaz.");
    try { await API.post(`/api/agents/${id}/rename`, { name: v }); toast("Ad kaydedildi: " + v); await App.loadAgents(); }
    catch (e) { toast(e.message); }
  },
  async setCount(id, n) {
    try { await API.post(`/api/agents/${id}/count`, { count: n }); await App.loadAgents(); App.refresh(); }
    catch (e) { toast(e.message); }
  },
  async fire(id) { await API.post(`/api/agents/${id}/fire`); await App.loadAgents(); App.refresh(); },
  async hire(id) { await API.post("/api/agents/hire", { ids: [id] }); await App.loadAgents(); App.refresh(); },
  async delCustom(id) { if (!confirm("Özel ajan silinsin mi?")) return; await API.del(`/api/agents/custom/${id}`); await App.loadAgents(); App.refresh(); },
  async market(el) {
    await App.loadAgents();
    const cats = {};
    App.agents.filter((a) => !a.copy).forEach((a) => (cats[a.category] ||= []).push(a));
    const tools = App.meta.tools;
    el.innerHTML = Object.entries(cats).map(([c, list]) => `<div class="card"><h2>${esc(c)}</h2><div class="grid g3">${list.map((a) => `<div class="agent-card ${a.hired ? "on" : ""}">
      <div class="av">${a.avatar}</div><div style="flex:1"><b>${esc(a.title)}</b><br><small>${esc(a.name)}</small><p style="margin:4px 0"><small>${esc(a.duty)}</small></p>
      <small>Araçlar: ${a.tools.map((t) => `<span class="pill">${t}</span>`).join(" ")}</small><br><small>Yetki: ${["", "Okuma", "Düzenleme", "İşlem"][a.permission]}</small>
      <div class="row" style="margin-top:6px">${a.id === "ceo" ? '<span class="badge ok">Ofiste (tek)</span>' : a.builtin || !a.copy ? `<button class="btn sec sm" onclick="Views.setCount('${a.id}',${a.team_count - 1})" ${a.team_count ? "" : "disabled"}>−</button>
        <b>${a.team_count}</b><button class="btn sm" onclick="Views.setCount('${a.id}',${a.team_count + 1})">+</button><small>kişi ofiste</small>` : ""}</div></div></div>`).join("")}</div></div>`).join("") +
      `<div class="card"><h2>➕ Kendi ajanını oluştur</h2><div class="grid g2">
      <div><label>Ad</label><input id="ca_name" placeholder="Örn: Kemal Bey"></div><div><label>Unvan / uzmanlık</label><input id="ca_title" placeholder="Örn: Savunma Sanayi Analisti"></div>
      <div><label>Uzmanlık alanı</label><input id="ca_exp" placeholder="Hava savunma sistemleri, teknik literatür"></div><div><label>Avatar (emoji)</label><input id="ca_av" value="🧑‍🔬"></div>
      <div style="grid-column:span 2"><label>Görev tanımı</label><textarea id="ca_duty" rows="2"></textarea></div>
      <div><label>Departman</label><select id="ca_dept">${App.meta.departments.filter((d) => d !== "Toplantı Odası").map((d) => `<option>${d}</option>`).join("")}</select></div>
      <div><label>Yetki seviyesi</label><select id="ca_perm"><option value="1">1 – Okuma</option><option value="2" selected>2 – Düzenleme</option><option value="3">3 – İşlem (onaylı)</option></select></div>
      <div style="grid-column:span 2"><label>Araçlar</label><div class="row">${tools.map((t) => `<label class="pill"><input type="checkbox" class="ca_tool" value="${t}" style="width:auto"> ${t}</label>`).join("")}</div></div>
      <div style="grid-column:span 2"><label>Diğer ajanlarla iletişim</label><select id="ca_talk"><option value="all">Tüm ajanlarla konuşabilir</option><option value="none">Sadece CEO ile</option></select></div>
      <div style="grid-column:span 2"><label>Özel sistem talimatı (isteğe bağlı)</label><textarea id="ca_sys" rows="2"></textarea></div></div>
      <button class="btn" style="margin-top:10px" onclick="Views.createAgent()">Ajanı oluştur ve işe al</button></div>`;
  },
  async createAgent() {
    const v = (id) => document.getElementById(id).value;
    const data = { name: v("ca_name"), title: v("ca_title"), expertise: v("ca_exp"), avatar: v("ca_av"), duty: v("ca_duty"), department: v("ca_dept"),
      permission: +v("ca_perm"), can_talk_to: v("ca_talk"), system_prompt: v("ca_sys"), tools: [...document.querySelectorAll(".ca_tool:checked")].map((c) => c.value) };
    if (!data.title) return toast("Unvan gerekli.");
    await API.post("/api/agents/custom", data);
    toast("Ajan oluşturuldu ve ofise eklendi.");
    await App.loadAgents(); App.refresh();
  },

  // ---------------------------------------------------------------- Görevler
  taskTable(list) {
    if (!list.length) return "<small>Henüz görev yok.</small>";
    return `<table><tr><th>Görev</th><th>Durum</th><th>İlerleme</th><th>Başlangıç</th></tr>${list.map((t) => `<tr class="click" onclick="location.hash='#tasks';setTimeout(()=>Views.openTask('${t.id}'),150)">
      <td>${esc(t.title)}<br><small>${App.agent(t.lead_agent).avatar} ${(t.agents || []).length} ajan · ${(t.files || []).length} dosya</small></td><td>${taskBadge(t.status)}</td>
      <td><div class="bar" style="width:80px"><i style="width:${t.progress || 0}%"></i></div></td><td><small>${fmtTime(t.created)}</small></td></tr>`).join("")}</table>`;
  },
  async tasks(el) {
    const r = await API.get("/api/tasks");
    el.innerHTML = `<div class="grid g2"><div class="card"><h2>Görev geçmişi</h2>${this.taskTable(r.tasks)}</div><div id="taskDetail" class="card"><small>Ayrıntı için bir göreve tıklayın.</small></div></div>`;
  },
  async openTask(id, keepScroll) {
    if (!document.getElementById("taskDetail")) await this.tasks(document.getElementById("view"));
    const r = await API.get(`/api/tasks/${id}`);
    const t = r.task;
    const dur = t.started ? Math.round(((t.finished || Date.now() / 1000) - t.started) / 60) + " dk" : "—";
    const box = document.getElementById("taskDetail");
    box.innerHTML = `<div class="row between"><h2>${esc(t.title)}</h2>${taskBadge(t.status)}</div>
      <div class="kv"><b>Açıklama</b><span>${esc(t.command)}</span><b>Sorumlu ajan</b><span>${esc(App.agent(t.lead_agent).title)}</span>
      <b>Görevli ajanlar</b><span>${(t.agents || []).map((a) => App.agent(a).avatar + " " + esc(App.agent(a).title)).join(", ")}</span>
      <b>Başlangıç</b><span>${fmtTime(t.started || t.created)}</span><b>Süre</b><span>${dur}</span><b>İlerleme</b><span>%${t.progress || 0}</span>
      <b>Proje klasörü</b><span><small>${esc(t.project_dir)}</small></span><b>Dosyalar</b><span>${(t.files || []).map((f) => this.fileLink(f)).join(" ") || "—"}</span>
      <b>Hatalar</b><span>${(t.errors || []).map(esc).join("<br>") || "—"}</span></div>
      ${t.result ? `<h3 style="margin-top:10px">Sonuç</h3><div class="msg sonuc">${esc(t.result)}</div>` : ""}
      <div class="row" style="margin:10px 0">${t.status === "onay_bekliyor" ? `<button class="btn" onclick="Views.approve('${t.id}')">Onayla ve başlat</button>` : ""}
      ${["hata", "iptal", "durduruldu"].includes(t.status) && t.plan ? `<button class="btn" onclick="Views.approve('${t.id}')">Devam ettir</button>` : ""}
      ${["calisiyor", "plan_hazirlaniyor", "onay_bekliyor"].includes(t.status) ? `<button class="btn danger" onclick="Views.cancel('${t.id}')">Durdur</button>` : ""}</div>
      <h3>Adımlar</h3>${(t.plan?.adimlar || []).map((s) => `<details class="plan-step" style="display:block"><summary><b>${s.id}. ${App.agent(s.ajan).avatar} ${esc(App.agent(s.ajan).title)}</b> – ${esc(s.baslik)} · ${esc(s.durum)}</summary><pre>${esc(s.sonuc || "")}</pre></details>`).join("") || "<small>Plan yok</small>"}
      <h3>Ajan konuşmaları</h3><div class="feed" id="taskFeed" data-task="${t.id}">${r.messages.map((m) => this.msgHtml(m)).join("")}</div>`;
    const f = document.getElementById("taskFeed"); f.scrollTop = f.scrollHeight;
  },
  async meetings(el) {
    const r = await API.get("/api/messages?kind=toplanti&limit=100");
    const a = await API.get("/api/messages?kind=atama&limit=200");
    el.innerHTML = `<div class="card"><h2>Toplantı kayıtları</h2><p class="muted">Görev onaylandığında CEO, ekibi toplantı odasında toplayıp görevleri atar.</p>
      ${r.messages.reverse().map((m) => `<div class="card" style="background:var(--gray)">${this.msgHtml(m)}${a.messages.filter((x) => x.task_id === m.task_id).map((x) => this.msgHtml(x)).join("")}
      <a href="#tasks" onclick="setTimeout(()=>Views.openTask('${m.task_id}'),150)">Göreve git →</a></div>`).join("") || "<small>Henüz toplantı yapılmadı.</small>"}</div>`;
  },

  // ---------------------------------------------------------------- Hafıza
  async memory(el, q = "", layer = "") {
    const r = await API.get(`/api/memory?q=${encodeURIComponent(q)}&layer=${layer}`);
    el.innerHTML = `<div class="card"><h2>Hafıza Merkezi</h2><div class="row">${Object.entries(r.layers).map(([k, v]) => `<span class="badge">${v}: ${r.stats[k]}</span>`).join("")}</div>
      <div class="row" style="margin-top:10px"><input id="mq" value="${esc(q)}" placeholder="Hafızada ara…" style="max-width:300px" onkeydown="if(event.key==='Enter')Views.memory(document.getElementById('view'),this.value,document.getElementById('ml').value)">
      <select id="ml" style="width:auto" onchange="Views.memory(document.getElementById('view'),document.getElementById('mq').value,this.value)"><option value="">Tüm katmanlar</option>${Object.entries(r.layers).map(([k, v]) => `<option value="${k}" ${k === layer ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <div class="card"><h3>Kullanıcı tercihi / çalışma kuralı ekle</h3><div class="row"><input id="mnew" placeholder="Örn: Raporlarda APA kaynakça formatı kullan."><button class="btn" onclick="Views.addMem()">Kaydet</button></div>
      <small>Kullanıcı hafızası her görevde ajanlara verilir. Saklanacak bilgileri siz yönetirsiniz.</small></div>
      <div class="card"><table><tr><th>Katman</th><th>İçerik</th><th>Kaynak</th><th>Güven</th><th>Oluşturan</th><th>Tarih</th><th></th></tr>${r.items.map((m) => `<tr>
      <td><span class="pill">${esc(r.layers[m.layer] || m.layer)}</span>${m.shared ? '<br><span class="pill">paylaşımlı</span>' : ""}</td><td>${esc(m.content)}</td><td><small>${esc(m.source)}</small></td>
      <td>${(m.confidence || 0).toFixed(1)}</td><td>${esc(App.agent(m.created_by).title)}</td><td><small>${fmtTime(m.updated)}</small></td>
      <td><button class="btn sec sm" onclick="Views.editMem(${m.id})">Düzenle</button> <button class="btn sec sm" onclick="Views.shareMem(${m.id},${m.shared ? 0 : 1})">${m.shared ? "Paylaşımı kapat" : "Ajanlarla paylaş"}</button> <button class="btn danger sm" onclick="Views.delMem(${m.id})">Sil</button></td></tr>`).join("") || "<tr><td colspan=7><small>Kayıt yok</small></td></tr>"}</table>
      <p class="muted">Eski ve çelişkili bilgiler otomatik doğru kabul edilmez: ajanlara tarih ve güven düzeyiyle birlikte "doğrulanmamış" olarak verilir.</p></div>`;
  },
  async addMem() { const v = document.getElementById("mnew").value.trim(); if (!v) return; await API.post("/api/memory", { layer: "kullanici", content: v }); this.memory(document.getElementById("view")); },
  async editMem(id) { const c = prompt("Yeni içerik:"); if (c) { await API.put(`/api/memory/${id}`, { content: c }); this.memory(document.getElementById("view")); } },
  async shareMem(id, v) { await API.put(`/api/memory/${id}`, { shared: v }); this.memory(document.getElementById("view")); },
  async delMem(id) { if (confirm("Silinsin mi?")) { await API.del(`/api/memory/${id}`); this.memory(document.getElementById("view")); } },
  async kb(el) {
    setTimeout(() => { this.embStatus(); this.loadSources(); }, 50);
    const r = await API.get("/api/kb");
    el.innerHTML = `<div class="card"><h2>Bilgi Bankası</h2><p>Belgeleri ekleyin (PDF, DOCX, XLSX, PPTX, TXT, MD, HTML). Metin çıkarılır, parçalara ayrılır ve <b>internetsiz</b> anahtar kelime aramasıyla ajanlara kaynak olarak sunulur.</p>
      <div id="embBox" class="msg">Anlamsal arama durumu yükleniyor…</div>
      <div class="row"><input id="kbp" placeholder="Dosya veya klasör yolu (izinli klasörlerde)"><button class="btn sec" onclick="Views.pick('kbp')">Klasör seç</button><button class="btn" onclick="Views.kbAdd()">Ekle</button><button class="btn sec" onclick="Views.kbRefresh()">Güncellemeleri kontrol et</button></div></div>
      <div class="card"><h2>🌐 İnternet kaynaklarım</h2>
      <p>Ajanların özellikle bakmasını istediğiniz siteleri ekleyin. <b>Öncelikli</b> kaynaklar web aramalarında önce aranır ve ajanlara listelenir;
      <b>içeriği eklenen</b> kaynaklar indirilip bilgi bankasına kaydedilir (internet yokken de aranabilir).</p>
      <textarea id="srcUrls" rows="3" placeholder="Her satıra bir adres. İsterseniz ad da verin:\nTÜBİTAK | https://www.tubitak.gov.tr\nhttps://dergipark.org.tr\nhttps://www.ssb.gov.tr/haberler"></textarea>
      <div class="row" style="margin-top:6px"><label class="row"><input type="checkbox" id="srcPrio" checked style="width:auto"> Ajanlar önce buraya baksın</label>
      <label class="row"><input type="checkbox" id="srcIdx" checked style="width:auto"> İçeriği indir ve bilgi bankasına ekle</label>
      <label class="row">Sayfa sayısı <select id="srcPages" style="width:auto">${[1, 5, 10, 20, 30].map((n) => `<option value="${n}">${n === 1 ? "sadece bu sayfa" : n + " sayfa (aynı siteden)"}</option>`).join("")}</select></label>
      <button class="btn" onclick="Views.addSources(this)">Kaynak ekle</button></div>
      <div id="srcList" style="margin-top:10px">Yükleniyor…</div></div>
      <div class="card"><div class="row"><input id="kbq" placeholder="Bilgi bankasında ara…" onkeydown="if(event.key==='Enter')Views.kbSearch()"><button class="btn" onclick="Views.kbSearch()">Ara</button></div><div id="kbHits"></div></div>
      <div class="card"><h3>Belgeler (${r.docs.length})</h3><table><tr><th>Belge</th><th>Parça</th><th>Eklenme</th><th></th></tr>${r.docs.map((d) => `<tr><td>${esc(d.title)}<br><small>${esc(d.path)}</small></td><td>${d.chunks}</td><td>${fmtTime(d.added)}</td><td><button class="btn danger sm" onclick="Views.kbDel(${d.id})">Kaldır</button></td></tr>`).join("")}</table></div>`;
  },
  async embStatus() {
    const r = await API.get("/api/embeddings/status");
    const e = r.embedder;
    const el = document.getElementById("embBox"); if (!el) return;
    el.innerHTML = `<b>Anlamsal (vektör) arama:</b> ${esc(e.model)} – ${e.status === "hazır" ? '<span class="badge ok">hazır (' + esc(e.backend) + ")</span>" : '<span class="badge warn">' + esc(e.status) + "</span>"}
      · İndekslenmeyi bekleyen: ${r.pending}<br><small>Arama: anahtar kelime (FTS5) + anlamsal benzerlik (bge-m3, çok dilli) → RRF ile birleştirilir. İnternetsiz çalışır.</small><br>
      ${e.model_file ? "" : `<button class="btn sm" onclick="Views.embDl()">Anlamsal arama modelini indir (438 MB, MIT lisansı)</button> <span id="embJob"></span>`}
      ${e.status === "hazır" && r.pending ? `<button class="btn sm" onclick="Views.embIndex()">Şimdi indeksle</button>` : ""}${e.error && e.status !== "hazır" ? `<br><small>${esc(e.error)}</small>` : ""}`;
  },
  async embDl() { const r = await API.post("/api/embeddings/download"); toast("İndirme başladı."); WS.on("job", (m) => { if (m.job.id === r.job.id) { const el = document.getElementById("embJob"); if (el) el.textContent = m.job.status === "çalışıyor" ? `%${m.job.total ? Math.round(m.job.done / m.job.total * 100) : 0}` : m.job.status + (m.job.error ? ": " + m.job.error : ""); if (m.job.status === "tamamlandı") this.embStatus(); } }); },
  async embIndex() { toast("İndeksleniyor…"); try { const r = await API.post("/api/embeddings/index"); toast(r.indexed + " parça indekslendi."); this.embStatus(); } catch (e) { toast(e.message); } },
  async loadSources() {
    const el = document.getElementById("srcList"); if (!el) return;
    const r = await API.get("/api/kb/sources");
    el.innerHTML = r.sources.length ? `<table><tr><th>Kaynak</th><th>Öncelikli</th><th>Bilgi bankasında</th><th>Durum</th><th></th></tr>${r.sources.map((x) => `<tr>
      <td><b>${esc(x.title)}</b><br><a href="${esc(x.url)}" target="_blank"><small>${esc(x.url)}</small></a></td>
      <td><input type="checkbox" style="width:auto" ${x.priority ? "checked" : ""} onchange="Views.srcSet(${x.id},{priority:this.checked?1:0})"></td>
      <td>${x.indexed ? `${x.pages.length} sayfa` : "—"}</td><td><small>${esc(x.status || "")}${x.last_fetched ? "<br>" + fmtTime(x.last_fetched) : ""}</small></td>
      <td><button class="btn sec sm" onclick="Views.srcRefresh(${x.id},this)">Yenile</button> <button class="btn danger sm" onclick="Views.srcDel(${x.id})">Sil</button></td></tr>`).join("")}</table>`
      : "<small>Henüz kaynak eklenmedi.</small>";
  },
  async addSources(btn) {
    const urls = document.getElementById("srcUrls").value.trim();
    if (!urls) return toast("En az bir adres yazın.");
    btn.disabled = true; btn.textContent = "Ekleniyor… (sayfalar indiriliyor)";
    try {
      const r = await API.post("/api/kb/sources", { urls, priority: document.getElementById("srcPrio").checked,
        index: document.getElementById("srcIdx").checked, max_pages: +document.getElementById("srcPages").value });
      toast(`${r.ids.length} kaynak eklendi.` + (r.results.length ? " " + r.results.map((x) => x.status).join(" · ") : ""), 7000);
      document.getElementById("srcUrls").value = "";
    } catch (e) { toast(e.message, 6000); }
    btn.disabled = false; btn.textContent = "Kaynak ekle";
    this.kb(document.getElementById("view"));
  },
  async srcSet(id, data) { await API.put(`/api/kb/sources/${id}`, data); toast("Kaydedildi."); },
  async srcRefresh(id, btn) { btn.disabled = true; btn.textContent = "…"; const r = await API.post(`/api/kb/sources/${id}/refresh`); toast(r.status); this.loadSources(); },
  async srcDel(id) { if (!confirm("Kaynak ve bilgi bankasındaki sayfaları silinsin mi?")) return; await API.del(`/api/kb/sources/${id}`); this.kb(document.getElementById("view")); },
  async kbAdd() { try { const r = await API.post("/api/kb/add", { path: document.getElementById("kbp").value }); toast(`${r.added.length} belge eklendi${r.errors.length ? ", " + r.errors.length + " hata" : ""}.`); this.kb(document.getElementById("view")); } catch (e) { toast(e.message, 6000); } },
  async kbRefresh() { const r = await API.post("/api/kb/refresh"); toast(`${r.updated.length} belge güncellendi.`); },
  async kbSearch() { const r = await API.get("/api/kb/search?q=" + encodeURIComponent(document.getElementById("kbq").value)); document.getElementById("kbHits").innerHTML = r.hits.map((h) => `<div class="msg"><div class="who">📄 ${esc(h.title)} – bölüm ${h.chunk_no + 1} <span class="pill">${esc(h.method || "")}${h.score ? " · " + h.score : ""}</span></div>${esc(h.content.slice(0, 500))}</div>`).join("") || "<small>Sonuç yok</small>"; },
  async kbDel(id) { await API.del(`/api/kb/${id}`); this.kb(document.getElementById("view")); },
  async pick(inputId) { try { const r = await API.post("/api/system/pick-folder"); if (r.path) document.getElementById(inputId).value = r.path; } catch (e) { toast(e.message); } },

  // ---------------------------------------------------------------- Dosyalar, araçlar
  async files(el) {
    const r = await API.get("/api/files");
    el.innerHTML = `<div class="card"><h2>Dosyalarım</h2><p>Çalışma klasörü: <code>${esc(r.root)}</code></p><p><small>İzinli klasörler: ${r.allowed.map(esc).join(" · ")}</small></p>
      <table><tr><th>Dosya</th><th>Klasör</th><th>Boyut</th><th>Tarih</th><th></th></tr>${r.files.map((f) => `<tr><td>📄 ${esc(f.name)}</td><td><small>${esc(f.folder)}</small></td><td>${f.size_kb} KB</td><td><small>${fmtTime(f.mtime)}</small></td>
      <td><a class="btn sm" href="/api/files/download?path=${encodeURIComponent(f.path)}">İndir</a> <button class="btn sec sm" onclick="Views.openFile('${encQ(f.path)}',false)">Aç</button> <button class="btn sec sm" onclick="Views.openFile('${encQ(f.path)}',true)">Konumu göster</button></td></tr>`).join("") || "<tr><td colspan=5><small>Henüz dosya yok.</small></td></tr>"}</table></div>`;
  },
  async tools(el) {
    const [r, s] = await Promise.all([API.get("/api/tools"), API.get("/api/settings")]);
    const groups = {};
    r.tools.forEach((t) => (groups[t.group] ||= []).push(t));
    el.innerHTML = `<div class="card"><h2>Erişim anahtarları</h2>${this.switches(s.settings)}</div>` + Object.entries(groups).map(([g, list]) => `<div class="card"><h3>${esc(g)}</h3><table><tr><th>Araç</th><th>Yetki</th><th>Açıklama</th><th>Kullanan ajanlar</th></tr>
      ${list.map((t) => `<tr><td><b>${esc(t.label)}</b><br><code>${t.name}</code></td><td>${["", "Okuma", "Düzenleme", "İşlem"][t.level]}${t.needs_approval ? '<br><span class="badge warn">onay gerekir</span>' : ""}${t.needs_internet ? '<br><span class="badge">internet</span>' : ""}</td><td><small>${esc(t.desc)}</small></td><td><small>${t.agents.map(esc).join(", ") || "—"}</small></td></tr>`).join("")}</table></div>`).join("") +
      `<div class="card" id="compBox">Bileşenler kontrol ediliyor…</div>`;
    const c = await API.get("/api/tools/components");
    const b = (okv, t) => `<span class="badge ${okv ? "ok" : "warn"}">${okv ? "✔" : "✖"} ${t}</span>`;
    document.getElementById("compBox").innerHTML = `<h3>Bileşen durumu</h3><div class="row">${b(c.ocr, "Yerel OCR (RapidOCR)")}${b(c.data, "Veri analizi + grafik")}
      ${b(c.browser.installed && c.browser.browser, "Tarayıcı otomasyonu (Playwright/Chromium)")}${b(c.code_exec, "Kod çalıştırma (Ayarlar'dan açılır)")}${b(c.smtp, "E-posta gönderimi (SMTP)")}</div>
      ${c.browser.installed && c.browser.browser ? "" : `<p><button class="btn" onclick="Views.installBrowser(this)">Tarayıcı otomasyonunu kur (~150 MB, pakete eklenir)</button></p><pre id="brLog" class="hidden"></pre>`}
      <small>Görüntü analizi: boyut, EXIF, baskın renkler ve OCR ile yazı okuma (görsel içerik tanıma için ayrı bir görsel model gerekmez).</small>`;
  },
  async installBrowser(btn) {
    btn.disabled = true; const log = document.getElementById("brLog"); log.classList.remove("hidden"); log.textContent = "Kuruluyor… (birkaç dakika sürebilir)";
    const r = await API.post("/api/tools/install-browser"); log.textContent = r.log; toast(r.success ? "Tarayıcı otomasyonu kuruldu." : "Kurulum başarısız.");
    if (r.success) this.tools(document.getElementById("view"));
  },
  switches(s) {
    const sw = (k, label, desc) => `<label class="row between" style="padding:8px 0;border-bottom:1px solid var(--gray2)"><span><b>${label}</b><br><small>${desc}</small></span><input type="checkbox" style="width:auto;transform:scale(1.4)" ${s[k] ? "checked" : ""} onchange="Views.setSetting('${k}',this.checked)"></label>`;
    return sw("internet_enabled", "İnternet erişimi", "Kapatırsanız ajanlar web araçlarını kullanamaz; yerel çalışma devam eder.") +
      sw("files_enabled", "Dosya erişimi", "Kapatırsanız ajanlar hiçbir dosyaya erişemez.") +
      sw("agents_paused", "Ajanları duraklat", "Çalışan görevler bir sonraki adımda bekler.") +
      sw("memory_enabled", "Hafıza kullanımı", "Ajanlar geçmiş bilgileri kullanır.") +
      sw("embedding_enabled", "Anlamsal arama", "bge-m3 embedding modeli ile vektör arama (≈0.5 GB RAM).") +
      sw("code_exec_enabled", "Python kodu çalıştırma", "Yazılım/Otomasyon ajanları kod çalıştırabilir; HER çalıştırma onayınızı ister. 60 sn sınırı, görev klasöründe.") +
      `<label class="row between" style="padding:8px 0"><span><b>Keyfi shell erişimi</b><br><small>Güvenlik için kalıcı olarak kapalıdır.</small></span><input type="checkbox" disabled style="width:auto"></label>`;
  },
  async setSetting(k, v) { await API.put("/api/settings", { [k]: v }); toast("Ayar kaydedildi."); },

  // ---------------------------------------------------------------- USB, yedek, geçmiş, ayarlar
  async usb(el) {
    const r = await API.get("/api/portable");
    el.innerHTML = `<div class="grid g2"><div class="card"><h2>🔌 Taşınabilir mod</h2><div class="kv"><b>Mod</b><span>${r.portable ? '<span class="badge turq">USB / Taşınabilir</span>' : "Bilgisayar"}</span>
      <b>Konum</b><span><code>${esc(r.root)}</code></span><b>Sürücü</b><span>${esc(r.drive)} (harf değişse de çalışır – tüm yollar dinamik)</span>
      <b>Model konumu</b><span>${esc({ usb: "USB üzerinde", local: "Bilgisayarda", hybrid: "Karma" }[r.model_location])}</span>
      <b>USB'deki modeller</b><span>${r.models_on_usb.map(esc).join("<br>") || "—"}</span><b>Motorlar</b><span>Vulkan: ${r.engines.vulkan ? "✔" : "✖"} · CPU: ${r.engines.cpu ? "✔" : "✖"}</span></div>
      <button class="btn danger big" style="margin-top:14px" onclick="safeExit()">⏏ Güvenli Kapat ve Çıkar</button></div>
      <div class="card"><h2>Bu USB'nin kullanıldığı bilgisayarlar</h2><table><tr><th>Bilgisayar</th><th>Mod</th><th>Model</th><th>Son</th></tr>${r.machines.map((m) => `<tr><td>${esc(m.hostname)} ${m.current ? '<span class="badge ok">şu an</span>' : ""}</td><td>${esc(m.tier_label || "—")}</td><td>${esc(m.model_id || "—")}</td><td><small>${fmtTime(m.last_seen)}</small></td></tr>`).join("")}</table>
      <p><small>Donanıma bağlı ayarlar her bilgisayar için ayrı tutulur; ajanlar, hafıza ve projeler ortaktır.</small></p>
      <button class="btn sec" onclick="Wizard.start(true)">Bu bilgisayarı yeniden analiz et</button></div></div>
      <div class="grid g2"><div class="card"><h2>🔒 USB veri kasası (şifreleme)</h2><p>Ajanlar, hafıza, bilgi bankası, projeler, veritabanı ve ayarlar tek bir şifreli dosyada toplanır; açık kopyalar silinir.
      USB kaybolsa bile parola olmadan okunamaz. Bir sonraki açılışta parola sorulur.</p>
      <input id="vpw" type="password" placeholder="Parola (en az 6 karakter)"><input id="vpw2" type="password" placeholder="Parola (tekrar)" style="margin-top:6px">
      <label class="row" style="margin-top:6px"><input type="checkbox" id="vws" style="width:auto"> Çalışma dosyalarını da şifrele</label>
      <p class="todo">Parolayı unutursanız veriler KURTARILAMAZ.</p><button class="btn navy" onclick="Views.lockVault()">🔒 Şifrele ve kapat</button></div>
      <div class="card"><h2>🔄 Bilgisayarlar arası senkronizasyon</h2><p>Başka bir AI OFFICE klasörü (diğer USB / bilgisayardaki kopya) veya yedek dosyasıyla karşılaştırın. Çakışmalarda otomatik üzerine yazılmaz.</p>
      <div class="row"><input id="syp" placeholder="Klasör veya yedek dosyası yolu"><button class="btn sec" onclick="Views.pick('syp')">Klasör seç</button></div>
      <input id="sypw" type="password" placeholder="Şifreli yedekse parola" style="margin-top:6px"><button class="btn" style="margin-top:6px" onclick="Views.syncCompare()">Karşılaştır</button><div id="syncBox"></div></div></div>
      <div class="grid g2"><div class="card"><h2>🧠 Model dosyaları</h2><div id="mfiles">Yükleniyor…</div></div>
      <div class="card"><h2>💻 Bilgisayara kur</h2><p>Bu taşınabilir kopyayı bilgisayarınıza (%LOCALAPPDATA%\\AI_OFFICE\\app) kurar, masaüstü ve Başlat menüsü kısayolu oluşturur. Yönetici yetkisi gerekmez.
      Ajanlarınız, hafızanız ve projeleriniz de kopyalanır.</p><label class="row"><input type="checkbox" id="ilm" checked style="width:auto"> Model dosyalarını da kopyala</label>
      <button class="btn" style="margin-top:8px" onclick="Views.installLocal()">Bilgisayara kur</button><div id="ilr"></div></div></div>`;
    this.modelFiles();
  },
  async modelFiles() {
    const r = await API.get("/api/models/files");
    document.getElementById("mfiles").innerHTML = `<table><tr><th>Dosya</th><th>Konum</th><th>Boyut</th><th>Lisans</th><th></th></tr>${r.files.map((f) => `<tr><td>${esc(f.file)}</td><td>${f.location === "usb" ? "USB" : "Bilgisayar"}</td><td>${f.size_gb} GB</td><td><small>${esc(f.license)}</small></td>
      <td><button class="btn sec sm" onclick="Views.moveModel('${esc(f.file)}','${f.location}')">${f.location === "usb" ? "Bilgisayara taşı" : "USB'ye taşı"}</button> <button class="btn danger sm" onclick="Views.delModel('${esc(f.file)}','${f.location}')">Sil</button></td></tr>`).join("") || "<tr><td colspan=5><small>Model dosyası yok.</small></td></tr>"}</table>
      <small>Karma mod: küçük modeli USB'de, büyük modeli bilgisayarda tutabilirsiniz. Motor, mevcut olanı otomatik bulur.</small>`;
  },
  async moveModel(file, location) { toast("Taşınıyor… (büyük dosyalarda birkaç dakika)"); try { await API.post("/api/models/move", { file, location }); toast("Taşındı."); } catch (e) { toast(e.message); } this.modelFiles(); },
  async delModel(file, location) { if (!confirm(file + " silinsin mi?")) return; await API.post("/api/models/delete", { file, location }); this.modelFiles(); },
  async installLocal() {
    const el = document.getElementById("ilr"); el.innerHTML = '<span class="badge turq">Kopyalanıyor…</span>';
    try { const r = await API.post("/api/setup/install-local", { include_models: document.getElementById("ilm").checked }); el.innerHTML = `<p class="msg sonuc">${esc(r.note)}<br><code>${esc(r.path)}</code><br>${r.shortcuts.map(esc).join("<br>")}</p>`; }
    catch (e) { el.innerHTML = `<span class="badge err">${esc(e.message)}</span>`; }
  },
  async lockVault() {
    const a = document.getElementById("vpw").value, b = document.getElementById("vpw2").value;
    if (a !== b) return toast("Parolalar aynı değil."); if (a.length < 6) return toast("Parola en az 6 karakter olmalı.");
    if (!confirm("Veriler şifrelenecek ve program kapanacak. Parolayı unutursanız veriler kurtarılamaz. Devam?")) return;
    try { await API.post("/api/vault/lock", { password: a, include_workspace: document.getElementById("vws").checked }); } catch (e) { toast(e.message); }
  },
  async syncCompare() {
    const box = document.getElementById("syncBox"); box.innerHTML = '<span class="badge turq">Karşılaştırılıyor…</span>';
    try {
      const r = await API.post("/api/sync/compare", { path: document.getElementById("syp").value, password: document.getElementById("sypw").value });
      this._sync = r;
      const nc = r.new_counts;
      box.innerHTML = `<h3 style="margin-top:12px">Sonuç</h3><p>Yeni (sadece diğer kopyada): <b>${nc.memory}</b> hafıza, <b>${nc.tasks}</b> görev, <b>${nc.agents}</b> ajan</p>
        <label class="row"><input type="checkbox" id="syn" checked style="width:auto"> Yeni kayıtları içe aktar</label>
        <h3>Çakışmalar (${r.conflicts.length})</h3>${r.conflicts.map((c, i) => `<div class="conflict"><b>${esc(c.kind)}:</b> ${esc(c.title)} <small>(daha yeni: ${c.newer === "theirs" ? "diğer kopya" : "bu kopya"})</small>
        <div class="cols"><div><small>Bu kopya · ${esc(c.mine.date)}</small><pre>${esc(c.mine.text)}</pre></div><div><small>Diğer kopya · ${esc(c.theirs.date)}</small><pre>${esc(c.theirs.text)}</pre></div></div>
        <select data-key="${esc(c.key)}" class="sydec" style="width:auto"><option value="mine">Bu kopyayı koru</option><option value="theirs" ${c.newer === "theirs" ? "selected" : ""}>Diğer kopyayı al</option><option value="both">İki sürümü de koru</option></select></div>`).join("") || "<small>Çakışma yok.</small>"}
        <button class="btn" onclick="Views.syncApply()">Seçimleri uygula</button> <small>Uygulamadan önce otomatik yedek alınır.</small>`;
    } catch (e) { box.innerHTML = `<span class="badge err">${esc(e.message)}</span>`; }
  },
  async syncApply() {
    const decisions = {}; document.querySelectorAll(".sydec").forEach((s) => (decisions[s.dataset.key] = s.value));
    const r = await API.post("/api/sync/apply", { session: this._sync.session, decisions, import_new: document.getElementById("syn").checked });
    document.getElementById("syncBox").innerHTML = `<p class="msg sonuc">Tamamlandı: ${r.imported} yeni kayıt, ${r.theirs} diğer kopyadan alındı, ${r.both} ikisi de korundu, ${r.mine} bu kopya korundu.<br>Güvenlik yedeği: ${esc(r.safety_backup)}</p>`;
    await App.loadAgents();
  },
  async backup(el) {
    const r = await API.get("/api/backups");
    const names = { agents: "Ajanlar", memory: "Hafıza + bilgi bankası", projects: "Projeler", settings: "Ayarlar", database: "Veritabanı", workspace: "Çalışma dosyaları" };
    el.innerHTML = `<div class="card"><h2>💾 Tek tıkla yedekle</h2><div class="row">${r.parts.map((p) => `<label class="pill"><input type="checkbox" class="bk" value="${p}" style="width:auto" ${p !== "workspace" ? "checked" : ""}> ${names[p]}</label>`).join("")}</div>
      <div class="row" style="margin-top:10px"><input id="bkpw" type="password" placeholder="Parola (boş bırakırsanız şifresiz ZIP)" style="max-width:320px"><button class="btn" onclick="Views.doBackup()">Yedekle</button></div>
      <small>Şifreli yedek: AES (Fernet) + PBKDF2 (390.000 tur). USB kaybolursa verileriniz parola olmadan açılamaz. Parolayı unutursanız yedek kurtarılamaz.</small></div>
      <div class="card"><h3>Yedekler</h3><table><tr><th>Ad</th><th>Boyut</th><th>Tarih</th><th></th></tr>${r.items.map((b) => `<tr><td>${b.encrypted ? "🔒" : "📦"} ${esc(b.name)}</td><td>${b.size_mb} MB</td><td>${b.date}</td><td><button class="btn sec sm" onclick="Views.restore('${b.name}',${b.encrypted})">Geri yükle</button></td></tr>`).join("") || "<tr><td colspan=4><small>Yedek yok.</small></td></tr>"}</table></div>`;
  },
  async doBackup() { const parts = [...document.querySelectorAll(".bk:checked")].map((c) => c.value); const r = await API.post("/api/backups", { parts, password: document.getElementById("bkpw").value }); toast("Yedek oluşturuldu: " + r.name); this.backup(document.getElementById("view")); },
  async restore(name, enc) {
    if (!confirm("Geri yükleme mevcut verilerin üzerine yazar (önce otomatik güvenlik yedeği alınır). Devam?")) return;
    const password = enc ? prompt("Yedek parolası:") || "" : "";
    try { const r = await API.post("/api/backups/restore", { name, password }); toast(`${r.restored_files} dosya geri yüklendi. Güvenlik yedeği: ${r.safety_backup}`, 6000); setTimeout(() => location.reload(), 1500); } catch (e) { toast(e.message, 6000); }
  },
  async audit(el) {
    const r = await API.get("/api/audit");
    el.innerHTML = `<div class="card"><h2>İşlem Geçmişi</h2><p class="muted">Hangi ajanın hangi işlemi yaptığı kaydedilir. Hassas içerikler kaydedilmez.</p><table><tr><th>Zaman</th><th>Ajan</th><th>İşlem</th><th>Hedef</th><th>Sonuç</th></tr>
      ${r.items.map((i) => `<tr><td><small>${fmtTime(i.ts)}</small></td><td>${App.agent(i.agent).avatar} ${esc(App.agent(i.agent).title)}</td><td><code>${esc(i.action)}</code></td><td><small>${esc(i.target)}</small></td><td><small>${esc(i.result)}</small></td></tr>`).join("") || "<tr><td colspan=5><small>Kayıt yok</small></td></tr>"}</table></div>`;
  },
  async settings(el) {
    const [s, m] = await Promise.all([API.get("/api/settings"), API.get("/api/models")]);
    const st = s.settings;
    el.innerHTML = `<div class="grid g2"><div class="card"><h2>İzinli klasörler</h2><p><small>Ajanlar yalnızca çalışma klasörüne ve burada izin verdiğiniz klasörlere erişebilir.</small></p>
      ${st.allowed_folders.map((f) => `<div class="row between"><code>${esc(f)}</code><button class="btn danger sm" onclick="Views.rmFolder('${encQ(f)}')">Kaldır</button></div>`).join("") || "<small>Ek klasör yok.</small>"}
      <div class="row" style="margin-top:8px"><input id="fold" placeholder="Örn: C:\\Users\\Ad\\Documents"><button class="btn sec" onclick="Views.pick('fold')">Seç</button><button class="btn" onclick="Views.addFolder()">İzin ver</button></div></div>
      <div class="card"><h2>AI motoru ve model</h2><p>Önerilen: <b>${esc(m.recommendation.model_id)}</b> (${esc(m.recommendation.tier_label)})</p>
      <label>Kullanılacak model</label><select id="mdl">${m.models.map((x) => `<option value="${x.id}" ${x.installed ? "" : "disabled"}>${esc(x.name)} ${x.installed ? "" : "(yüklü değil)"}${x.recommended ? " ★" : ""}</option>`).join("")}</select>
      <div class="row" style="margin-top:8px"><button class="btn" onclick="Views.selModel()">Bu modelle yeniden başlat</button><button class="btn sec" onclick="API.post('/api/engine/start').then(r=>toast(r.started?'Motor hazır':'Hata: '+r.engine.error,6000))">Motoru başlat</button><button class="btn sec" onclick="API.post('/api/engine/stop')">Durdur</button><button class="btn sec" onclick="Wizard.start(true)">Model indir / kurulum</button></div>
      <label style="margin-top:10px;display:block">Motor tercihi</label><select onchange="Views.setSetting('engine_preference',this.value)">${["auto", "llamacpp", "ollama"].map((v) => `<option ${st.engine_preference === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="card"><h2>Ajan sınırları (döngü koruması)</h2>${[["max_steps", "En fazla plan adımı"], ["max_tool_iters", "Adım başı en fazla araç kullanımı"], ["max_messages_per_task", "Görev başı en fazla mesaj"]].map(([k, l]) => `<label>${l}</label><input type="number" value="${st[k]}" onchange="Views.setSetting('${k}',+this.value)">`).join("")}</div>
      <div class="card"><h2>Güvenlik</h2>${this.switches(st)}</div>
      <div class="card"><h2>Performans</h2><label>Aynı anda çalışan görev sayısı</label><select onchange="Views.setSetting('max_parallel_tasks',+this.value)">${[1, 2, 3].map((n) => `<option ${st.max_parallel_tasks === n ? "selected" : ""}>${n}</option>`).join("")}</select>
      <small>Düşük donanımda 1 önerilir; fazlası sıraya alınır. Model çağrıları her durumda tek kuyruktan geçer.</small></div>
      <div class="card"><h2>E-posta (SMTP)</h2><small>E-posta Uzmanı taslakları her zaman .eml olarak kaydeder. Gönderim için SMTP gerekir ve her gönderim onayınızı ister. Parola yalnızca bu klasördeki ayar dosyasında tutulur (kasa şifrelemesiyle korunabilir), günlük dosyalarına yazılmaz.</small>
      ${["host", "port", "user", "password", "from"].map((k) => `<label>${{ host: "Sunucu (ör. smtp.gmail.com)", port: "Port (587)", user: "Kullanıcı", password: "Parola / uygulama şifresi", from: "Gönderen adresi" }[k]}</label><input id="smtp_${k}" ${k === "password" ? 'type="password"' : ""} value="${esc((st.smtp || {})[k] || "")}">`).join("")}
      <button class="btn" style="margin-top:8px" onclick="Views.saveSmtp()">Kaydet</button></div></div>`;
  },
  async saveSmtp() { const smtp = {}; ["host", "port", "user", "password", "from"].forEach((k) => (smtp[k] = document.getElementById("smtp_" + k).value)); await API.put("/api/settings", { smtp }); toast("SMTP ayarları kaydedildi."); },
  async addFolder() { try { await API.post("/api/settings/folders", { path: document.getElementById("fold").value }); this.settings(document.getElementById("view")); } catch (e) { toast(e.message); } },
  async rmFolder(enc) { await API.post("/api/settings/folders/remove", { path: decodeURIComponent(enc) }); this.settings(document.getElementById("view")); },
  async selModel() { toast("Model yükleniyor…"); const r = await API.post("/api/models/select", { model_id: document.getElementById("mdl").value }); toast(r.started ? "Model hazır." : "Hata: " + r.engine.error, 6000); },
};
