/* Speculum: search, and sorting and filters on tables. Everything runs in the reader's browser on files
   built with the site; nothing is sent anywhere and nothing is tracked. */
(function () {
  "use strict";
  var ROOT = (document.documentElement.getAttribute("data-root") || "");

  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function fold(s) {
    s = String(s || "");
    if (s.normalize) s = s.normalize("NFKD").replace(/[̀-ͯ]/g, "");
    return s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }
  var cache = {};
  function getJSON(path) {
    return cache[path] || (cache[path] = fetch(ROOT + path).then(function (r) { if (!r.ok) throw new Error(path); return r.json(); }));
  }

  // ---------------- search ----------------
  var WEIGHT = {"Member": 3, "Case": 3, "Page": 2.5, "Bill": 1.5, "Organization": 1.2};
  function rank(index, q, limit) {
    var toks = fold(q).split(" ").filter(Boolean);
    if (!toks.length) return [];
    var fq = toks.join(" "), out = [];
    for (var i = 0; i < index.length; i++) {
      var e = index[i], name = fold(e[1]), hay = name + " " + (e[4] || ""), words = hay.split(" "), score = 0, ok = true;
      for (var t = 0; t < toks.length && ok; t++) {
        var tk = toks[t], best = 0;
        for (var w = 0; w < words.length; w++) {
          if (words[w] === tk) { best = 3; break; }
          if (words[w].indexOf(tk) === 0) best = Math.max(best, 2);
        }
        if (!best && tk.length >= 4 && hay.indexOf(tk) !== -1) best = 1;
        if (!best) ok = false; else score += best;
      }
      if (!ok) continue;
      if (name.indexOf(fq) === 0) score += 5; else if (name.indexOf(fq) !== -1) score += 2;
      score *= (WEIGHT[e[0]] || 1);
      score -= i / 1e6;                       // ties: the order the file lists them in (largest organizations first)
      out.push([score, e]);
    }
    out.sort(function (a, b) { return b[0] - a[0]; });
    return out.slice(0, limit || 12).map(function (x) { return x[1]; });
  }
  function resultHTML(e, on) {
    return '<a class="sr' + (on ? ' on' : '') + '" href="' + ROOT + e[3] + '"><span class="sr-t">' + esc(e[0]) + '</span><span class="sr-n">' +
      esc(e[1]) + '</span><span class="sr-s">' + esc(e[2]) + '</span></a>';
  }
  window.SpeculumSearch = {rank: rank, load: function () { return getJSON("search.json"); }, html: resultHTML};

  var box = document.getElementById("site-search"), btn = document.getElementById("search-btn");
  if (box && btn) {
    var input = box.querySelector("input"), list = box.querySelector(".sr-list"), results = [], sel = 0;
    function open() { box.hidden = false; btn.setAttribute("aria-expanded", "true"); input.focus(); getJSON("search.json"); }
    function close() { box.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    function draw() {
      list.innerHTML = results.length ? results.map(function (e, i) { return resultHTML(e, i === sel); }).join("") +
        '<a class="sr-all" href="' + ROOT + 'search.html?q=' + encodeURIComponent(input.value) + '">All results for “' + esc(input.value) + '”</a>'
        : (input.value.trim() ? '<p class="sr-none">Nothing found. Try a last name, a company, a bill number such as “HR 1013”, or a topic such as “banks”.</p>' : "");
    }
    input.addEventListener("input", function () {
      var q = input.value;
      getJSON("search.json").then(function (ix) { if (input.value === q) { results = rank(ix, q, 8); sel = 0; draw(); } });
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown") { sel = Math.min(sel + 1, results.length - 1); draw(); ev.preventDefault(); }
      else if (ev.key === "ArrowUp") { sel = Math.max(sel - 1, 0); draw(); ev.preventDefault(); }
      else if (ev.key === "Enter") { ev.preventDefault(); location.href = results[sel] ? ROOT + results[sel][3] : ROOT + "search.html?q=" + encodeURIComponent(input.value); }
      else if (ev.key === "Escape") close();
    });
    btn.addEventListener("click", function () { box.hidden ? open() : close(); });
    document.addEventListener("keydown", function (ev) {
      var tag = (ev.target.tagName || "").toLowerCase();
      if (ev.key === "/" && tag !== "input" && tag !== "textarea" && tag !== "select") { ev.preventDefault(); open(); }
    });
    document.addEventListener("click", function (ev) { if (!box.hidden && !box.contains(ev.target) && ev.target !== btn && !btn.contains(ev.target)) close(); });
  }

  // ---------------- tables: sort and filter ----------------
  function cellValue(td) {
    if (!td) return null;
    if (td.hasAttribute("data-v")) { var v = td.getAttribute("data-v"); return v === "" ? null : (isNaN(+v) ? v : +v); }
    var t = (td.innerText || td.textContent || "").trim().split("\n")[0].trim();
    if (!t || t === "—" || t === "-" || /^(none|no reports|n\/a)$/i.test(t)) return null;
    var m = t.match(/^(-)?\$?\s?([\d,]*\.?\d+)\s*([KMB])?\b/i);
    if (m && /^[-$\d]/.test(t)) {
      var n = parseFloat(m[2].replace(/,/g, "")) * ({k: 1e3, m: 1e6, b: 1e9}[(m[3] || "").toLowerCase()] || 1);
      return m[1] ? -n : n;
    }
    if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t;
    return t.toLowerCase();
  }
  function sortable(table) {
    var head = table.tHead && table.tHead.rows[0], body = table.tBodies[0];
    if (!head || !body || table.hasAttribute("data-nosort")) return;
    if (body.querySelector("td[colspan]")) return;          // grouped tables keep their order
    Array.prototype.forEach.call(head.cells, function (th, col) {
      if (th.colSpan > 1) return;
      th.classList.add("sortable"); th.tabIndex = 0; th.setAttribute("role", "columnheader");
      function go() {
        var dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
        Array.prototype.forEach.call(head.cells, function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", dir);
        var rows = Array.prototype.slice.call(body.rows), k = dir === "ascending" ? 1 : -1;
        rows.sort(function (a, b) {
          var x = cellValue(a.cells[col]), y = cellValue(b.cells[col]);
          if (x === null && y === null) return 0; if (x === null) return 1; if (y === null) return -1;
          if (typeof x === "number" && typeof y === "number") return (x - y) * k;
          return String(x).localeCompare(String(y)) * k;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      }
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
    });
  }

  var PN = {D: "Democrats", R: "Republicans", I: "Independents"};
  function money(x) { x = +x || 0; return x >= 1e9 ? "$" + (x / 1e9).toFixed(1) + "B" : x >= 1e6 ? "$" + (x / 1e6).toFixed(1) + "M" : x >= 1e3 ? "$" + Math.round(x / 1e3) + "K" : "$" + Math.round(x).toLocaleString(); }

  function filters(table) {
    var body = table.tBodies[0];
    if (!body || table.hasAttribute("data-nofilter") || body.querySelector("td[colspan]")) return;
    var rows = Array.prototype.slice.call(body.rows), bios = rows.map(function (r) {
      var a = r.querySelector('a[href*="member/"]'); var m = a && a.getAttribute("href").match(/member\/([A-Z]\d{6})\.html/);
      return m ? m[1] : null;
    });
    var nMembers = bios.filter(Boolean).length;
    if (rows.length < 12 && nMembers < 8) return;
    var bar = document.createElement("div"); bar.className = "tbl-tools";
    bar.innerHTML = '<input type="search" class="tt-q" placeholder="Filter rows" aria-label="Filter this table">' +
      '<span class="tt-more"></span><span class="tt-count meta" aria-live="polite"></span>';
    var wrap = table.closest(".tbl-wrap, .table-wrap") || table;
    wrap.parentNode.insertBefore(bar, wrap);
    var q = bar.querySelector(".tt-q"), count = bar.querySelector(".tt-count"), state = {party: "", ch: "", st: "", cm: ""}, people = null, cidx = null;
    var moneyCol = -1, head = table.tHead && table.tHead.rows[0];
    if (head) for (var c = 0; c < head.cells.length; c++) {
      var vals = rows.slice(0, 5).map(function (r) { return (r.cells[c] && r.cells[c].textContent || "").trim(); });
      if (vals.some(function (v) { return /^\$/.test(v); })) { moneyCol = c; break; }
    }
    var LIMIT = 50, expanded = rows.length <= LIMIT + 10, more = null;
    if (!expanded) {
      table.classList.add("collapsed");
      more = document.createElement("p"); more.className = "meta tt-all";
      more.innerHTML = '<a href="#">Show all ' + rows.length + ' rows</a> · the top ' + LIMIT + ' are shown in the current order';
      wrap.parentNode.insertBefore(more, wrap.nextSibling);
      more.querySelector("a").addEventListener("click", function (ev) { ev.preventDefault(); expanded = true; table.classList.remove("collapsed"); more.remove(); });
    }
    function apply() {
      var t = fold(q.value), shown = 0, sum = 0;
      rows.forEach(function (r, i) {
        var ok = !t || fold(r.textContent).indexOf(t) !== -1, p = people && bios[i] && people[bios[i]];
        if (ok && (state.party || state.ch || state.st || state.cm)) {
          if (!p) ok = false;
          else {
            if (state.party && (p[0] === "I" ? "I" : p[0]) !== state.party) ok = false;
            if (state.ch && p[1] !== state.ch) ok = false;
            if (state.st && p[2] !== state.st) ok = false;
            if (state.cm && p[3].indexOf(state.cm) === -1) ok = false;
          }
        }
        r.hidden = !ok;
        if (ok) { shown++; if (moneyCol >= 0) { var v = cellValue(r.cells[moneyCol]); if (typeof v === "number") sum += v; } }
      });
      var filtered = shown !== rows.length;
      if (!expanded) { table.classList.toggle("collapsed", !filtered); if (more) more.hidden = filtered; }
      count.innerHTML = filtered ? '<b class="tt-on">Filtered:</b> ' + shown + " of " + rows.length + " rows" + (moneyCol >= 0 ? " · " + money(sum) + " in the rows shown" : "") : "";
    }
    q.addEventListener("input", apply);
    if (nMembers >= 8) {
      Promise.all([getJSON("people.json"), getJSON("committees.json")]).then(function (x) {
        people = x[0]; cidx = x[1];
        var present = bios.filter(Boolean).map(function (b) { return people[b]; }).filter(Boolean);
        var states = {}, cms = {}, chambers = {};
        present.forEach(function (p) { states[p[2]] = 1; chambers[p[1]] = 1; p[3].forEach(function (c) { cms[c] = (cms[c] || 0) + 1; }); });
        var cmList = Object.keys(cms).filter(function (c) { return cidx[c]; }).sort(function (a, b) {
          var A = cidx[a], B = cidx[b], pa = A.p || a, pb = B.p || b;
          if (pa !== pb) return (cidx[pa] ? cidx[pa].c + cidx[pa].n : pa) < (cidx[pb] ? cidx[pb].c + cidx[pb].n : pb) ? -1 : 1;
          return A.p ? (B.p ? (A.n < B.n ? -1 : 1) : 1) : -1;
        });
        var chName = {h: "House", s: "Senate", j: "Joint"};
        var html = '<select data-k="party" aria-label="Party"><option value="">All parties</option>' + ["D", "R", "I"].map(function (p) { return '<option value="' + p + '">' + PN[p] + '</option>'; }).join("") + '</select>';
        if (Object.keys(chambers).length > 1) html += '<select data-k="ch" aria-label="Chamber"><option value="">Both chambers</option><option value="h">House</option><option value="s">Senate</option></select>';
        html += '<select data-k="st" aria-label="State"><option value="">All states</option>' + Object.keys(states).sort().map(function (s) { return '<option>' + s + '</option>'; }).join("") + '</select>';
        html += '<select data-k="cm" aria-label="Committee"><option value="">All committees</option>' + cmList.map(function (c) {
          var e = cidx[c]; return '<option value="' + c + '">' + (e.p ? " " + esc(e.n.replace(/^.*?:\s*/, "")) : chName[e.c] + ": " + esc(e.n)) + '</option>'; }).join("") + '</select>';
        var more = bar.querySelector(".tt-more"); more.innerHTML = html;
        more.querySelectorAll("select").forEach(function (s) { s.addEventListener("change", function () { state[s.dataset.k] = s.value; apply(); }); });
      }).catch(function () {});
    }
  }
  function enhance(table) {
    if (table.querySelector("th[data-sort]")) return;          // pages with their own sorting and filters (The Chamber, Interests)
    sortable(table); filters(table);
  }
  window.SpeculumTables = {enhance: enhance, money: money, getJSON: getJSON, esc: esc, fold: fold};
  document.querySelectorAll(".tbl-wrap > table, .table-wrap > table, table.data").forEach(function (t) {
    if (!t.hasAttribute("data-late")) enhance(t);
  });
})();
