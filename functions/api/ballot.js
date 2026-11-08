// Said & Done: the readers' ballot. Verified reader-checkers choose which bill opens next (speculum/saiddone.py).
// A voter must (1) be signed in through Cloudflare Access on early.speculum.vote, proven by checking the Access
// token's signature, and (2) be an approved reader on their sign-up record. Votes are kept in the private SIGNUPS
// store, one per reader per round (a new vote replaces the old), and counted by the nightly run after the round
// closes; only the totals are published. The round and its shortlist come from the built site's ballot.json.
const HOST = 'early.speculum.vote';
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

async function hex(s, n) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].slice(0, n).map(b => b.toString(16).padStart(2, '0')).join('');
}
function b64url(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}
const text = s => new TextDecoder().decode(b64url(s));
function cookie(request, name) {
  const m = (request.headers.get('cookie') || '').match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
  return m ? m[1] : null;
}
function todayEastern() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

// The Access application's audience tag, read once a day from Cloudflare (needs CF_ACCESS_TOKEN, as approvals do).
async function appAud(env) {
  const cached = await env.SIGNUPS.get('cfg:access-aud');
  if (cached) return cached;
  const token = String(env.CF_ACCESS_TOKEN || '').trim(), account = String(env.CF_ACCOUNT_ID || '').trim();
  if (!token || !account) return null;
  const r = await fetch(`https://api.cloudflare.com/client/v4/accounts/${account}/access/apps`, { headers: { authorization: `Bearer ${token}` } });
  const j = await r.json().catch(() => ({}));
  const app = (j.result || []).find(a => [a.domain, ...(a.self_hosted_domains || [])].some(d => String(d || '').split('/')[0] === HOST));
  if (!app || !app.aud) return null;
  await env.SIGNUPS.put('cfg:access-aud', app.aud, { expirationTtl: 86400 });
  return app.aud;
}

// The signed-in reader's email, or a reason they cannot vote.
async function reader(request, env) {
  if (new URL(request.url).hostname !== HOST) return { why: "Voting is open to verified reader-checkers on the readers' site." };
  const jwt = request.headers.get('Cf-Access-Jwt-Assertion') || cookie(request, 'CF_Authorization');
  const parts = (jwt || '').split('.');
  if (parts.length !== 3) return { why: "Sign in to the readers' site to vote." };
  let header, claims;
  try { header = JSON.parse(text(parts[0])); claims = JSON.parse(text(parts[1])); } catch { return { why: 'Your sign-in could not be read. Reload the page.' }; }
  if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(String(claims.iss || ''))) return { why: 'Your sign-in could not be checked.' };
  if (!claims.exp || claims.exp * 1000 < Date.now()) return { why: 'Your sign-in has expired. Reload the page.' };
  const aud = await appAud(env);
  if (!aud) return { why: 'The ballot is not set up yet.' };
  if (!(Array.isArray(claims.aud) ? claims.aud : [claims.aud]).includes(aud)) return { why: 'Your sign-in could not be checked.' };
  const certs = await (await fetch(`${claims.iss}/cdn-cgi/access/certs`, { cf: { cacheTtl: 3600 } })).json().catch(() => ({}));
  const jwk = (certs.keys || []).find(k => k.kid === header.kid);
  if (!jwk) return { why: 'Your sign-in could not be checked.' };
  const key = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: 'RS256', ext: true },
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!ok) return { why: 'Your sign-in could not be checked.' };
  const email = String(claims.email || '').trim().toLowerCase();
  if (!email) return { why: 'Your sign-in has no email address.' };
  const id = await hex(email, 16);
  const rec = JSON.parse((await env.SIGNUPS.get(`s:${id}`)) || 'null');
  if (!rec || !rec.approved) return { why: 'Voting is open to approved reader-checkers. Your account is not approved yet.' };
  return { id };
}

async function round(request, env) {
  const r = await env.ASSETS.fetch(new URL('/saiddone/ballot.json', request.url));
  const b = r.ok ? await r.json().catch(() => null) : null;
  if (!b || !b.round || !(b.candidates || []).length) return { why: 'No round is open.' };
  if (todayEastern() > b.closes) return { why: 'This round has closed. The next one opens tomorrow morning.' };
  return b;
}

async function handle(request, env, post) {
  if (!env.SIGNUPS) return json({ eligible: false, message: 'The ballot is not open yet.' });
  const rd = await round(request, env);
  if (rd.why) return json({ eligible: false, message: rd.why });
  const who = await reader(request, env);
  if (who.why) return json({ eligible: false, message: who.why });
  const key = `b:${rd.round}:${who.id}`;
  if (!post) return json({ eligible: true, round: rd.round, closes: rd.closes, mine: await env.SIGNUPS.get(key) });
  let b;
  try { b = await request.json(); } catch { return json({ error: 'Bad request.' }, 400); }
  const slug = String(b.slug || '');
  if (!rd.candidates.includes(slug)) return json({ error: 'That bill is not on this round’s ballot.' }, 400);
  const rk = `ballotrate:${todayEastern()}:${who.id}`;
  const n = parseInt((await env.SIGNUPS.get(rk)) || '0', 10);
  if (n >= 20) return json({ error: 'Too many changes today. Please try tomorrow.' }, 429);
  await env.SIGNUPS.put(rk, String(n + 1), { expirationTtl: 172800 });
  await env.SIGNUPS.put(key, slug, { expirationTtl: 60 * 86400 });
  return json({ ok: true, mine: slug });
}

export async function onRequest({ request, env }) {
  try {
    if (request.method === 'GET') return await handle(request, env, false);
    if (request.method === 'POST') return await handle(request, env, true);
    return json({ error: 'Use GET or POST.' }, 405);
  } catch (e) {
    return json({ eligible: false, error: 'Server error.', message: 'The ballot had a problem. Please try again later.' }, 422);
  }
}
