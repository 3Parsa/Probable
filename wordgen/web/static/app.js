const form = document.getElementById("gen-form");
const resultsPanel = document.getElementById("results");
const totalEl = document.getElementById("total");
const previewEl = document.getElementById("preview");
const downloadLink = document.getElementById("download-link");
const generateBtn = document.getElementById("generate-btn");
const btnLabel = generateBtn.querySelector(".btn-label");
const loadExampleBtn = document.getElementById("load-example-btn");
const copyBtn = document.getElementById("copy-btn");

// English sample values for the "Load example" one-click demo -- matches
// the fields' placeholder text so the filled-in form and the placeholders
// tell the same story.
const EXAMPLE_VALUES = {
  names: "Michael",
  dates: "1995-03-15",
  pets: "Buddy",
  teams: "Liverpool",
  places: "London",
  partner: "Emily",
  custom: "sunshine",
};

// The currently rendered preview candidates, kept around so the copy
// button can copy exactly what's on screen without an extra fetch.
let lastPreview = [];

function setLoading(isLoading) {
  generateBtn.disabled = isLoading;
  generateBtn.classList.toggle("is-loading", isLoading);
  btnLabel.textContent = isLoading ? "Generating…" : "Generate";
}

loadExampleBtn.addEventListener("click", () => {
  for (const [field, value] of Object.entries(EXAMPLE_VALUES)) {
    const input = form.elements.namedItem(field);
    if (input) {
      input.value = value;
    }
  }
});

copyBtn.addEventListener("click", async () => {
  if (!lastPreview.length) {
    return;
  }
  try {
    await navigator.clipboard.writeText(lastPreview.join("\n"));
  } catch {
    return; // clipboard access denied/unavailable - fail quietly, no crash
  }

  const originalLabel = copyBtn.textContent;
  copyBtn.textContent = "Copied!";
  copyBtn.classList.add("is-copied");
  setTimeout(() => {
    copyBtn.textContent = originalLabel;
    copyBtn.classList.remove("is-copied");
  }, 1200);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);

  setLoading(true);
  try {
    const response = await fetch("/generate", { method: "POST", body: formData });
    if (!response.ok) {
      resultsPanel.classList.add("is-empty");
      resultsPanel.classList.remove("has-results");
      totalEl.textContent = "Error generating candidates.";
      previewEl.textContent = "";
      lastPreview = [];
      copyBtn.hidden = true;
      return;
    }

    const data = await response.json();

    // Rebuild the list from scratch each time so a stale re-render never
    // mixes candidates from two different requests.
    previewEl.textContent = "";
    for (const [index, candidate] of data.preview.entries()) {
      const li = document.createElement("li");
      li.dataset.rank = index + 1;
      li.textContent = candidate; // never innerHTML - candidates echo operator input
      previewEl.appendChild(li);
    }

    lastPreview = data.preview;
    copyBtn.hidden = data.preview.length === 0;

    totalEl.textContent = `${data.total} total candidates (showing top ${data.preview.length})`;
    resultsPanel.classList.remove("is-empty");
    resultsPanel.classList.add("has-results");

    // Retrigger the entrance animation on every fresh render.
    previewEl.style.animation = "none";
    previewEl.offsetHeight; // eslint-disable-line no-unused-expressions
    previewEl.style.animation = "";

    const params = new URLSearchParams(formData);
    downloadLink.href = `/download?${params.toString()}`;
  } finally {
    setLoading(false);
  }
});
