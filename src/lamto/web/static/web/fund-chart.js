/* Renders #fund-chart from the #fund-chart-data json_script payload.
   data-compact="1" = balance line only (Action inbox card). */
(function () {
  "use strict";
  var dataEl = document.getElementById("fund-chart-data");
  var canvas = document.getElementById("fund-chart");
  if (!dataEl || !canvas || typeof Chart === "undefined") return;
  var points = JSON.parse(dataEl.textContent);
  if (!points.length) return;
  var compact = canvas.dataset.compact === "1";
  var vnd = function (v) { return Number(v).toLocaleString("vi-VN"); };
  var datasets = [
    {
      type: "line",
      label: canvas.dataset.labelBalance || "Balance",
      data: points.map(function (p) { return p.balance_vnd; }),
      borderColor: "#3f51b5",
      backgroundColor: "rgba(63, 81, 181, 0.12)",
      fill: true,
      tension: 0.2,
      pointRadius: compact ? 0 : 2,
      order: 0,
    },
  ];
  if (!compact) {
    datasets.push(
      {
        type: "bar",
        label: canvas.dataset.labelInflows || "Inflows",
        data: points.map(function (p) { return p.inflows_vnd; }),
        backgroundColor: "rgba(46, 125, 50, 0.6)",
        order: 1,
      },
      {
        type: "bar",
        label: canvas.dataset.labelOutflows || "Outflows",
        data: points.map(function (p) { return p.outflows_vnd; }),
        backgroundColor: "rgba(198, 40, 40, 0.6)",
        order: 1,
      }
    );
  }
  new Chart(canvas, {
    data: {
      labels: points.map(function (p) { return p.period_start; }),
      datasets: datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { display: !compact } },
        y: { ticks: { callback: vnd } },
      },
      plugins: {
        legend: { display: !compact },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return ctx.dataset.label + ": " + vnd(ctx.parsed.y) + " VND";
            },
          },
        },
      },
    },
  });
})();
