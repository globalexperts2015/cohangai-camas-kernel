// Cohort Widget JS - Cohangai Cohort 1
// Vanilla JS, no dependencies. Embed-ready in GHL Membership pages.

(function () {
  "use strict";

  const widget = document.getElementById("cohort-widget");
  if (!widget) return;

  const wizard = widget.dataset.wizard;
  const inputField = widget.dataset.inputField;
  const deployLabel = widget.dataset.deployLabel; // undefined nếu wizard không support deploy

  const inputEl = document.getElementById("cohort-input");
  const tokenEl = document.getElementById("cohort-token");
  const runBtn = document.getElementById("cohort-run-btn");
  const loadingEl = document.getElementById("cohort-loading");
  const errorEl = document.getElementById("cohort-error");
  const outputEl = document.getElementById("cohort-output");
  const outputMdEl = document.getElementById("cohort-output-markdown");
  const saveBtn = document.getElementById("cohort-save-btn");

  // Sprint 15-16 Output → Action UI (multi-action support)
  const deployBtns = document.querySelectorAll(".cohort-deploy-action-btn");
  const deployResultEl = document.getElementById("cohort-deploy-result");
  const deployUrlEl = document.getElementById("cohort-deploy-url");
  const deployCopyBtn = document.getElementById("cohort-deploy-copy");
  const deployOpenLink = document.getElementById("cohort-deploy-open");
  const deployLoadingEl = document.getElementById("cohort-deploy-loading");

  // Track last wizard output for deploy
  let lastWizardOutput = null;
  const LAST_OUTPUT_KEY = `cohort_last_output_${wizard}`;
  try {
    const saved = localStorage.getItem(LAST_OUTPUT_KEY);
    if (saved) lastWizardOutput = JSON.parse(saved);
  } catch (e) {}

  // Load saved token from localStorage
  const SAVED_TOKEN_KEY = "cohort_student_token";
  const savedToken = localStorage.getItem(SAVED_TOKEN_KEY);
  if (savedToken) tokenEl.value = savedToken;

  // Save token on change
  tokenEl.addEventListener("change", () => {
    if (tokenEl.value.trim()) {
      localStorage.setItem(SAVED_TOKEN_KEY, tokenEl.value.trim());
    }
  });

  // Auto-restore last input per wizard
  const INPUT_KEY = `cohort_input_${wizard}`;
  const savedInput = localStorage.getItem(INPUT_KEY);
  if (savedInput) inputEl.value = savedInput;
  inputEl.addEventListener("input", () => {
    localStorage.setItem(INPUT_KEY, inputEl.value);
  });

  // Auto-restore output per wizard
  const OUTPUT_KEY = `cohort_output_${wizard}`;
  const savedOutput = localStorage.getItem(OUTPUT_KEY);
  if (savedOutput) {
    outputMdEl.innerHTML = markdownToHtml(savedOutput);
    collapsifyH2(outputMdEl);
    outputEl.style.display = "block";
  }

  // Convert each H2 + its following siblings (until next H2) into a collapsible section.
  // First section opens by default; rest collapsed. Click H2 to toggle.
  function collapsifyH2(container) {
    const children = Array.from(container.childNodes);
    const h2s = children.filter(n => n.nodeType === 1 && n.tagName === "H2");
    if (h2s.length === 0) return;
    h2s.forEach((h2, idx) => {
      const wrapper = document.createElement("section");
      wrapper.className = "cohort-collapse" + (idx === 0 ? " cohort-collapse-open" : "");
      const header = document.createElement("button");
      header.type = "button";
      header.className = "cohort-collapse-head";
      header.innerHTML = `<span class="cohort-collapse-title">${h2.innerHTML}</span><span class="cohort-collapse-icon">▾</span>`;
      const body = document.createElement("div");
      body.className = "cohort-collapse-body";
      // Collect siblings until next H2
      let sibling = h2.nextSibling;
      const toMove = [];
      while (sibling && !(sibling.nodeType === 1 && sibling.tagName === "H2")) {
        toMove.push(sibling);
        sibling = sibling.nextSibling;
      }
      // Replace h2 with wrapper; move siblings into body
      h2.parentNode.insertBefore(wrapper, h2);
      h2.parentNode.removeChild(h2);
      wrapper.appendChild(header);
      wrapper.appendChild(body);
      toMove.forEach(n => body.appendChild(n));
      header.addEventListener("click", () => {
        wrapper.classList.toggle("cohort-collapse-open");
      });
    });
  }

  runBtn.addEventListener("click", async () => {
    const input = inputEl.value.trim();
    const token = tokenEl.value.trim();

    errorEl.style.display = "none";
    outputEl.style.display = "none";

    if (input.length < 10) {
      showError("Input quá ngắn, cần ≥ 10 ký tự");
      return;
    }
    const isCohort1 = token.startsWith("cohort1-");
    const isWebinar = /^wk2-b[1-3]-[a-f0-9]{8}$/.test(token);
    if (!isCohort1 && !isWebinar) {
      showError("Token sai format. Format: cohort1-yourstudentid-yourhash hoặc wk2-b{1|2|3}-{8hex}");
      return;
    }

    runBtn.disabled = true;
    loadingEl.style.display = "block";

    try {
      const resp = await fetch("/cohort/run-wizard", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Cohort-Student-Token": token,
        },
        body: JSON.stringify({
          wizard: wizard,
          input: input,
        }),
      });

      const data = await resp.json();

      if (!resp.ok || !data.success) {
        showError(data.error || data.detail || `HTTP ${resp.status}`);
        return;
      }

      const markdown = data.markdown || "(no markdown output)";
      outputMdEl.innerHTML = markdownToHtml(markdown);
      collapsifyH2(outputMdEl);
      outputEl.style.display = "block";
      localStorage.setItem(OUTPUT_KEY, markdown);

      // Save full payload cho deploy-action
      lastWizardOutput = data.payload || {};
      try {
        localStorage.setItem(LAST_OUTPUT_KEY, JSON.stringify(lastWizardOutput));
      } catch (e) {}

      // Show deploy buttons (multi-action) nếu wizard support
      if (deployBtns.length > 0) {
        deployBtns.forEach(b => { b.style.display = "inline-block"; });
        if (deployResultEl) deployResultEl.style.display = "none"; // reset
      }

      // Scroll to output
      outputEl.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      showError(`Network error: ${e.message}`);
    } finally {
      runBtn.disabled = false;
      loadingEl.style.display = "none";
    }
  });

  saveBtn.addEventListener("click", async () => {
    const token = tokenEl.value.trim();
    if (!token) {
      showError("Cần token để save progress");
      return;
    }

    try {
      const resp = await fetch("/cohort/save-progress", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Cohort-Student-Token": token,
        },
        body: JSON.stringify({
          wizard: wizard,
          summary: outputMdEl.innerText.substring(0, 500),
        }),
      });

      const data = await resp.json();
      if (data.success) {
        saveBtn.textContent = "✅ Đã lưu progress";
        saveBtn.disabled = true;
      } else {
        showError(data.error || "Save fail");
      }
    } catch (e) {
      showError(`Save error: ${e.message}`);
    }
  });

  // Show deploy buttons on load nếu có cached output + wizard support
  if (deployBtns.length > 0 && lastWizardOutput) {
    deployBtns.forEach(b => { b.style.display = "inline-block"; });
  }

  // Multi-action deploy button handlers
  deployBtns.forEach(btn => {
    btn.addEventListener("click", async () => {
      const token = tokenEl.value.trim();
      if (!token) {
        showError("Cần token để deploy");
        return;
      }
      if (!lastWizardOutput || Object.keys(lastWizardOutput).length === 0) {
        showError("Chưa có wizard output. Chạy wizard trước rồi deploy.");
        return;
      }

      const actionType = btn.dataset.actionType;
      const label = btn.dataset.label || "artifact";

      errorEl.style.display = "none";
      if (deployResultEl) deployResultEl.style.display = "none";
      btn.disabled = true;
      if (deployLoadingEl) {
        deployLoadingEl.style.display = "block";
        deployLoadingEl.querySelector("p").textContent = `Đang tạo ${label}... (5-10 giây)`;
      }

      try {
        const resp = await fetch(`/cohort/wizard/${wizard}/deploy-action`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Cohort-Student-Token": token,
          },
          body: JSON.stringify({
            wizard_output: lastWizardOutput,
            action_type: actionType,
          }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
          showError(data.error || data.detail || `Deploy fail HTTP ${resp.status}`);
          return;
        }

        if (deployUrlEl) deployUrlEl.value = data.url;
        if (deployOpenLink) deployOpenLink.href = data.url;
        if (deployResultEl) {
          deployResultEl.style.display = "block";
          const h3 = deployResultEl.querySelector("h3");
          if (h3) h3.textContent = `✨ ${label} đã sẵn sàng`;
          deployResultEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      } catch (e) {
        showError(`Deploy error: ${e.message}`);
      } finally {
        btn.disabled = false;
        if (deployLoadingEl) deployLoadingEl.style.display = "none";
      }
    });
  });

  // Copy URL handler
  if (deployCopyBtn) {
    deployCopyBtn.addEventListener("click", async () => {
      const url = deployUrlEl.value;
      if (!url) return;
      try {
        await navigator.clipboard.writeText(url);
        const originalText = deployCopyBtn.textContent;
        deployCopyBtn.textContent = "✅ Copied!";
        setTimeout(() => { deployCopyBtn.textContent = originalText; }, 2000);
      } catch (e) {
        // Fallback: select text
        deployUrlEl.select();
        document.execCommand("copy");
      }
    });
  }

  function showError(msg) {
    errorEl.textContent = `❌ ${msg}`;
    errorEl.style.display = "block";
  }

  // Minimal Markdown → HTML converter (vanilla, no marked.js dependency)
  function markdownToHtml(md) {
    let html = md
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Code blocks
    html = html.replace(/```([^`]+)```/g, "<pre><code>$1</code></pre>");

    // Inline code
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Headers
    html = html.replace(/^###### (.+)$/gm, "<h6>$1</h6>");
    html = html.replace(/^##### (.+)$/gm, "<h5>$1</h5>");
    html = html.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

    // Bold + italic
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

    // Lists (- or *)
    html = html.replace(/^[\-\*] (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => "<ul>" + match + "</ul>");

    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, "<oli>$1</oli>");
    html = html.replace(/(<oli>.*<\/oli>\n?)+/g, (match) => "<ol>" + match.replace(/<oli>/g, "<li>").replace(/<\/oli>/g, "</li>") + "</ol>");

    // Tables (simple pipe-syntax)
    html = html.replace(/^\|(.+)\|$/gm, (match, content) => {
      const cells = content.split("|").map((c) => c.trim());
      return "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
    });
    html = html.replace(/(<tr>.*<\/tr>\n?)+/g, (match) => "<table>" + match + "</table>");

    // Paragraphs (double newline)
    html = html
      .split(/\n\n+/)
      .map((para) => {
        para = para.trim();
        if (!para) return "";
        if (para.startsWith("<")) return para;
        return `<p>${para.replace(/\n/g, "<br>")}</p>`;
      })
      .join("\n");

    return html;
  }
})();
