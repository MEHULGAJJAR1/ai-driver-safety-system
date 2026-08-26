/* upload.js - offline file analysis */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const form = $("uploadForm");
  const progress = $("progress");
  const errBox = $("uploadError");
  const results = $("results");
  let chart = null;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = $("fileInput").files[0];
    if (!file) return;

    errBox.classList.add("hidden");
    results.classList.add("hidden");
    progress.classList.remove("hidden");

    const fd = new FormData();
    fd.append("file", file);

    let data;
    try {
      const r = await fetch("/api/analyze", { method: "POST", body: fd });
      data = await r.json();
    } catch (err) {
      showError("Upload failed: " + err.message);
      return;
    }
    progress.classList.add("hidden");

    if (!data.ok) { showError(data.error || "Analysis failed."); return; }
    render(data);
  });

  function showError(msg) {
    progress.classList.add("hidden");
    errBox.textContent = msg;
    errBox.classList.remove("hidden");
  }

  function render(d) {
    $("verdict").textContent = d.verdict;
    $("verdict").style.color =
      d.verdict.startsWith("Drowsiness") ? "#ef4444"
      : d.verdict.startsWith("Mild") ? "#f59e0b" : "#22c55e";

    $("rFrames").textContent = d.frames_analyzed;
    $("rFaces").textContent = d.faces_found;
    $("rMax").textContent = d.max_score;
    $("rAvg").textContent = d.avg_score;
    $("rMinEar").textContent = d.min_ear ?? "-";
    $("rDrowsy").textContent = d.drowsy_events;
    $("rYawn").textContent = d.yawn_count;
    $("rNod").textContent = d.nod_count;

    if (d.preview) $("previewImg").src = d.preview;
    results.classList.remove("hidden");

    const labels = d.timeline.map((p) => p.t);
    const scores = d.timeline.map((p) => p.score);
    if (chart) chart.destroy();
    chart = new Chart($("uploadChart"), {
      type: "line",
      data: { labels, datasets: [{
        label: "Drowsiness score", data: scores,
        borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.15)",
        fill: true, tension: .25, pointRadius: 0, borderWidth: 2,
      }]},
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        scales: {
          x: { title: { display: true, text: d.kind === "video" ? "seconds" : "frame", color: "#98a2b3" },
               ticks: { color: "#98a2b3", maxTicksLimit: 10 }, grid: { color: "#232a33" } },
          y: { min: 0, max: 100, ticks: { color: "#98a2b3" }, grid: { color: "#232a33" } },
        },
        plugins: { legend: { labels: { color: "#cbd5e1" } } },
      },
    });
  }
})();
