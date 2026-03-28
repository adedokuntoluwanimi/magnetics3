export function showConfirm(
  message,
  {title = "Confirm", confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false, onConfirm, onCancel} = {},
) {
  const overlay = document.createElement("div");
  overlay.className = "gaia-modal-overlay";
  overlay.innerHTML = `
    <div class="gaia-modal">
      <div class="gaia-modal-title">${title}</div>
      <div class="gaia-modal-msg">${message}</div>
      <div class="gaia-modal-actions">
        <button class="btn btn-out btn-sm" id="_gmCancel">${cancelLabel}</button>
        <button class="btn ${danger ? "btn-danger" : "btn-g"} btn-sm" id="_gmConfirm">${confirmLabel}</button>
      </div>
    </div>
  `;
  const close = () => overlay.remove();
  overlay.querySelector("#_gmCancel").addEventListener("click", () => { close(); onCancel?.(); });
  overlay.querySelector("#_gmConfirm").addEventListener("click", () => { close(); onConfirm?.(); });
  overlay.addEventListener("click", (e) => { if (e.target === overlay) { close(); onCancel?.(); } });
  document.body.appendChild(overlay);
}

export function showAlert(message, {title = "Notice"} = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "gaia-modal-overlay";
    overlay.innerHTML = `
      <div class="gaia-modal">
        <div class="gaia-modal-title">${title}</div>
        <div class="gaia-modal-msg">${message}</div>
        <div class="gaia-modal-actions">
          <button class="btn btn-g btn-sm" id="_gmOk">OK</button>
        </div>
      </div>
    `;
    overlay.querySelector("#_gmOk").addEventListener("click", () => { overlay.remove(); resolve(); });
    document.body.appendChild(overlay);
  });
}
