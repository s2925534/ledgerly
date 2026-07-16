// Vanilla JS only, deliberately: this app has no build step and no third-party
// dependency. Every data operation below calls the same /api/v1/* JSON API the
// CLI uses (see docs/api/CONTRACT.md) rather than duplicating any engine logic
// here. Session auth rides on the httponly cookie the login page sets, so
// fetch() calls never need to read or store a token themselves.

const state = {
  workspace: null,
  uploads: [],
};

function apiUrl(path, params = {}) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("workspace", state.workspace);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

async function api(method, path, { params = {}, json = null, formData = null } = {}) {
  const options = { method, credentials: "same-origin" };
  if (formData) {
    options.body = formData;
  } else if (json !== null) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(json);
  }
  const response = await fetch(apiUrl(path, params), options);
  if (response.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.href);
    throw new Error("unauthorized");
  }
  const body = await response.json();
  if (!response.ok || !body.ok) {
    const message = (body.errors && body.errors[0] && body.errors[0].message) || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body.data;
}

// --- workspace loading ---

function showWorkspaceError(message) {
  const el = document.getElementById("workspace-error");
  el.textContent = message;
  el.hidden = !message;
}

async function loadWorkspace(workspace) {
  state.workspace = workspace;
  showWorkspaceError("");
  document.getElementById("app-main").hidden = true;
  try {
    await loadUploadLimits();
    await refreshUploads();
    document.getElementById("app-main").hidden = false;
  } catch (err) {
    showWorkspaceError(err.message);
    return;
  }
  // Zotero panel failures are shown inline in that panel, not as a
  // workspace-load error — a missing/unconfigured Zotero account shouldn't
  // block the rest of the app from loading.
  refreshZoteroPanel();
}

async function loadUploadLimits() {
  const limits = await api("GET", "/api/v1/artefacts/upload/limits");
  document.getElementById("upload-limits").textContent =
    `Up to ${limits.max_files} files per batch, ${limits.max_file_size_mb} MB each. ` +
    `Allowed types: ${limits.allowed_extensions.join(", ")}.`;
}

async function refreshUploads() {
  const uploads = await api("GET", "/api/v1/artefacts/uploads");
  state.uploads = uploads;
  renderUploadsTable(uploads);
}

function renderUploadsTable(uploads) {
  const tbody = document.getElementById("uploads-tbody");
  const empty = document.getElementById("uploads-empty");
  tbody.innerHTML = "";
  empty.hidden = uploads.length > 0;
  for (const upload of uploads) {
    const tr = document.createElement("tr");
    const crossRefCount = (upload.cross_references || []).length;
    tr.innerHTML = `
      <td>${escapeHtml(upload.title || "")}</td>
      <td>${escapeHtml(upload.original_file_name || "")}</td>
      <td>${escapeHtml(upload.renamed_file_name || "")}</td>
      <td>${crossRefCount}</td>
      <td class="row-actions"></td>
    `;
    const actions = tr.querySelector(".row-actions");

    const previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.textContent = "Preview";
    previewBtn.addEventListener("click", () => openPreview(upload));
    actions.appendChild(previewBtn);

    const crossRefBtn = document.createElement("button");
    crossRefBtn.type = "button";
    crossRefBtn.className = "secondary";
    crossRefBtn.textContent = "Cross-reference";
    crossRefBtn.addEventListener("click", () => openCrossReference(upload));
    actions.appendChild(crossRefBtn);

    tbody.appendChild(tr);
  }
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// --- upload (drag-and-drop + browse) ---

function setupDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const browseLink = document.getElementById("browse-link");

  browseLink.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("click", (event) => {
    if (event.target === browseLink) return;
    fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) uploadFiles(fileInput.files);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", (event) => {
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length) uploadFiles(files);
  });
}

async function uploadFiles(fileList) {
  const formData = new FormData();
  for (const file of fileList) formData.append("files", file);

  const reportEl = document.getElementById("upload-report");
  reportEl.textContent = "Uploading...";
  try {
    const report = await api("POST", "/api/v1/artefacts/upload", { formData });
    renderUploadReport(report);
    await refreshUploads();
  } catch (err) {
    reportEl.textContent = "";
    showWorkspaceError(err.message);
  }
}

function renderUploadReport(report) {
  const reportEl = document.getElementById("upload-report");
  const rows = (report.rows || [])
    .map(
      (row) => `
      <tr>
        <td>${escapeHtml(row.file_name || "")}</td>
        <td>${escapeHtml(row.status || "")}</td>
        <td>${escapeHtml(row.reason || "")}</td>
      </tr>`
    )
    .join("");
  reportEl.innerHTML = `
    <p>Processed ${report.processed}: ${report.accepted} accepted, ${report.duplicate} duplicate,
       ${report.rejected} rejected, ${report.failed} failed.</p>
    <table class="data-table">
      <thead><tr><th>File</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// --- preview modal ---

const TEXT_PREVIEW_EXTENSIONS = new Set([".txt", ".md", ".csv", ".json"]);
const IMAGE_PREVIEW_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp"]);

function extensionOf(filename) {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

async function openPreview(upload) {
  const titleEl = document.getElementById("preview-title");
  const bodyEl = document.getElementById("preview-body");
  titleEl.textContent = upload.title || upload.renamed_file_name || "Preview";
  bodyEl.innerHTML = "Loading preview...";
  openModal("preview-modal");

  const ext = extensionOf(upload.renamed_file_name || "");
  const fileUrl = apiUrl(`/api/v1/artefacts/uploads/${encodeURIComponent(upload.upload_id)}/file`);

  if (ext === ".pdf") {
    bodyEl.innerHTML = `<iframe src="${fileUrl}" title="Preview"></iframe>`;
  } else if (IMAGE_PREVIEW_EXTENSIONS.has(ext)) {
    bodyEl.innerHTML = `<img src="${fileUrl}" alt="Preview">`;
  } else if (TEXT_PREVIEW_EXTENSIONS.has(ext)) {
    try {
      const response = await fetch(fileUrl, { credentials: "same-origin" });
      const text = await response.text();
      bodyEl.innerHTML = `<pre></pre>`;
      bodyEl.querySelector("pre").textContent = text;
    } catch (err) {
      bodyEl.textContent = "Could not load preview.";
    }
  } else {
    bodyEl.innerHTML = `<p>No inline preview available for ${escapeHtml(ext || "this file type")}.
      <a href="${fileUrl}" target="_blank" rel="noopener">Open in a new tab</a> instead.</p>`;
  }
}

// --- cross-reference review overlay ---

let crossRefUploadId = null;

async function openCrossReference(upload) {
  crossRefUploadId = upload.upload_id;
  const bodyEl = document.getElementById("crossref-body");
  bodyEl.innerHTML = "Loading candidates...";
  openModal("crossref-modal");
  await refreshCrossReferenceCandidates();
}

async function refreshCrossReferenceCandidates() {
  const bodyEl = document.getElementById("crossref-body");
  try {
    const report = await api("GET", "/api/v1/artefacts/cross-reference", { params: { upload_id: crossRefUploadId } });
    renderCrossReferenceCandidates(report.candidates || []);
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

function renderCrossReferenceCandidates(candidates) {
  const bodyEl = document.getElementById("crossref-body");
  if (!candidates.length) {
    bodyEl.innerHTML = "<p class=\"muted\">No candidates found for this upload.</p>";
    return;
  }
  bodyEl.innerHTML = "";
  for (const candidate of candidates) {
    const row = document.createElement("div");
    row.className = "candidate-row";
    const statusClass = candidate.review_status === "accepted" || candidate.review_status === "approved"
      ? "accepted"
      : candidate.review_status === "rejected"
        ? "rejected"
        : "";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(candidate.target_title || candidate.target_id)}</strong>
        <span class="muted small">(${escapeHtml(candidate.target_kind)}, matched: ${
          (candidate.matched_keywords || []).join(", ")
        })</span>
        <div class="candidate-status ${statusClass}">${escapeHtml(candidate.review_status)}</div>
      </div>
      <div class="row-actions"></div>
    `;
    const actions = row.querySelector(".row-actions");
    const acceptBtn = document.createElement("button");
    acceptBtn.type = "button";
    acceptBtn.textContent = "Accept";
    acceptBtn.addEventListener("click", () => reviewCandidate(candidate, "accepted"));
    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "secondary";
    rejectBtn.textContent = "Reject";
    rejectBtn.addEventListener("click", () => reviewCandidate(candidate, "rejected"));
    actions.appendChild(acceptBtn);
    actions.appendChild(rejectBtn);
    bodyEl.appendChild(row);
  }
}

async function reviewCandidate(candidate, reviewStatus) {
  try {
    await api("POST", "/api/v1/artefacts/cross-reference/candidate-review", {
      params: { upload_id: crossRefUploadId },
      json: { target_kind: candidate.target_kind, target_id: candidate.target_id, review_status: reviewStatus },
    });
    await refreshCrossReferenceCandidates();
  } catch (err) {
    document.getElementById("crossref-body").insertAdjacentHTML(
      "afterbegin",
      `<p class="error">${escapeHtml(err.message)}</p>`
    );
  }
}

async function applyCrossReferenceLinks() {
  try {
    await api("POST", "/api/v1/artefacts/cross-reference/apply", { json: { upload_id: crossRefUploadId } });
    await refreshUploads();
    closeModal("crossref-modal");
  } catch (err) {
    document.getElementById("crossref-body").insertAdjacentHTML(
      "afterbegin",
      `<p class="error">${escapeHtml(err.message)}</p>`
    );
  }
}

// --- Zotero: link/unlink account, local status, basic browse ---
// "Basic perusal" only: read-only views over the same GET /api/v1/zotero/*
// routes the CLI's `researchboss zotero` commands use. Never writes inside
// the user's local Zotero directory (see AGENTS.md's Zotero no-write rule) —
// linking only saves API credentials into this workspace's own .env.

function setStatusPill(elId, text, cssClass) {
  const el = document.getElementById(elId);
  el.textContent = text;
  el.className = `candidate-status ${cssClass}`;
}

async function refreshZoteroPanel() {
  await Promise.all([refreshZoteroApiStatus(), refreshZoteroLocalStatus()]);
}

async function refreshZoteroApiStatus() {
  try {
    const report = await api("GET", "/api/v1/zotero/api/test");
    setStatusPill("zotero-api-status", `Connected (user ${report.user_id})`, "connected");
    if (report.key_has_write_access) {
      setStatusPill("zotero-api-status", `Connected (user ${report.user_id}) — key has write access, use read-only`, "error");
    }
  } catch (err) {
    if (/Missing ZOTERO_API_KEY|Missing ZOTERO_USER_ID/.test(err.message)) {
      setStatusPill("zotero-api-status", "Not linked", "not-connected");
    } else {
      setStatusPill("zotero-api-status", `Error: ${err.message}`, "error");
    }
  }
}

async function refreshZoteroLocalStatus() {
  const listEl = document.getElementById("zotero-collections-list");
  const emptyEl = document.getElementById("zotero-collections-empty");
  try {
    const collections = await api("GET", "/api/v1/zotero/local/collections");
    setStatusPill(
      "zotero-local-status",
      collections.length ? `Detected (${collections.length} collection${collections.length === 1 ? "" : "s"})` : "Detected (no collections)",
      "connected"
    );
    renderZoteroCollections(collections);
  } catch (err) {
    setStatusPill("zotero-local-status", "Not detected", "not-connected");
    listEl.innerHTML = "";
    emptyEl.hidden = false;
    emptyEl.textContent = err.message;
  }
}

function renderZoteroCollections(collections) {
  const listEl = document.getElementById("zotero-collections-list");
  const emptyEl = document.getElementById("zotero-collections-empty");
  listEl.innerHTML = "";
  emptyEl.hidden = collections.length > 0;
  for (const collection of collections) {
    const row = document.createElement("div");
    row.className = "zotero-collection-row";
    row.innerHTML = `
      <span>${escapeHtml(collection.name)}</span>
      <span class="muted small">${collection.item_count} item${collection.item_count === 1 ? "" : "s"}</span>
    `;
    listEl.appendChild(row);
  }
}

async function saveZoteroCredentials() {
  const messageEl = document.getElementById("zotero-link-message");
  const apiKeyInput = document.getElementById("zotero-api-key-input");
  const userIdInput = document.getElementById("zotero-user-id-input");
  const apiKey = apiKeyInput.value.trim();
  const userId = userIdInput.value.trim();
  messageEl.hidden = false;
  messageEl.className = "small";
  if (!apiKey || !userId) {
    messageEl.textContent = "Both an API key and a user ID are required.";
    messageEl.classList.add("error");
    return;
  }
  messageEl.textContent = "Linking...";
  try {
    await api("POST", "/api/v1/zotero/api/credentials", { json: { api_key: apiKey, user_id: userId } });
    apiKeyInput.value = "";
    userIdInput.value = "";
    messageEl.textContent = "Linked. Credentials saved to this workspace's .env — not shown again.";
    await refreshZoteroApiStatus();
  } catch (err) {
    messageEl.textContent = err.message;
    messageEl.classList.add("error");
  }
}

async function unlinkZoteroCredentials() {
  const messageEl = document.getElementById("zotero-link-message");
  try {
    await api("DELETE", "/api/v1/zotero/api/credentials");
    messageEl.hidden = false;
    messageEl.className = "small";
    messageEl.textContent = "Unlinked.";
    await refreshZoteroApiStatus();
  } catch (err) {
    messageEl.hidden = false;
    messageEl.className = "small error";
    messageEl.textContent = err.message;
  }
}

async function searchZoteroLocal() {
  const query = document.getElementById("zotero-search-input").value.trim();
  const resultsEl = document.getElementById("zotero-search-results");
  if (!query) {
    resultsEl.innerHTML = "";
    return;
  }
  resultsEl.innerHTML = "<p class=\"muted small\">Searching...</p>";
  try {
    const hits = await api("GET", "/api/v1/zotero/local/search", { params: { query, limit: 20 } });
    if (!hits.length) {
      resultsEl.innerHTML = "<p class=\"muted small\">No matches.</p>";
      return;
    }
    resultsEl.innerHTML = "";
    for (const hit of hits) {
      const row = document.createElement("div");
      row.className = "zotero-search-hit";
      const fileName = (hit.file_path || "").split("/").pop();
      row.innerHTML = `
        <strong>${escapeHtml(fileName || hit.storage_key)}</strong>
        <span class="muted small">(matched: ${escapeHtml((hit.matched_terms || []).join(", "))})</span>
        ${hit.snippet ? `<p class="small muted">${escapeHtml(hit.snippet)}</p>` : ""}
      `;
      resultsEl.appendChild(row);
    }
  } catch (err) {
    resultsEl.innerHTML = `<p class="error small">${escapeHtml(err.message)}</p>`;
  }
}

function setupZoteroPanel() {
  document.getElementById("zotero-link-save-btn").addEventListener("click", saveZoteroCredentials);
  document.getElementById("zotero-link-unlink-btn").addEventListener("click", unlinkZoteroCredentials);
  document.getElementById("zotero-search-btn").addEventListener("click", searchZoteroLocal);
  document.getElementById("zotero-search-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchZoteroLocal();
  });
}

// --- modal plumbing (shared by preview / cross-reference / about) ---

function openModal(id) {
  document.getElementById(id).hidden = false;
}

function closeModal(id) {
  document.getElementById(id).hidden = true;
}

function setupModals() {
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });
  document.querySelectorAll(".modal-overlay").forEach((overlay) => {
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) overlay.hidden = true;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
      if (!overlay.hidden) overlay.hidden = true;
    });
  });
}

// --- wiring ---

function currentWorkspaceFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("workspace") || "";
}

function setWorkspaceInUrl(workspace) {
  const url = new URL(window.location.href);
  url.searchParams.set("workspace", workspace);
  window.history.replaceState({}, "", url.toString());
}

document.addEventListener("DOMContentLoaded", () => {
  setupDropzone();
  setupModals();
  setupZoteroPanel();

  const workspaceInput = document.getElementById("workspace-input");
  const initialWorkspace = currentWorkspaceFromUrl();
  if (initialWorkspace) {
    workspaceInput.value = initialWorkspace;
    loadWorkspace(initialWorkspace);
  }

  document.getElementById("workspace-load").addEventListener("click", () => {
    const workspace = workspaceInput.value.trim();
    if (!workspace) return;
    setWorkspaceInUrl(workspace);
    loadWorkspace(workspace);
  });
  workspaceInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") document.getElementById("workspace-load").click();
  });

  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      window.location.href = "/login";
    }
  });

  document.getElementById("about-link").addEventListener("click", () => openModal("about-modal"));
  document.getElementById("crossref-apply-btn").addEventListener("click", applyCrossReferenceLinks);
});
