/* history.js - event log, stats and charts */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let typeChart = null, timelineChart = null;

  async function load() {
    const [stats, ev] = await Promise.all([
      fetch("/api/stats").then((r) => r.json()),
      fetch("/api/events?limit=200").then((r) => r.json()),
    ]);
    renderStats(stats);
    renderTable(ev.events || []);
  }

  function renderStats(s) {
    $("sTotal").textContent = s.total || 0;
    $("s24h").textContent = s.last_24h || 0;
    $("sHigh").textContent = (s.by_severity && s.by_severity.high) || 0;
    $("sYawn").textContent = (s.by_type && s.by_type.YAWN) || 0;

    const types = Object.keys(s.by_type || {});
    const counts = types.map((t) => s.by_type[t]);
    if (typeChart) typeChart.destroy();
    typeChart = new Chart($("typeChart"), {
      type: "doughnut",
      data: { labels: types.length ? types : ["No data"],
        datasets: [{ data: counts.length ? counts : [1],
          backgroundColor: ["#3b82f6","#ef4444","#f59e0b","#22c55e","#a855f7","#06b6d4"] }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "right", labels: { color: "#cbd5e1" } } } },
    });

    const labels = (s.timeline || []).map((p) => p.hour.slice(11) + ":00");
    const data = (s.timeline || []).map((p) => p.count);
    if (timelineChart) timelineChart.destroy();
    timelineChart = new Chart($("timelineChart"), {
      type: "bar",
      data: { labels, datasets: [{ label: "Events", data,
        backgroundColor: "#3b82f6" }] },
      options: { responsive: true, maintainAspectRatio: false,
        scales: { x: { ticks: { color: "#98a2b3" }, grid: { color: "#232a33" } },
                  y: { ticks: { color: "#98a2b3" }, grid: { color: "#232a33" }, beginAtZero: true } },
        plugins: { legend: { display: false } } },
    });
  }

  function renderTable(events) {
    const body = $("eventsBody");
    if (!events.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted">No events yet.</td></tr>';
      return;
    }
    body.innerHTML = events.map((e) => `
      <tr>
        <td>${e.timestamp.replace("T", " ")}</td>
        <td>${e.event_type}</td>
        <td><span class="sev sev-${e.severity}">${e.severity}</span></td>
        <td>${e.message || ""}</td>
        <td>${fmt(e.ear)}</td>
        <td>${fmt(e.mar)}</td>
        <td>${e.score != null ? e.score : "-"}</td>
        <td>${e.source || ""}</td>
      </tr>`).join("");
  }

  function fmt(v) { return (v === null || v === undefined) ? "-" : Number(v).toFixed(2); }

  $("clearBtn").addEventListener("click", async () => {
    if (!confirm("Delete all logged events?")) return;
    await fetch("/api/events/clear", { method: "POST" });
    load();
  });

  load();
  setInterval(load, 5000);
})();
