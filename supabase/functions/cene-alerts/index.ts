// cene.babl.cc · price-drop e-mails – data side (the GitHub morning run compares prices and sends the e-mails).
// Caller proves itself with the price-watch project's service key (checked against that project), so no extra secret is needed.
//   POST {action:"list"}                         → {users:[{user_id,email,lang,alerts,weekly,items:[{id,store,name,url,ref}]}]}
//   POST {action:"mark", updates:[{user_id,id,price}]} → {ok:n}
//   POST {action:"stats", day:"YYYY-MM-DD"}      → {total,new_day,active_day,cene_users,alerts,weekly,users:[{email,created,last,provider,saved,alerts,weekly}]}
import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const CENE = "https://hxtdrtsqigvuvhaszxna.supabase.co";
const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

async function isCeneService(key: string) {
  if (!key || key.length < 20) return false;
  const h: Record<string, string> = { apikey: key };
  if (key.startsWith("eyJ")) h.Authorization = "Bearer " + key;
  const r = await fetch(`${CENE}/rest/v1/runs?select=id&limit=1`, { headers: h });   // rows only come back for the service role
  if (!r.ok) return false;
  const j = await r.json().catch(() => []);
  return Array.isArray(j) && j.length > 0;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  const key = (req.headers.get("x-cene-key") || "").trim();
  if (!(await isCeneService(key))) return json({ error: "forbidden" }, 403);
  const body = await req.json().catch(() => ({}));

  if (body.action === "list") {
    const { data: prefs } = await admin.from("cene_prefs").select("user_id,lang,price_alerts,weekly").or("price_alerts.eq.true,weekly.eq.true");
    if (!prefs?.length) return json({ users: [] });
    const ids = prefs.map((p) => p.user_id);
    const { data: saved } = await admin.from("cene_saved").select("user_id,id,store,name,url,price_saved,alert_price").in("user_id", ids);
    const users = [];
    for (const p of prefs) {
      const items = !p.price_alerts ? [] : (saved || []).filter((s) => s.user_id === p.user_id)
        .map((s) => ({ id: s.id, store: s.store, name: s.name, url: s.url, ref: s.alert_price ?? s.price_saved }));
      if (!items.length && !p.weekly) continue;
      const { data: u } = await admin.auth.admin.getUserById(p.user_id);
      if (!u?.user?.email) continue;
      users.push({ user_id: p.user_id, email: u.user.email, lang: p.lang || "sr", alerts: !!p.price_alerts, weekly: !!p.weekly, items });
    }
    return json({ users });
  }

  if (body.action === "mark") {
    let n = 0;
    for (const u of (body.updates || []).slice(0, 2000)) {
      if (!u.user_id || !u.id || !Number.isFinite(+u.price)) continue;
      const { error } = await admin.from("cene_saved").update({ alert_price: Math.round(+u.price), alerted_at: new Date().toISOString() })
        .eq("user_id", u.user_id).eq("id", String(u.id));
      if (!error) n++;
    }
    return json({ ok: n });
  }
  if (body.action === "stats") {
    const day = /^\d{4}-\d{2}-\d{2}$/.test(body.day || "") ? body.day : new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    const all: any[] = [];
    for (let page = 1; page < 50; page++) {
      const { data, error } = await admin.auth.admin.listUsers({ page, perPage: 1000 });
      if (error || !data?.users?.length) break;
      all.push(...data.users);
      if (data.users.length < 1000) break;
    }
    const { data: saved } = await admin.from("cene_saved").select("user_id");
    const { data: prefs } = await admin.from("cene_prefs").select("user_id,price_alerts,weekly");
    const sc: Record<string, number> = {};
    for (const s of saved || []) sc[s.user_id] = (sc[s.user_id] || 0) + 1;
    const pf: Record<string, any> = {};
    for (const p of prefs || []) pf[p.user_id] = p;
    const d = (x?: string | null) => (x || "").slice(0, 10);
    const users = all.map((u) => ({ email: u.email || "", created: d(u.created_at), last: d(u.last_sign_in_at),
      provider: u.app_metadata?.provider || "", saved: sc[u.id] || 0, alerts: !!pf[u.id]?.price_alerts, weekly: !!pf[u.id]?.weekly, cene: !!(sc[u.id] || pf[u.id]) }))
      .sort((a, b) => (b.last || "").localeCompare(a.last || ""));
    return json({ day, total: users.length, new_day: users.filter((u) => u.created === day).length,
      active_day: users.filter((u) => u.last === day).length, cene_users: users.filter((u) => u.cene).length,
      alerts: users.filter((u) => u.alerts).length, weekly: users.filter((u) => u.weekly).length, users: users.slice(0, 200) });
  }
  return json({ error: "unknown action" }, 400);
});
