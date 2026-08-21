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
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    setTimeout(() => {
      btn.textContent = original;
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

const fmtSize = (n) =>
  n >= 1048576
    ? `${(n / 1048576).toFixed(1)} MiB`
    : n >= 1024
      ? `${(n / 1024).toFixed(1)} KiB`
      : `${n} B`;

const fmtDate = (ts) =>
  new Date(ts * 1000).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });

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
                ${esc(p.name)}
                <span class="pkg-links"><a href="https://github.com/renownitall/forge/blob/main/packages/${esc(p.base)}/PKGBUILD">PKGBUILD</a></span>
              </td>
              <td class="mono">${esc(p.version)}</td>
              <td class="desc">${esc(p.description || "")}</td>
              <td class="num">${fmtSize(p.size)}</td>
              <td class="num">${fmtDate(p.built)}</td>
            </tr>`,
    )
    .join("");
};

filterEl.addEventListener("input", () => {
  filterClear.hidden = !filterEl.value;
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
const sunIcon = document.getElementById("icon-sun");
const moonIcon = document.getElementById("icon-moon");

const syncThemeIcon = () => {
  const dark = themeRoot.dataset.theme === "dark";
  sunIcon.hidden = !dark;
  moonIcon.hidden = dark;
};

themeBtn.addEventListener("click", () => {
  const next = themeRoot.dataset.theme === "dark" ? "light" : "dark";
  themeRoot.dataset.theme = next;
  localStorage.setItem("forge-theme", next);
  syncThemeIcon();
});

syncThemeIcon();

fetch("packages.json")
  .then((res) => {
    if (!res.ok) throw new Error(res.status);
    return res.json();
  })
  .then((data) => {
    packages = data.packages;
    render(packages);
  })
  .catch(() => {
    rowsEl.innerHTML = "";
    errorEl.hidden = false;
  });
