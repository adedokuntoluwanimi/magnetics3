function getNoticeNode() {
  let node = document.getElementById("globalNotice");
  if (node) {
    return node;
  }
  node = document.createElement("div");
  node.id = "globalNotice";
  node.style.display = "none";
  node.style.position = "fixed";
  node.style.top = "76px";
  node.style.right = "18px";
  node.style.zIndex = "40";
  node.style.maxWidth = "360px";
  node.style.padding = "12px 14px";
  node.style.borderRadius = "14px";
  node.style.boxShadow = "var(--shadow)";
  node.style.border = "1px solid var(--border)";
  node.style.fontSize = "12px";
  node.style.fontWeight = "600";
  document.body.appendChild(node);
  return node;
}

export function showGlobalNotice(message, tone = "error") {
  const node = getNoticeNode();
  node.style.display = "block";
  node.textContent = message;
  if (tone === "success") {
    node.style.background = "var(--g50)";
    node.style.color = "var(--g600)";
    node.style.borderColor = "var(--g100)";
    return;
  }
  if (tone === "info") {
    node.style.background = "var(--blue-bg)";
    node.style.color = "var(--blue)";
    node.style.borderColor = "rgba(26,95,140,0.18)";
    return;
  }
  node.style.background = "var(--red-bg)";
  node.style.color = "var(--red)";
  node.style.borderColor = "rgba(185,28,28,0.18)";
}

export function hideGlobalNotice() {
  const node = getNoticeNode();
  node.style.display = "none";
  node.textContent = "";
}
