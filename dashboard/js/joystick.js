/**
 * BOB Dashboard — joystick.js
 * Canvas-based mecanum joystick.
 * Sends {vy, vx} to app.js every frame while dragging.
 */

(function () {
  const canvas = document.getElementById('joystick');
  const ctx    = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const CX = W / 2, CY = H / 2;
  const BASE_R  = W / 2 - 6;   // outer ring radius
  const KNOB_R  = 32;            // draggable knob radius
  const MAX_R   = BASE_R - KNOB_R;

  let dragging = false;
  let kx = 0, ky = 0;  // knob offset from centre (-MAX_R … MAX_R)

  // Colours
  const C_BASE_FILL   = '#151825';
  const C_BASE_RING   = 'rgba(255,255,255,0.07)';
  const C_CROSS       = 'rgba(255,255,255,0.06)';
  const C_KNOB_IDLE   = '#1c2133';
  const C_KNOB_ACTIVE = '#f5c800';
  const C_KNOB_RING   = 'rgba(245,200,0,0.35)';
  const C_DOT         = '#f5c800';

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Outer base circle
    ctx.beginPath();
    ctx.arc(CX, CY, BASE_R, 0, Math.PI * 2);
    ctx.fillStyle = C_BASE_FILL;
    ctx.fill();
    ctx.strokeStyle = C_BASE_RING;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Crosshair guides
    ctx.strokeStyle = C_CROSS;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 6]);
    ctx.beginPath(); ctx.moveTo(CX, CY - BASE_R + 4); ctx.lineTo(CX, CY + BASE_R - 4); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(CX - BASE_R + 4, CY); ctx.lineTo(CX + BASE_R - 4, CY); ctx.stroke();
    ctx.setLineDash([]);

    // Direction zones (subtle sectors)
    const zones = [
      [  -45,   45, 'rgba(245,200,0,0.04)'],  // forward
      [  135,  225, 'rgba(245,200,0,0.04)'],  // backward
      [   45,  135, 'rgba(76,158,255,0.03)'], // right
      [  225,  315, 'rgba(76,158,255,0.03)'], // left
    ];
    zones.forEach(([s, e, col]) => {
      ctx.beginPath();
      ctx.moveTo(CX, CY);
      ctx.arc(CX, CY, BASE_R - 2, (s - 90) * Math.PI / 180, (e - 90) * Math.PI / 180);
      ctx.closePath();
      ctx.fillStyle = col;
      ctx.fill();
    });

    // Centre dot
    ctx.beginPath();
    ctx.arc(CX, CY, 4, 0, Math.PI * 2);
    ctx.fillStyle = C_DOT;
    ctx.fill();

    // Knob shadow
    const kpx = CX + kx, kpy = CY + ky;
    ctx.beginPath();
    ctx.arc(kpx + 3, kpy + 4, KNOB_R, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fill();

    // Knob glow when dragging
    if (dragging) {
      ctx.beginPath();
      ctx.arc(kpx, kpy, KNOB_R + 8, 0, Math.PI * 2);
      const grad = ctx.createRadialGradient(kpx, kpy, KNOB_R, kpx, kpy, KNOB_R + 12);
      grad.addColorStop(0, 'rgba(245,200,0,0.25)');
      grad.addColorStop(1, 'rgba(245,200,0,0)');
      ctx.fillStyle = grad;
      ctx.fill();
    }

    // Knob body
    ctx.beginPath();
    ctx.arc(kpx, kpy, KNOB_R, 0, Math.PI * 2);
    const kgrad = ctx.createRadialGradient(kpx - 5, kpy - 5, 2, kpx, kpy, KNOB_R);
    if (dragging) {
      kgrad.addColorStop(0, '#ffe040');
      kgrad.addColorStop(1, '#c89800');
    } else {
      kgrad.addColorStop(0, '#252a3d');
      kgrad.addColorStop(1, '#1a1e2e');
    }
    ctx.fillStyle = kgrad;
    ctx.fill();
    ctx.strokeStyle = dragging ? C_KNOB_RING : C_BASE_RING;
    ctx.lineWidth = dragging ? 2 : 1;
    ctx.stroke();

    // Knob inner dot
    ctx.beginPath();
    ctx.arc(kpx, kpy, 5, 0, Math.PI * 2);
    ctx.fillStyle = dragging ? '#fff8' : 'rgba(255,255,255,0.15)';
    ctx.fill();
  }

  function clampToCircle(dx, dy) {
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > MAX_R) {
      const scale = MAX_R / dist;
      return [dx * scale, dy * scale];
    }
    return [dx, dy];
  }

  function getPos(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = W / rect.width, scaleY = H / rect.height;
    if (e.touches) {
      return [(e.touches[0].clientX - rect.left) * scaleX,
              (e.touches[0].clientY - rect.top)  * scaleY];
    }
    return [(e.clientX - rect.left) * scaleX,
            (e.clientY - rect.top)  * scaleY];
  }

  function startDrag(e) {
    e.preventDefault();
    dragging = true;
    moveDrag(e);
  }

  function moveDrag(e) {
    if (!dragging) return;
    e.preventDefault();
    const [px, py] = getPos(e);
    [kx, ky] = clampToCircle(px - CX, py - CY);
    emitValues();
    draw();
  }

  function endDrag() {
    if (!dragging) return;
    dragging = false;
    kx = 0; ky = 0;
    emitValues();
    draw();
  }

  function emitValues() {
    // vy = forward/back (-255…255), vx = strafe (-255…255)
    const vy = -Math.round((ky / MAX_R) * 255);
    const vx =  Math.round((kx / MAX_R) * 255);
    // Dispatch custom event for app.js to pick up
    canvas.dispatchEvent(new CustomEvent('joystick-move', {
      detail: { vy, vx }, bubbles: true
    }));
  }

  // Mouse
  canvas.addEventListener('mousedown',  startDrag);
  canvas.addEventListener('mousemove',  moveDrag);
  canvas.addEventListener('mouseup',    endDrag);
  canvas.addEventListener('mouseleave', endDrag);

  // Touch
  canvas.addEventListener('touchstart', startDrag, { passive: false });
  canvas.addEventListener('touchmove',  moveDrag,  { passive: false });
  canvas.addEventListener('touchend',   endDrag);

  draw();
})();
