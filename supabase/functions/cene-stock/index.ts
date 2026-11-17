// cene.babl.cc · "Where is it in stock?" – for signed-in babl users only.
// POST {store, url, name}  →  {stores: [{chain, label, city, address, lat, lng, qty, approx}], note}
// Gigatron: the shop's own per-store availability API (with coordinates).
// WinWin: the store list on the product page. (Tehnomedia's site refuses server requests – not offered.)
// Stores without coordinates in the answer are placed with the store table cene_store_geo (from the shops' store pages).
import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const ORIGINS = ["https://cene.babl.cc", "http://localhost:8000"];
const UA = "Mozilla/5.0 (compatible; cene.babl.cc stock check; +https://cene.babl.cc)";
const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });

const cors = (req: Request) => {
  const o = req.headers.get("origin") || "";
  return {
    "Access-Control-Allow-Origin": ORIGINS.includes(o) ? o : ORIGINS[0],
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
};
const json = (req: Request, body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors(req), "Content-Type": "application/json" } });

const get = async (url: string) => {
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept-Language": "sr,en;q=0.8" } });
  if (!r.ok) throw new Error(`${new URL(url).host} answered ${r.status}`);
  return await r.text();
};
const txt = (s: string) => s.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#0?39;|&apos;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();

type Store = { chain: string; label: string; city: string; address: string; lat: number | null; lng: number | null; qty: number | null; approx?: boolean; hours?: string; phone?: string };

// ---------------------------------------------------------------- shops
async function gigatron(url: string): Promise<Store[]> {
  const sku = (new URL(url).pathname.match(/-(\d{5,})$/) || [])[1];
  if (!sku) throw new Error("no product code in the link");
  const j = JSON.parse(await get(`https://gigatron.rs/api/vtex/sku-available-stores?sku=${sku}`));
  return (j.items || []).filter((x: any) => x.isAvailable && x.isActive !== false).map((x: any) => {
    let phone = ""; try { phone = JSON.parse(x.instructions || "{}").phoneNumber || ""; } catch (_) { /* */ }
    const a = x.address || {};
    return { chain: "Gigatron", label: x.name, city: a.city || "", address: [a.street, a.complement].filter(Boolean).join(", ").trim(),
             lat: a.location?.latitude ?? null, lng: a.location?.longitude ?? null, qty: null, phone };
  });
}

async function winwin(url: string): Promise<Store[]> {
  const page = await get(url);
  const box = (page.match(/class="store_wrap">([\s\S]*?)<\/div>/) || [])[1] || "";
  return [...box.matchAll(/<a[^>]*>([\s\S]*?)<\/a>/g)].map((m) => {
    const t = txt(m[1]); const i = t.indexOf(" - ");
    const city = i > 0 ? t.slice(0, i) : ""; const address = i > 0 ? t.slice(i + 3) : t;
    return { chain: "WinWin", label: t, city, address, lat: null, lng: null, qty: null };
  });
}

const SHOPS: Record<string, { host: RegExp; fn: (u: string) => Promise<Store[]> }> = {
  Gigatron: { host: /(^|\.)gigatron\.rs$/, fn: gigatron },
  WinWin: { host: /(^|\.)winwin\.rs$/, fn: winwin },
};

// ---------------------------------------------------------------- coordinates for shops that give only an address
// cene_store_geo holds every WinWin store with coordinates (from the shop's own store page).
const norm = (x: string) => x.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/\bbr\.?\b/g, " ").replace(/[^a-z0-9]+/g, "");
const words = (x: string) => x.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/\(.*?\)/g, " ").split(/[^a-z0-9]+/).filter((w) => w.length >= 3 || /^\d+[a-z]?$/.test(w));
async function locate(stores: Store[]) {
  const need = stores.filter((s) => s.lat == null);
  if (!need.length) return;
  const chains = [...new Set(need.map((s) => s.chain))];
  const { data } = await admin.from("cene_store_geo").select("chain,label,city,address,lat,lng,src").in("chain", chains);
  const rows = (data || []) as any[];
  const byLabel = new Map(rows.map((r) => [r.chain + "|" + norm(r.label), r]));
  for (const s of need) {
    let r = byLabel.get(s.chain + "|" + norm(s.label));
    if (!r) {   // same city, best overlap of street words and house number
      const w = new Set(words(s.address)); let best = 0;
      for (const c of rows) {
        if (c.chain !== s.chain || norm(c.city || "") !== norm(s.city)) continue;
        const sc = words(c.address || c.label).filter((x) => w.has(x)).length;
        if (sc > best) { best = sc; r = c; }
      }
      if (best < 1) r = undefined;
    }
    if (r) { s.lat = r.lat; s.lng = r.lng; s.approx = r.src === "city"; continue; }
    const sameCity = rows.find((c) => norm(c.city || "") === norm(s.city));
    if (sameCity) { s.lat = sameCity.lat; s.lng = sameCity.lng; s.approx = true; }
  }
}

// ---------------------------------------------------------------- handler
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors(req) });
  if (req.method !== "POST") return json(req, { error: "POST only" }, 405);
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  const { data: u } = token ? await admin.auth.getUser(token) : { data: { user: null } };
  if (!u?.user) return json(req, { error: "login" }, 401);
  let body: any = {};
  try { body = await req.json(); } catch (_) { /* */ }
  const shop = SHOPS[body.store];
  if (!shop) return json(req, { error: "unsupported", supported: Object.keys(SHOPS) }, 400);
  let url: URL;
  try { url = new URL(body.url); } catch (_) { return json(req, { error: "bad url" }, 400); }
  if (!shop.host.test(url.hostname)) return json(req, { error: "bad url" }, 400);
  try {
    const stores = await shop.fn(url.href);
    await locate(stores);
    return json(req, { store: body.store, checked: new Date().toISOString(), stores });
  } catch (e) {
    return json(req, { error: "shop", detail: String((e as Error).message || e).slice(0, 200) }, 502);
  }
});
