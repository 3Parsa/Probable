const form = document.getElementById("gen-form");
const totalEl = document.getElementById("total");
const previewEl = document.getElementById("preview");
const downloadLink = document.getElementById("download-link");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);

  const response = await fetch("/generate", { method: "POST", body: formData });
  if (!response.ok) {
    totalEl.textContent = "Error generating candidates.";
    previewEl.innerHTML = "";
    return;
  }

  const data = await response.json();
  totalEl.textContent = `${data.total} total candidates (showing top ${data.preview.length})`;
  previewEl.innerHTML = "";
  for (const candidate of data.preview) {
    const li = document.createElement("li");
    li.textContent = candidate;
    previewEl.appendChild(li);
  }

  const params = new URLSearchParams(formData);
  downloadLink.href = `/download?${params.toString()}`;
});
