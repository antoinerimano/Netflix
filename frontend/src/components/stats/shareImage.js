// src/components/stats/shareImage.js
// The "Share my year" picture: a 1080 x 1350 card (a phone story / post size) drawn on a canvas
// from the stats, in the app's colors. Shared with the phone's share sheet, else downloaded.

const W = 1080;
const H = 1350;
const RED = '#e50914';

function fit(ctx, text, max, size, weight = 700) {
  let s = size;
  ctx.font = `${weight} ${s}px Inter, system-ui, sans-serif`;
  while (s > 20 && ctx.measureText(text).width > max) {
    s -= 2;
    ctx.font = `${weight} ${s}px Inter, system-ui, sans-serif`;
  }
  return s;
}

/**
 * lines: { year, name, headline, sub, facts: [[label, value], ...], brand }  (already translated)
 * -> Promise<Blob> (image/png)
 */
export function drawShareImage(lines) {
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#2a0507');
  bg.addColorStop(0.45, '#111114');
  bg.addColorStop(1, '#0a0a0c');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = RED;
  ctx.fillRect(80, 120, 120, 10);

  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = '#ffffff';
  ctx.font = '700 44px Inter, system-ui, sans-serif';
  ctx.fillText(`${lines.year} · ${lines.name}`, 80, 210);

  fit(ctx, lines.headline, W - 160, 132, 900);
  ctx.fillText(lines.headline, 80, 390);
  ctx.fillStyle = 'rgba(255,255,255,0.72)';
  fit(ctx, lines.sub, W - 160, 44, 500);
  ctx.fillText(lines.sub, 80, 460);

  let y = 600;
  for (const [label, value] of lines.facts) {
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.font = '600 34px Inter, system-ui, sans-serif';
    ctx.fillText(label.toUpperCase(), 80, y);
    ctx.fillStyle = '#ffffff';
    fit(ctx, value, W - 160, 64, 800);
    ctx.fillText(value, 80, y + 72);
    y += 170;
  }

  ctx.fillStyle = RED;
  ctx.font = '800 40px Inter, system-ui, sans-serif';
  ctx.fillText(lines.brand, 80, H - 90);

  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}

/** Share sheet when the device has one for files, else a download. Returns "shared" | "saved". */
export async function shareOrSave(blob, filename, title) {
  const file = new File([blob], filename, { type: 'image/png' });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title });
      return 'shared';
    } catch (e) {
      if (e?.name === 'AbortError') return 'cancelled';
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return 'saved';
}
