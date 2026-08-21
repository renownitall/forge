const COPY_TEXT = {
  key: `curl -fsSL https://renownitall.github.io/forge/signing_key.asc -o /tmp/forge-signing-key.asc\nsudo pacman-key --add /tmp/forge-signing-key.asc\nsudo pacman-key --lsign-key 45EAC3E28FC392FC4418F415C0C5B611BF77F6E5`,
  conf: `[forge]\nSigLevel = Required DatabaseOptional\nServer = https://renownitall.github.io/forge`,
  install: `sudo pacman -Syu\nsudo pacman -S PACKAGE_NAME`,
};

const copyStatus = document.getElementById("copy-status");

document.querySelectorAll(".copy").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const original = btn.textContent;
    try {
      await navigator.clipboard.writeText(COPY_TEXT[btn.dataset.copy]);
      btn.textContent = "Copied";
      copyStatus.textContent = "Copied to clipboard";
    } catch {
      btn.textContent = "Failed";
      copyStatus.textContent =
        "Copy failed. The commands are selected instead.";
      const code = btn.parentElement.querySelector("code");
      if (code) {
        const range = document.createRange();
        range.selectNodeContents(code);
        const selection = window.getSelection();
        if (selection) {
          selection.removeAllRanges();
          selection.addRange(range);
        }
      }
    }
    setTimeout(() => {
      btn.textContent = original;
      copyStatus.textContent = "";
    }, 1200);
  });
});

const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

const fmtSize = (n) => {
  if (!Number.isFinite(n) || n < 0) return "—";
  return n >= 1048576
    ? `${(n / 1048576).toFixed(1)} MiB`
    : n >= 1024
      ? `${(n / 1024).toFixed(1)} KiB`
      : `${n} B`;
};

const fmtDate = (ts) => {
  if (!Number.isFinite(ts)) return "—";
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
};

const rowsEl = document.getElementById("rows");
const countEl = document.getElementById("count");
const errorEl = document.getElementById("error");
const filterEl = document.getElementById("filter");
const filterClear = document.getElementById("filter-clear");

let packages = [];

const render = (list) => {
  countEl.textContent = `${list.length} of ${packages.length}`;
  if (!list.length) {
    rowsEl.innerHTML =
      '<tr><td colspan="5" class="state">No matching packages.</td></tr>';
    return;
  }
  rowsEl.innerHTML = list
    .map(
      (p) => `<tr>
              <td class="mono">
                ${esc(p.name ?? "—")}
                <span class="pkg-links"><a href="https://github.com/renownitall/forge/blob/main/packages/${encodeURIComponent(p.base ?? p.name ?? "")}/PKGBUILD">PKGBUILD</a></span>
              </td>
              <td class="mono">${esc(p.version ?? "—")}</td>
              <td class="desc">${esc(p.description ?? "")}</td>
              <td class="num">${fmtSize(p.size)}</td>
              <td class="num">${fmtDate(p.built)}</td>
            </tr>`,
    )
    .join("");
};

filterEl.addEventListener("input", () => {
  filterClear.hidden = !filterEl.value.trim();
  const q = filterEl.value.trim().toLowerCase();
  render(
    q
      ? packages.filter((p) =>
          `${p.name} ${p.description || ""}`.toLowerCase().includes(q),
        )
      : packages,
  );
});

filterClear.addEventListener("click", () => {
  filterEl.value = "";
  filterEl.dispatchEvent(new Event("input"));
  filterEl.focus();
});

const themeRoot = document.documentElement;
const themeBtn = document.getElementById("theme-toggle");

const SUN_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>`;
const MOON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;

const syncThemeIcon = () => {
  themeBtn.innerHTML = themeRoot.dataset.theme === "dark" ? SUN_SVG : MOON_SVG;
};

themeBtn.addEventListener("click", () => {
  const next = themeRoot.dataset.theme === "dark" ? "light" : "dark";
  themeRoot.dataset.theme = next;
  try {
    localStorage.setItem("forge-theme", next);
  } catch {}
  syncThemeIcon();
});

syncThemeIcon();

fetch("packages.json", { cache: "no-store" })
  .then((res) => {
    if (!res.ok) throw new Error(res.status);
    return res.json();
  })
  .then((data) => {
    if (!data || !Array.isArray(data.packages)) throw new Error("invalid manifest");
    packages = data.packages;
    render(packages);
  })
  .catch(() => {
    rowsEl.innerHTML = "";
    countEl.textContent = "";
    errorEl.hidden = false;
  });
