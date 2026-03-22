export async function loadScript(src) {
  const existing = document.querySelector(`script[src="${src}"]`);
  if (existing) {
    return;
  }
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}
