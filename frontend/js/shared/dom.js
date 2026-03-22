export function ensureElement(parent, selector, create) {
  let element = parent.querySelector(selector);
  if (!element) {
    element = create();
    parent.appendChild(element);
  }
  return element;
}

export function setFlash(element, message, tone = "info") {
  element.style.display = "block";
  element.textContent = message;
  if (tone === "error") {
    element.style.background = "var(--red-bg)";
    element.style.color = "var(--red)";
    element.style.border = "1px solid rgba(185,28,28,0.18)";
    return;
  }
  if (tone === "success") {
    element.style.background = "var(--g50)";
    element.style.color = "var(--g600)";
    element.style.border = "1px solid var(--g100)";
    return;
  }
  element.style.background = "var(--blue-bg)";
  element.style.color = "var(--blue)";
  element.style.border = "1px solid rgba(26,95,140,0.18)";
}

export function clearFlash(element) {
  element.style.display = "none";
  element.textContent = "";
}
