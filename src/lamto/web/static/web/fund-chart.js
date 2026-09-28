/* Renders #fund-chart from the #fund-chart-data json_script payload.
   data-compact="1" = balance line only (Action inbox card).
   Colours come from the stylesheet's tokens, so the chart follows the page
   into dark mode. Flows use the tint and a neutral: green and red are
   reserved for evidence state and never describe money moving. */
(function () {
  "use strict";
  var dataEl = document.getElementById("fund-chart-data");
  var canvas = document.getElementById("fund-chart");
  if (!dataEl || !canvas || typeof Chart === "undefined") return;
  var points = JSON.parse(dataEl.textContent);
  if (!points.length) return;
  var compact = canvas.dataset.compact === "1";
  var palette = getComputedStyle(document.documentElement);
  var color = function (name) { return palette.getPropertyValue(name).trim(); };
  var withAlpha = function (hex, alpha) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    if (!m) return hex;
    return "rgba(" + parseInt(m[1], 16) + "," + parseInt(m[2], 16) + "," + parseInt(m[3], 16) + "," + alpha + ")";
  };
  var vnd = function (v) { return Number(v).toLocaleString("vi-VN"); };
  var compactVnd = new Intl.NumberFormat("vi-VN", { notation: "compact", maximumFractionDigits: 1 });
  var tint = color("--tint");
  var label = color("--label");
  var secondary = color("--label-secondary");
  var separator = color("--separator");
  var surface = color("--surface-raised");
  var font = { family: getComputedStyle(document.body).fontFamily, size: 11 };

  // The area under the balance fades out, so the line reads first.
  var fill = function (context) {
    var chart = context.chart;
    var area = chart.chartArea;
    if (!area) return withAlpha(tint, 0.12);
    var gradient = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    gradient.addColorStop(0, withAlpha(tint, compact ? 0.22 : 0.16));
    gradient.addColorStop(1, withAlpha(tint, 0));
    return gradient;
  };

  var datasets = [
    {
      type: "line",
      label: canvas.dataset.labelBalance || "Balance",
      data: points.map(function (p) { return p.balance_vnd; }),
      borderColor: tint,
      borderWidth: 2,
      backgroundColor: fill,
      fill: true,
      tension: 0.35,
      cubicInterpolationMode: "monotone",
      pointRadius: 0,
      pointHoverRadius: 4,
      pointHoverBackgroundColor: tint,
      pointHoverBorderColor: surface,
      pointHoverBorderWidth: 2,
      order: 0,
    },
  ];
  if (!compact) {
    datasets.push(
      {
        type: "bar",
        label: canvas.dataset.labelInflows || "Inflows",
        data: points.map(function (p) { return p.inflows_vnd; }),
        backgroundColor: withAlpha(tint, 0.35),
        borderRadius: 4,
        maxBarThickness: 18,
        order: 1,
      },
      {
        type: "bar",
        label: canvas.dataset.labelOutflows || "Outflows",
        data: points.map(function (p) { return p.outflows_vnd; }),
        backgroundColor: withAlpha(secondary, 0.4),
        borderRadius: 4,
        maxBarThickness: 18,
        order: 1,
      }
    );
  }
  new Chart(canvas, {
    data: {
      labels: points.map(function (p) {
        var raw = String(p.period_start || "");
        // period_start is ISO date; show d/m/Y to match staff_datetime day-first.
        var m = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
        return m ? m[3] + "/" + m[2] + "/" + m[1] : raw;
      }),
      datasets: datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: compact ? { top: 4, bottom: 2 } : { top: 8 } },
      scales: {
        x: {
          display: !compact,
          grid: { display: false },
          border: { display: false },
          ticks: { color: secondary, font: font, maxRotation: 0, autoSkipPadding: 16 },
        },
        y: {
          display: !compact,
          beginAtZero: true,
          grid: { color: separator, drawTicks: false },
          border: { display: false },
          ticks: {
            color: secondary,
            font: font,
            padding: 8,
            maxTicksLimit: 5,
            callback: function (v) { return compactVnd.format(v); },
          },
        },
      },
      plugins: {
        legend: {
          display: !compact,
          align: "end",
          labels: { color: label, font: { family: font.family, size: 12 }, usePointStyle: true, pointStyle: "rectRounded", boxWidth: 8, boxHeight: 8 },
        },
        tooltip: {
          backgroundColor: surface,
          titleColor: label,
          bodyColor: label,
          borderColor: separator,
          borderWidth: 1,
          cornerRadius: 10,
          padding: 10,
          boxPadding: 4,
          usePointStyle: true,
          titleFont: { family: font.family, size: 12, weight: "600" },
          bodyFont: { family: font.family, size: 12 },
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
