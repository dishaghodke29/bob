/**
 * BOB Dashboard — gauges.js
 * Draws animated arc gauges for roll & pitch on canvas.
 * Also draws the VL53L5CX 8×8 ToF heatmap.
 */

(function () {

  // ── Arc gauge ────────────────────────────────────────────────────────────

  function drawGauge(canvas, valueDeg, maxDeg, color) {
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2, r = W / 2 - 10;
    ctx.clearRect(0, 0, W, H);

    const startAngle = Math.PI * 0.75;   // 135°
    const endAngle   = Math.PI * 2.25;   // 405°  (total sweep = 270°)
    const sweep      = Math.PI * 1.5;    // 270°

    // Track background
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.strokeStyle = '#1c2133';
    ctx.lineWidth = 10;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Value arc
    const frac = Math.min(1, Math.abs(valueDeg) / maxDeg);
    const midAngle = startAngle + sweep / 2;   // straight up = 0°
    const arcEnd   = midAngle + (valueDeg / maxDeg) * (sweep / 2);

    ctx.beginPath();
    ctx.arc(cx, cy, r, midAngle, arcEnd, valueDeg < 0);
    ctx.strokeStyle = color;
    ctx.lineWidth = 10;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Centre tick marks
    for (let i = 0; i <= 6; i++) {
      const a = startAngle + (i / 6) * sweep;
      const x1 = cx + (r - 13) * Math.cos(a);
      const y1 = cy + (r - 13) * Math.sin(a);
      const x2 = cx + (r - 6)  * Math.cos(a);
      const y2 = cy + (r - 6)  * Math.sin(a);
      ctx.beginPath();
      ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Needle dot
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }

  // ── ToF heatmap ──────────────────────────────────────────────────────────

  function heatColor(v, min, max) {
    // v=min → green, v=max → red, via yellow
    const t = Math.min(1, Math.max(0, (v - min) / (max - min)));
    // green → yellow → red
    let r, g, b;
    if (t < 0.5) {
      r = Math.round(t * 2 * 255);
      g = Math.round(255 - t * 0.4 * 255);
    } else {
      r = 255;
      g = Math.round((1 - (t - 0.5) * 2) * 200);
    }
    b = 0;
    return `rgb(${r},${g},${b})`;
  }

  window.drawToF = function (grid) {
    const canvas = document.getElementById('tof-canvas');
    if (!canvas || !grid || grid.length !== 64) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const cellW = W / 8, cellH = H / 8;
    const validVals = grid.filter(v => v > 0);
    const minV = validVals.length ? Math.min(...validVals) : 0;
    const maxV = validVals.length ? Math.max(...validVals) : 200;

    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const val = grid[row * 8 + col];
        const x = col * cellW, y = row * cellH;
        ctx.fillStyle = val > 0 ? heatColor(val, Math.max(0, minV - 5), Math.min(300, maxV + 5))
                                : '#151825';
        ctx.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);

        // Value label
        if (val > 0) {
          ctx.fillStyle = 'rgba(0,0,0,0.55)';
          ctx.font = '9px Space Mono, monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(Math.round(val), x + cellW / 2, y + cellH / 2);
        }
      }
    }
  };

  // ── Public update function called by app.js ───────────────────────────────

  let _roll = 0, _pitch = 0;

  window.updateGauges = function ({ roll, pitch }) {
    _roll  = roll  ?? _roll;
    _pitch = pitch ?? _pitch;

    const rollCanvas  = document.getElementById('roll-gauge');
    const pitchCanvas = document.getElementById('pitch-gauge');
    if (rollCanvas)  drawGauge(rollCanvas,  _roll,  45, '#f5c800');
    if (pitchCanvas) drawGauge(pitchCanvas, _pitch, 45, '#4c9eff');

    const rv = document.getElementById('roll-val');
    const pv = document.getElementById('pitch-val');
    if (rv) rv.textContent  = _roll.toFixed(1)  + '°';
    if (pv) pv.textContent  = _pitch.toFixed(1) + '°';
  };

  // Draw initial empty gauges
  window.updateGauges({ roll: 0, pitch: 0 });

})();
