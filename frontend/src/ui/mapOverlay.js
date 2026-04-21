function titleFor(event) {
  if (event.type === "worker_earn") return "Completing a Work Cycle";
  if (event.type === "steal_bank") return "Vault Breach Detected";
  if (event.type === "steal_agent") return "Street Theft Attempt";
  if (event.type === "cop_chase") return "Pursuit in Progress";
  if (event.type === "api_call") return "Requesting External Intel";
  if (event.type === "ai_decision") return "Target Decision Issued";
  return "City Activity Update";
}

function lineFor(event) {
  if (event.type === "worker_earn") {
    const reward = Number(event.reward || 0).toFixed(2);
    return `${event.worker_id || "worker"} extracted value (+${reward}) and sent settlement.`;
  }
  if (event.type === "steal_bank") {
    return `${event.thief_id || "thief"} attempted to siphon funds from ${event.bank_id || "bank"}.`;
  }
  if (event.type === "steal_agent") {
    return `${event.thief_id || "thief"} targeted ${event.target_id || "an agent"} for direct theft.`;
  }
  if (event.type === "cop_chase") {
    return `${event.cop_id || "cop"} is tracking ${event.target_id || "a suspect"} through the grid.`;
  }
  if (event.type === "api_call") {
    return `${event.agent || "agent"} paid for external signal guidance before next move.`;
  }
  if (event.type === "ai_decision") {
    return `AI selected ${event.target || "a target"} via ${event.provider || "fallback"} mode.`;
  }
  return `${event.type} executed.`;
}

function focusIdFor(event) {
  return (
    event.worker_id ||
    event.thief_id ||
    event.cop_id ||
    event.agent ||
    event.target_id ||
    event.bank_id ||
    event.target ||
    null
  );
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

export function initMapOverlay(root) {
  root.innerHTML = `
    <svg id="callout-lines" viewBox="0 0 960 540" preserveAspectRatio="none"></svg>
    <div id="callout-cards"></div>
  `;
  const lines = root.querySelector("#callout-lines");
  const cardsWrap = root.querySelector("#callout-cards");
  const cards = [];
  const thumbCanvas = document.createElement("canvas");
  thumbCanvas.width = 220;
  thumbCanvas.height = 104;
  const thumbCtx = thumbCanvas.getContext("2d", { alpha: false });
  const slots = [
    { x: 22, y: 24, w: 290, h: 132 },
    { x: 648, y: 28, w: 290, h: 132 },
    { x: 22, y: 384, w: 300, h: 132 },
    { x: 636, y: 360, w: 302, h: 154 },
  ];

  function draw() {
    cardsWrap.innerHTML = cards
      .slice(0, slots.length)
      .map((card, i) => {
        const s = slots[i];
        const snapX = clamp(card.focus?.x ?? 480, 18, 942);
        const snapY = clamp(card.focus?.y ?? 18, 18, 522);
        const dialogue = card.dialogue || "";
        return `
          <article class="story-callout" style="left:${s.x}px;top:${s.y}px;width:${s.w}px;min-height:${s.h}px">
            <h4>${card.title}</h4>
            <div class="story-chip">${card.label}</div>
            <div class="story-preview">
              ${card.thumb ? `<img src="${card.thumb}" alt="" />` : `<div class="story-preview-empty"></div>`}
            </div>
            <p>${card.body}</p>
            ${dialogue ? `<pre class="story-dialogue">${dialogue}</pre>` : ""}
          </article>
          <svg class="story-link" viewBox="0 0 960 540" preserveAspectRatio="none" aria-hidden="true">
            <line x1="${s.x + s.w / 2}" y1="${s.y + s.h - 4}" x2="${snapX}" y2="${snapY}" />
            <circle cx="${snapX}" cy="${snapY}" r="6" />
          </svg>
        `;
      })
      .join("");
  }

  function captureThumb(focus, captureCanvas) {
    if (!focus || !captureCanvas || !thumbCtx) return null;
    const source = captureCanvas();
    if (!source) return null;
    const sw = source.width || 960;
    const sh = source.height || 540;
    const cropW = 320;
    const cropH = 150;
    const sx = clamp((focus.x || 480) - cropW / 2, 0, Math.max(0, sw - cropW));
    const sy = clamp((focus.y || 270) - cropH / 2, 0, Math.max(0, sh - cropH));
    thumbCtx.imageSmoothingEnabled = false;
    thumbCtx.fillStyle = "#1a2a3f";
    thumbCtx.fillRect(0, 0, thumbCanvas.width, thumbCanvas.height);
    thumbCtx.drawImage(
      source,
      sx,
      sy,
      cropW,
      cropH,
      0,
      0,
      thumbCanvas.width,
      thumbCanvas.height,
    );
    return thumbCanvas.toDataURL("image/png");
  }

  function dialogueFor(event) {
    if (event.type === "worker_earn") return "[Ops]: Throughput confirmed.\n[Worker]: Cycle complete.";
    if (event.type === "steal_bank") return "[Alert]: Vault breach.\n[Guard]: Dispatching response.";
    if (event.type === "steal_agent") return "[Alert]: Street robbery reported.\n[Cop]: Investigating.";
    if (event.type === "cop_chase") return "[Dispatch]: Target tracked.\n[Cop]: Closing distance.";
    if (event.type === "api_call") return "[Cop]: Requesting intel.\n[Oracle]: Candidate returned.";
    if (event.type === "ai_decision") return "[AI]: Target selected.\n[System]: Execution queued.";
    return "";
  }

  function pushCard(payload) {
    const signature = `${payload.title}|${payload.label}|${payload.body}`;
    if (cards[0]?.signature === signature) return;
    cards.unshift({ ...payload, signature, at: Date.now() });
    if (cards.length > 8) cards.length = 8;
  }

  function update({ newEvents = [], resolvePoint, captureCanvas }) {
    if (newEvents.length) {
      newEvents
        .filter((event) => event && typeof event.type === "string")
        .slice(-3)
        .forEach((event) => {
          const focusId = focusIdFor(event);
          const focus = focusId ? resolvePoint?.(focusId) : null;
          const thumb = captureThumb(focus, captureCanvas);
          pushCard({
            title: titleFor(event),
            label: focusId || event.type,
            body: lineFor(event),
            dialogue: dialogueFor(event),
            thumb,
            focus,
          });
        });
    }
    draw();
  }

  return { update };
}
