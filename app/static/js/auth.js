const form = document.getElementById("form");
const errorEl = document.getElementById("error");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.classList.remove("show");
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const res = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (res.redirected) { location.href = res.url; return; }  // 303 -> /app
    let msg = "Something went wrong. Please try again.";
    try { const d = await res.json(); if (d.error) msg = d.error; } catch {}
    errorEl.textContent = msg;
    errorEl.classList.add("show");
  } catch {
    errorEl.textContent = "Network error. Please try again.";
    errorEl.classList.add("show");
  } finally {
    btn.disabled = false;
  }
});
