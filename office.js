// Aşama 3: Hareketli sanal ofis kat planı.
// Ajanların konumu GERÇEK durum olaylarına bağlıdır: zone=meeting → toplantı odasına yürür,
// "Başka ajanla görüşüyor" → görüştüğü ajanın masasına gider, iş bitince masasına döner.
const ROOMS = [
  ["Genel Müdürlük", 0, 0], ["Araştırma", 1, 0], ["Akademik Çalışmalar", 2, 0],
  ["Veri Analizi", 0, 1], ["Toplantı Odası", 1, 1], ["Yazılım", 2, 1],
  ["Belge ve Raporlama", 0, 2], ["Finans", 1, 2], ["Ortak Çalışma Alanı", 2, 2],
];
const ROOM_ICON = { "Genel Müdürlük": "🏛️", "Araştırma": "🔬", "Akademik Çalışmalar": "🎓", "Veri Analizi": "📊", "Toplantı Odası": "🤝",
  "Yazılım": "💻", "Belge ve Raporlama": "📝", "Finans": "💹", "Ortak Çalışma Alanı": "☕" };
const W = 100 / 3, H = 100 / 3;

const Office = {
  homes: {},
  room(name) { return ROOMS.find((r) => r[0] === name) || ROOMS[8]; },
  computeHomes(hired) {
    this.homes = {};
    const byDept = {};
    hired.forEach((a) => (byDept[this.room(a.department)[0]] ||= []).push(a));
    Object.entries(byDept).forEach(([dept, list]) => {
      const [, cx, cy] = this.room(dept);
      const cols = 3, rows = Math.ceil(list.length / cols);
      const stepY = rows > 2 ? 8.5 : 12;
      list.forEach((a, i) => {
        this.homes[a.id] = { left: cx * W + 5 + (i % cols) * 9.6, top: cy * H + 7 + Math.floor(i / cols) * stepY };
      });
    });
  },
  meetingSeat(id, hired) {
    const inMeeting = hired.filter((a) => (App.states[a.id] || {}).zone === "meeting");
    const i = Math.max(0, inMeeting.findIndex((a) => a.id === id));
    const n = Math.max(inMeeting.length, 1);
    const ang = (i / n) * Math.PI * 2 - Math.PI / 2;
    return { left: W + W / 2 - 3.2 + Math.cos(ang) * 11, top: H + H / 2 - 4.5 + Math.sin(ang) * 10 };
  },
  pos(a, hired) {
    const st = App.states[a.id] || {};
    if (st.zone === "meeting") return this.meetingSeat(a.id, hired);
    if (st.with && st.status === "Başka ajanla görüşüyor" && this.homes[st.with]) {
      const h = this.homes[st.with];
      // iki ajandan "soran" karşı tarafın masasına yürür; cevaplayan masasında kalır
      if (st.bubble && !/yanıtlıyorum/i.test(st.bubble)) return { left: h.left + 5.5, top: h.top + 1.5 };
    }
    return this.homes[a.id] || { left: 2, top: 2 };
  },
  walkerHtml(a, p) {
    const st = App.states[a.id] || { status: "Müsait" };
    const working = WORKING.includes(st.status);
    const bubble = st.bubble && st.status !== "Müsait" ? `<div class="bubble">${esc(st.bubble)}</div>` : "";
    return `<div class="walker ${working ? "working" : ""}" id="w-${a.id}" style="left:${p.left}%;top:${p.top}%" onclick="App.openAgent('${a.id}')" title="${esc(a.title)}">
      ${bubble}<div class="av" style="border-color:${a.color}">${a.avatar}</div><div class="nm">${esc(a.name.split(" ")[0])}</div>${Views.statusPill(st.status)}</div>`;
  },
  html(height = 720) {
    const hired = App.agents.filter((a) => a.hired);
    this.computeHomes(hired);
    const rooms = ROOMS.map(([n, x, y]) => `<div class="room ${n === "Toplantı Odası" ? "meeting" : ""}" style="left:${x * W}%;top:${y * H}%;width:${W}%;height:${H}%">
      <span class="rname">${ROOM_ICON[n]} ${esc(n)}</span>${n === "Toplantı Odası" ? '<div class="mtable"></div>' : ""}</div>`).join("");
    const desks = hired.map((a) => { const h = this.homes[a.id]; return `<div class="desk2" style="left:${h.left - 0.2}%;top:${h.top + 3.4}%"><i></i></div>`; }).join("");
    const walkers = hired.map((a) => this.walkerHtml(a, this.pos(a, hired))).join("");
    return `<div class="floor" id="floor" style="height:${height}px">${rooms}${desks}${walkers}</div>`;
  },
  update(id) {
    const floor = document.getElementById("floor");
    if (!floor) return;
    const hired = App.agents.filter((a) => a.hired);
    const ids = (App.states[id] || {}).zone === "meeting" || document.querySelector(".walker.inmeet") ? hired.map((a) => a.id) : [id];
    ids.forEach((aid) => {
      const a = hired.find((x) => x.id === aid);
      const el = document.getElementById("w-" + aid);
      if (!a || !el) return;
      const p = this.pos(a, hired);
      const fresh = document.createElement("div");
      fresh.innerHTML = this.walkerHtml(a, p);
      const nw = fresh.firstElementChild;
      el.className = nw.className + ((App.states[aid] || {}).zone === "meeting" ? " inmeet" : "");
      el.innerHTML = nw.innerHTML;
      el.style.left = p.left + "%";   // CSS geçişi ile yürüme animasyonu
      el.style.top = p.top + "%";
    });
  },
};
