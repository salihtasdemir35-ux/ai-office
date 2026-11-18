// API ve WebSocket yardımcıları
const API = {
  async req(method, url, body) {
    const opt = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opt.body = JSON.stringify(body);
    const r = await fetch(url, opt);
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`);
    return data;
  },
  get(u) { return this.req("GET", u); },
  post(u, b = {}) { return this.req("POST", u, b); },
  put(u, b = {}) { return this.req("PUT", u, b); },
  del(u) { return this.req("DELETE", u); },
};

const WS = {
  handlers: {},
  on(type, fn) { (this.handlers[type] ||= []).push(fn); },
  connect() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      (this.handlers[msg.type] || []).forEach((fn) => { try { fn(msg); } catch (err) { console.error(err); } });
      (this.handlers["*"] || []).forEach((fn) => fn(msg));
    };
    ws.onclose = () => { if (!window.__exiting) setTimeout(() => this.connect(), 2000); };
    this.ws = ws;
  },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(text, ms = 3500) {
  const d = document.createElement("div");
  d.textContent = text;
  document.getElementById("toast").appendChild(d);
  setTimeout(() => d.remove(), ms);
}
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function fmtBytes(b) { return b > 1073741824 ? (b / 1073741824).toFixed(2) + " GB" : (b / 1048576).toFixed(1) + " MB"; }
const TASK_STATUS = {
  plan_hazirlaniyor: ["Plan hazırlanıyor", "turq"], onay_bekliyor: ["Onay bekliyor", "warn"],
  calisiyor: ["Çalışıyor", "turq"], tamamlandi: ["Tamamlandı", "ok"], hata: ["Hata", "err"],
  iptal: ["İptal edildi", ""], durduruldu: ["Durduruldu", "warn"], sirada: ["Sırada", "queue"],
};
function taskBadge(s) { const [t, c] = TASK_STATUS[s] || [s, ""]; return `<span class="badge ${c}">${esc(t)}</span>`; }
function encQ(s) { return encodeURIComponent(s).replace(/'/g, "%27"); }
