"use strict";

// ── Helpers ──────────────────────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function toast(msg, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

async function busy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    return await fn();
  } catch (e) {
    toast(e.message, 5000);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

const iso = (d) => d.toISOString().slice(0, 10);
const parseDay = (s) => new Date(s + "T12:00:00");
const fmtDay = (s, o = { month: "short", day: "numeric" }) => parseDay(s).toLocaleDateString(undefined, o);
function fmtTime(hhmm) {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
function mondayOf(d) {
  const x = new Date(d);
  x.setHours(12, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
const todayIso = () => iso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
const ICONS = { deal: "🏷️", taste: "★", cook: "👩‍🍳", time: "⏱", note: "📝", leftovers: "🥡", new: "✨", variety: "🔀" };

// ── State ────────────────────────────────────────────────────────────────────
const state = { week: null, start: null, recipes: [], deals: [] };

// ── Tabs ─────────────────────────────────────────────────────────────────────
function showTab(name) {
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
  try { localStorage.setItem("tab", name); } catch {}
  if (name === "recipes") loadRecipes();
  if (name === "deals") loadDeals();
  if (name === "taste") loadTaste();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ── Week ─────────────────────────────────────────────────────────────────────
async function loadWeek(start) {
  $("#days").innerHTML = Array.from({ length: 7 }, () => '<div class="skeleton"></div>').join("");
  const q = start ? `?start=${start}` : "";
  state.week = await api(`/api/week${q}`);
  state.start = state.week.week_start;
  renderWeek();
  loadRateBanner();
}

function renderWeek() {
  const w = state.week;
  $("#week-label").textContent = `${fmtDay(w.week_start, { month: "long", day: "numeric" })} – ${fmtDay(w.week_end, { month: "long", day: "numeric" })}`;
  $("#plan-week").textContent = w.planned ? "Re-plan week" : "Plan this week";

  const sh = w.shopping;
  const cooks = w.cooks.map((c) => `${esc(c.name)} ×${c.nights}`).join(" · ") || "—";
  $("#stats").innerHTML = w.planned
    ? `
    <div class="stat"><b>${w.meals.filter((m) => m.kind === "cook").length}</b><span>dinners to cook</span></div>
    <div class="stat"><b>${sh.count}</b><span>things to buy</span></div>
    <div class="stat good"><b>${sh.on_sale}</b><span>on sale this week</span></div>
    <div class="stat good"><b>${sh.estimated_savings ? "$" + sh.estimated_savings.toFixed(2) : "—"}</b><span>known savings</span></div>
    <div class="stat"><b style="font-size:1rem">${cooks}</b><span>who's cooking</span></div>
    <div class="stat"><b style="font-size:1rem">${w.deals.count} deals</b><span>${w.deals.last_checked ? "checked " + esc(w.deals.last_checked.slice(0, 16)) : "not checked yet"}</span></div>`
    : "";

  if (!w.planned) {
    $("#days").innerHTML = `
      <div class="empty" style="grid-column:1/-1">
        <h2>No plan for this week yet</h2>
        <p>The planner checks everyone's calendar, this week's deals at your stores and what you've liked, then picks seven dinners.</p>
        <button class="primary" onclick="document.getElementById('plan-week').click()">Plan it</button>
      </div>`;
    $("#shopping-body").innerHTML = '<p class="muted">The list appears once the week is planned.</p>';
    return;
  }

  const today = w.today || todayIso();
  $("#days").innerHTML = w.meals.map((m) => dayCard(m, today)).join("");
  renderShopping();
}

function dayCard(m, today) {
  const r = m.recipe;
  const cls = ["day", m.kind, m.day === today ? "today" : "", m.day < today ? "past" : ""].join(" ");
  let title;
  if (m.kind === "skip") title = `<span class="meal-name">Night off</span>`;
  else if (m.kind === "leftovers") title = `<button class="meal-name" data-recipe="${r?.id}">Leftovers: ${esc(r?.name)}</button>`;
  else title = `<button class="meal-name" data-recipe="${r.id}">${esc(r.name)}</button>`;

  const meta = [];
  if (m.cook) meta.push(`<span class="pill cook">👩‍🍳 ${esc(m.cook)}</span>`);
  if (r && m.kind === "cook") meta.push(`<span>⏱ ${r.total_minutes} min</span>`);
  if (m.start_by && m.kind === "cook") meta.push(`<span>start by ${fmtTime(m.start_by)}</span>`);
  if (r?.rating) meta.push(`<span>★ ${r.rating.toFixed(1)}</span>`);

  const reasons = m.reasons
    .map((x) => `<li class="reason ${esc(x.kind)}"><span>${ICONS[x.kind] || "•"}</span><span>${esc(x.text)}</span></li>`)
    .join("");

  const actions =
    m.kind === "skip"
      ? `<button data-swap="${m.day}">Plan a dinner</button>`
      : `<button data-swap="${m.day}" title="Pick the next best option">↻ Swap</button>
         <button data-choose="${m.day}" title="Choose the recipe yourself">Choose…</button>
         <button data-lock="${m.day}" class="${m.locked ? "on" : ""}" title="Keep this when re-planning">${m.locked ? "🔒 Kept" : "Keep"}</button>
         ${m.day <= today && r && m.kind === "cook" ? `<button data-rate="${r.id}" data-day="${m.day}">Rate</button>` : ""}`;

  return `
    <article class="${cls}">
      <div class="day-head">
        <div><span class="day-name">${esc(m.weekday)}</span>${m.day === today ? '<span class="badge-today">Tonight</span>' : ""}</div>
        <span class="day-date">${fmtDay(m.day)}</span>
      </div>
      ${title}
      <div class="meta">${meta.join("")}</div>
      <ul class="reasons">${reasons}</ul>
      <div class="day-actions">${actions}</div>
    </article>`;
}

function renderShopping() {
  const sh = state.week.shopping;
  if (!sh.count) {
    $("#shopping-body").innerHTML = '<p class="muted">Nothing to buy — the pantry has it covered.</p>';
    return;
  }
  $("#shopping-body").innerHTML = sh.by_store
    .map(
      (g) => `
      <div class="store">
        <h3><span>${esc(g.store)}</span><span>${g.items.length}</span></h3>
        <ul class="items">
          ${g.items
            .map(
              (i) => `
            <li>
              <div class="what">
                <b>${esc(i.item)}</b>
                <span class="for">for ${esc(i.for.join(", "))}</span>
                ${i.deal ? `<span class="tag-deal" title="${esc(i.deal.name)}">🏷️ ${esc(i.deal.price_text)}${i.deal.savings ? ` · save $${i.deal.savings.toFixed(2)}` : ""}</span>` : ""}
              </div>
              <span class="amt">${esc(i.amount)}</span>
            </li>`
            )
            .join("")}
        </ul>
      </div>`
    )
    .join("");
}

// Day actions (event delegation)
$("#days").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.recipe) return openRecipe(Number(b.dataset.recipe));
  if (b.dataset.swap)
    return busy(b, async () => {
      state.week = await api(`/api/days/${b.dataset.swap}/swap`, { method: "POST", body: {} });
      renderWeek();
      toast("Swapped. The planner will remember you passed on that one.");
    });
  if (b.dataset.lock) {
    const m = state.week.meals.find((x) => x.day === b.dataset.lock);
    return busy(b, async () => {
      state.week = await api(`/api/days/${b.dataset.lock}/lock`, { method: "POST", body: { locked: !m.locked } });
      renderWeek();
    });
  }
  if (b.dataset.choose) return chooseRecipe(b.dataset.choose);
  if (b.dataset.rate) return rateDialog(Number(b.dataset.rate), b.dataset.day);
});

$("#plan-week").addEventListener("click", (e) =>
  busy(e.currentTarget, async () => {
    state.week = await api("/api/week/plan", { method: "POST", body: { week_start: state.start } });
    renderWeek();
    toast("Planned. Kept dinners stayed put.");
  })
);

async function refreshDeals(btn) {
  return busy(btn, async () => {
    const r = await api("/api/deals/refresh", { method: "POST" });
    if (r.ok) toast(`Checked ${r.searched} items: ${r.saved} deals at your stores.`);
    else toast(r.error || "Couldn't check the flyers.", 6000);
    if (!$("#tab-week").hidden) await loadWeek(state.start);
    else loadDeals();
  });
}
$("#refresh-deals").addEventListener("click", (e) => refreshDeals(e.currentTarget));
$("#refresh-deals-2").addEventListener("click", (e) => refreshDeals(e.currentTarget));

$("#send-keep").addEventListener("click", (e) =>
  busy(e.currentTarget, async () => {
    const preview = await api("/api/keep/sync", { method: "POST", body: { week_start: state.start, dry_run: true } });
    openModal(`
      <h2>Send to Google Keep</h2>
      <p class="muted">Only items marked 🍽 are ever changed. Things you or Google Home added stay as they are.</p>
      ${preview.add.length ? `<h3>Add ${preview.add.length}</h3><ul>${preview.add.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : "<p>Nothing new to add.</p>"}
      ${preview.remove.length ? `<h3>Take off ${preview.remove.length} from an older plan</h3><ul>${preview.remove.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      ${preview.already_on_list.length ? `<p class="muted">Already on your list: ${esc(preview.already_on_list.join(", "))}</p>` : ""}
      <div class="day-actions"><button class="primary" id="keep-go">Update Keep</button><a href="${esc(preview.link)}" target="_blank" rel="noopener">Open list</a></div>`);
    $("#keep-go").addEventListener("click", (ev) =>
      busy(ev.currentTarget, async () => {
        const r = await api("/api/keep/sync", { method: "POST", body: { week_start: state.start } });
        closeModal();
        toast(`Keep updated: ${r.add.length} added, ${r.remove.length} removed.`);
      })
    );
  })
);

$("#prev-week").addEventListener("click", () => loadWeek(iso(addDays(parseDay(state.start), -7))));
$("#next-week").addEventListener("click", () => loadWeek(iso(addDays(parseDay(state.start), 7))));
$("#this-week").addEventListener("click", () => loadWeek(iso(mondayOf(state.week?.today ? parseDay(state.week.today) : new Date()))));
function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

// ── Rating ───────────────────────────────────────────────────────────────────
function stars(recipeId, day) {
  return `<span class="stars" data-recipe="${recipeId}" data-day="${day || ""}">${[1, 2, 3, 4, 5]
    .map((n) => `<button data-stars="${n}" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`)
    .join("")}</span>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-stars]");
  if (!b) return;
  const wrap = b.closest(".stars");
  try {
    await api("/api/ratings", {
      method: "POST",
      body: { recipe_id: Number(wrap.dataset.recipe), rating: Number(b.dataset.stars), served_on: wrap.dataset.day || null },
    });
    toast(Number(b.dataset.stars) >= 4 ? "Noted, you'll see more like it." : "Noted, it'll come up less.");
    closeModal();
    loadRateBanner();
    if (!$("#tab-taste").hidden) loadTaste();
  } catch (err) {
    toast(err.message);
  }
});

async function loadRateBanner() {
  const pending = await api("/api/ratings/pending").catch(() => []);
  $("#rate-banner").innerHTML = pending.length
    ? `<div class="rate-banner"><b>How were these? A tap teaches the planner.</b>
        ${pending
          .slice(0, 3)
          .map((p) => `<div class="rate-row"><span>${esc(fmtDay(p.day, { weekday: "short" }))} · ${esc(p.name)}</span>${stars(p.id, p.day)}</div>`)
          .join("")}</div>`
    : "";
}

function rateDialog(recipeId, day) {
  const r = state.week.meals.find((m) => m.recipe?.id === recipeId)?.recipe;
  openModal(`<h2>How was ${esc(r?.name || "it")}?</h2><p class="muted">5 = make it again soon, 1 = never again.</p>${stars(recipeId, day)}`);
}

// ── Recipe modal and picker ──────────────────────────────────────────────────
async function openRecipe(id) {
  const r = await api(`/api/recipes/${id}`);
  const steps = (r.instructions || "").split("\n").filter(Boolean).map((s) => s.replace(/^\d+\.\s*/, ""));
  openModal(`
    <article class="recipe">
      <h2>${esc(r.name)}</h2>
      <div class="meta" style="margin-top:6px">
        <span>⏱ ${r.total_minutes} min (${r.hands_on} hands-on)</span><span>serves ${r.servings}</span>
        ${r.ratings.count ? `<span>★ ${r.ratings.average.toFixed(1)} (${r.ratings.count})</span>` : ""}
        ${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">source</a>` : ""}
      </div>
      <div class="tags" style="margin-top:8px">${r.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
      ${r.image_url ? `<img src="${esc(r.image_url)}" alt="" loading="lazy" />` : ""}
      <div class="cols">
        <div><h3>Ingredients</h3><ul>${r.ingredients.map((i) => `<li>${esc(i.line)}</li>`).join("")}</ul></div>
        <div><h3>Steps</h3><ol>${steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>
      </div>
      <p>Rate it: ${stars(r.id, "")}</p>
    </article>`);
}

async function chooseRecipe(day) {
  if (!state.recipes.length) state.recipes = await api("/api/recipes");
  openModal(`
    <h2>Choose dinner for ${esc(fmtDay(day, { weekday: "long" }))}</h2>
    <input id="pick-q" type="search" placeholder="Search…" style="width:100%;margin-top:10px" />
    <ul class="pick-list" id="pick-list"></ul>`);
  const render = (q = "") => {
    const ql = q.toLowerCase();
    $("#pick-list").innerHTML = state.recipes
      .filter((r) => !ql || r.name.toLowerCase().includes(ql) || r.tags.some((t) => t.includes(ql)))
      .map((r) => `<li><button data-pick="${r.id}"><span>${esc(r.name)}</span><span class="muted">${r.total_minutes} min</span></button></li>`)
      .join("");
  };
  render();
  $("#pick-q").addEventListener("input", (e) => render(e.target.value));
  $("#pick-list").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-pick]");
    if (!b) return;
    state.week = await api(`/api/days/${day}/swap`, { method: "POST", body: { recipe_id: Number(b.dataset.pick) } });
    closeModal();
    renderWeek();
    toast("Done, and kept for re-plans.");
  });
}

function openModal(html) {
  $("#modal-body").innerHTML = html;
  const d = $("#modal");
  if (!d.open) d.showModal();
}
function closeModal() {
  const d = $("#modal");
  if (d.open) d.close();
}

// ── Recipes tab ──────────────────────────────────────────────────────────────
async function loadRecipes() {
  state.recipes = await api("/api/recipes");
  renderRecipes();
}
function renderRecipes() {
  const q = $("#recipe-search").value.toLowerCase();
  const list = state.recipes.filter(
    (r) =>
      !q ||
      r.name.toLowerCase().includes(q) ||
      r.tags.some((t) => t.includes(q)) ||
      r.ingredients.some((i) => i.item.includes(q))
  );
  $("#recipe-grid").innerHTML =
    list
      .map(
        (r) => `
      <article class="card">
        ${r.image_url ? `<img src="${esc(r.image_url)}" alt="" loading="lazy" />` : ""}
        <button class="meal-name title" data-recipe="${r.id}">${esc(r.name)}</button>
        <div class="meta"><span>⏱ ${r.total_minutes} min</span>${r.protein ? `<span>${esc(r.protein)}</span>` : ""}${r.ratings.count ? `<span>★ ${r.ratings.average.toFixed(1)}</span>` : ""}${r.makes_leftovers ? "<span>🥡 leftovers</span>" : ""}</div>
        <div class="tags">${r.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
        <div class="day-actions"><button data-retire="${r.id}" class="small ghost">Stop suggesting</button></div>
      </article>`
      )
      .join("") || '<p class="muted">No recipes match.</p>';
}
$("#recipe-search").addEventListener("input", renderRecipes);
$("#recipe-grid").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.recipe) return openRecipe(Number(b.dataset.recipe));
  if (b.dataset.retire) {
    await api(`/api/recipes/${b.dataset.retire}`, { method: "DELETE" });
    toast("It won't be planned any more.");
    loadRecipes();
  }
});
$("#import-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const btn = e.currentTarget.querySelector("button");
  busy(btn, async () => {
    const r = await api("/api/recipes/import", { method: "POST", body: { url: $("#import-url").value } });
    $("#import-url").value = "";
    toast(`Added “${r.name}” with ${r.ingredients.length} ingredients.`);
    loadRecipes();
  });
});

// ── Deals tab ────────────────────────────────────────────────────────────────
async function loadDeals() {
  state.deals = await api("/api/deals");
  renderDeals();
}
function renderDeals() {
  const q = $("#deal-search").value.toLowerCase();
  const list = state.deals.filter((d) => !q || d.name.toLowerCase().includes(q) || d.store.toLowerCase().includes(q));
  const stores = [...new Set(state.deals.map((d) => d.store))];
  $("#deals-meta").textContent = state.deals.length
    ? `${state.deals.length} deals on things your recipes use, at ${stores.join(", ")}.`
    : "No deals saved yet. Check the flyers, or add one you spotted.";
  $("#deal-grid").innerHTML = list
    .map(
      (d) => `
    <article class="card">
      ${d.image_url ? `<img src="${esc(d.image_url)}" alt="" loading="lazy" />` : ""}
      <span class="store-name">${esc(d.store)}${d.source === "manual" ? " · added by you" : ""}</span>
      <span class="title">${esc(d.name)}</span>
      <span class="price">${esc(d.price_text)}</span>
      <span class="muted" style="font-size:.8rem">${d.valid_to ? "until " + esc(fmtDay(d.valid_to)) : ""} ${d.link ? `· <a href="${esc(d.link)}" target="_blank" rel="noopener">flyer</a>` : ""}</span>
    </article>`
    )
    .join("");
}
$("#deal-search").addEventListener("input", renderDeals);
$("#deal-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.currentTarget);
  const btn = e.currentTarget.querySelector("button");
  busy(btn, async () => {
    await api("/api/deals", {
      method: "POST",
      body: {
        store: f.get("store"),
        name: f.get("name"),
        price: f.get("price") ? Number(f.get("price")) : null,
        valid_to: f.get("valid_to") || null,
        note: f.get("note") || "",
      },
    });
    e.target.reset();
    toast("Saved. The next plan will use it.");
    loadDeals();
  });
});

// ── Taste tab ────────────────────────────────────────────────────────────────
async function loadTaste() {
  const [p, pending] = await Promise.all([api("/api/preferences"), api("/api/ratings/pending")]);
  const bars = (rows, neg) => {
    const top = Math.max(0.01, ...rows.map((r) => Math.abs(r.weight)));
    return rows
      .map((r) => {
        const [kind, name] = r.key.split(":");
        const pct = Math.max(8, (Math.abs(r.weight) / top) * 100);
        return `<div class="bar"><span class="label">${esc(name)} <span class="muted">${esc(kind)}</span></span><span class="track"><span class="fill ${neg ? "neg" : ""}" style="width:${pct}%"></span></span></div>`;
      })
      .join("") || '<p class="muted">Nothing yet. Rate a few dinners.</p>';
  };
  $("#taste").innerHTML = `
    <section class="card"><h2>Rate recent dinners</h2>${
      pending.length
        ? pending.map((x) => `<div class="rate-row"><span>${esc(fmtDay(x.day, { weekday: "short" }))} · ${esc(x.name)}</span>${stars(x.id, x.day)}</div>`).join("")
        : '<p class="muted">All caught up.</p>'
    }</section>
    <section class="card"><h2>Favourites</h2>${
      p.favourites.length
        ? `<ul class="items">${p.favourites.map((f) => `<li><span class="what"><b style="text-transform:none">${esc(f.name)}</b></span><span class="amt">★ ${f.average.toFixed(1)} · ${f.count}×</span></li>`).join("")}</ul>`
        : '<p class="muted">Rate dinners 4★ or more and they show up here.</p>'
    }</section>
    <section class="card"><h2>More of</h2>${bars(p.likes, false)}</section>
    <section class="card"><h2>Less of</h2>${bars(p.dislikes, true)}</section>
    <section class="card"><h2>How it learns</h2><p class="muted">Each rating nudges that recipe a lot, and its cuisine, style and main protein a little. Swapping a dinner out is a gentle "not this week". It's all stored in the planner's own database, so nothing is forgotten and no AI tokens are spent.</p></section>`;
}

// ── Start ────────────────────────────────────────────────────────────────────
let initial = "week";
try { initial = localStorage.getItem("tab") || "week"; } catch {}
loadWeek().catch((e) => toast(e.message, 6000));
showTab(initial);
