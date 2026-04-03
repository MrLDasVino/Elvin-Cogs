// dashboard/static/js/reactionroles.js
(function () {
  "use strict";

  function parseInitialData() {
    try {
      const scripts = document.getElementsByTagName("script");
      for (let i = 0; i < scripts.length; i++) {
        const t = (scripts[i].textContent || "").trim();
        if (!t) continue;
        // The integration replaces /*__INITIAL_DATA__*/ with a JSON literal inside a script tag.
        if (t.startsWith("{") && (t.includes("reaction_messages") || t.includes("preview") || t.includes("message"))) {
          try {
            return JSON.parse(t);
          } catch (e) {
            // ignore parse errors and continue scanning
          }
        }
      }
    } catch (e) {
      console.error("RR: failed to parse initial data", e);
    }
    return {};
  }

  function extractGuildIdFromHash() {
    try {
      const hash = window.location.hash || "";
      // patterns: #/dashboard/<guild_id>/..., #/guild/<guild_id>/...
      const parts = hash.split("/");
      const dashIdx = parts.indexOf("dashboard");
      if (dashIdx !== -1 && parts.length > dashIdx + 1) {
        const gid = parts[dashIdx + 1];
        if (/^\d+$/.test(gid)) return gid;
      }
      const guildIdx = parts.indexOf("guild");
      if (guildIdx !== -1 && parts.length > guildIdx + 1) {
        const gid = parts[guildIdx + 1];
        if (/^\d+$/.test(gid)) return gid;
      }
    } catch (e) {
      // ignore
    }
    return null;
  }

  function currentGuildId() {
    // 1) try hash
    const fromHash = extractGuildIdFromHash();
    if (fromHash) return fromHash;
    // 2) try injected initial data
    const init = parseInitialData();
    if (init) {
      if (init.guild && init.guild.id) return String(init.guild.id);
      if (init.guild_id) return String(init.guild_id);
      if (init.reaction_messages && init.reaction_messages.length) {
        // no guild info available here; can't infer reliably
      }
    }
    // 3) try URL query (if dashboard uses query params)
    try {
      const q = window.location.search || "";
      if (q) {
        const params = new URLSearchParams(q);
        if (params.has("guild_id")) return params.get("guild_id");
        if (params.has("guildId")) return params.get("guildId");
      }
    } catch (e) {}
    return null;
  }

  function buildGuildLink(path) {
    const gid = currentGuildId();
    if (gid) {
      return `#/dashboard/${gid}/third-party/reaction_roles/${path}`;
    }
    return `#/third-party/reaction_roles/${path}`;
  }

  function renderList(data) {
    const container = document.getElementById("rr-list");
    if (!container) return;
    container.innerHTML = "";
    const items = data && data.reaction_messages ? data.reaction_messages : [];
    if (!items.length) {
      container.innerHTML = "<p>No reaction role messages configured.</p>";
      return;
    }
    items.forEach((it) => {
      const div = document.createElement("div");
      div.className = "rr-list-item";
      const header = document.createElement("div");
      header.innerHTML = `<strong>Message ${it.message_id}</strong> in channel ${it.channel_id}`;
      div.appendChild(header);
      const content = document.createElement("div");
      content.textContent = it.content || "";
      div.appendChild(content);
      const mappings = document.createElement("div");
      (it.mappings || []).forEach((m) => {
        const span = document.createElement("span");
        span.className = "rr-mapping";
        span.textContent = `${m.emoji} → ${m.role_id}`;
        mappings.appendChild(span);
      });
      div.appendChild(mappings);
      const actions = document.createElement("div");
      actions.style.marginTop = "8px";
      const previewLink = document.createElement("a");
      previewLink.className = "rr-button";
      previewLink.href = buildGuildLink("preview?message_id=" + it.message_id);
      previewLink.textContent = "Preview";
      const editLink = document.createElement("a");
      editLink.className = "rr-button";
      editLink.href = buildGuildLink("edit?message_id=" + it.message_id);
      editLink.textContent = "Edit";
      actions.appendChild(previewLink);
      actions.appendChild(document.createTextNode(" "));
      actions.appendChild(editLink);
      div.appendChild(actions);
      container.appendChild(div);
    });
  }

  function postFormToParent(payload) {
    // include guild id so dashboard forwards it if needed
    const gid = currentGuildId();
    if (gid) payload.guild_id = gid;
    try {
      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: "third_party_form_submit", payload: payload }, "*");
        return true;
      }
    } catch (e) {
      console.warn("RR: postMessage to parent failed", e);
    }
    return false;
  }

  function handleCreate() {
    const form = document.getElementById("rr-create-form");
    if (!form) return;
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const channel_id = (document.getElementById("channel_id") || {}).value || "";
      const content = (document.getElementById("content") || {}).value || "";
      const mappings = (document.getElementById("mappings") || {}).value || "";
      const payload = {
        channel_id: channel_id.trim(),
        content: content.trim(),
        mappings: mappings.trim(),
      };
      const ok = postFormToParent(payload);
      const res = document.getElementById("rr-create-result");
      if (res) {
        res.textContent = ok ? "Submitted to dashboard." : "Could not submit automatically; copy the JSON payload from the console.";
      }
      if (!ok) console.log("RR create payload:", payload);
    });
  }

  function handleEdit(initial) {
    const form = document.getElementById("rr-edit-form");
    if (!form) return;
    const contentEl = document.getElementById("content");
    const mappingsEl = document.getElementById("mappings");
    if (initial && initial.message) {
      contentEl.value = initial.message.content || "";
      // initial.message.mapping may be an object {emoji: role_id}
      const mappingArr = initial.message.mapping
        ? Object.entries(initial.message.mapping).map(([e, r]) => ({ emoji: e, role_id: r }))
        : [];
      mappingsEl.value = JSON.stringify(mappingArr, null, 2);
    }
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const content = (contentEl.value || "").trim();
      const mappings = (mappingsEl.value || "").trim();
      const payload = {
        content: content,
        mappings: mappings,
        message_id: initial && initial.message_id ? initial.message_id : undefined,
      };
      const ok = postFormToParent(payload);
      const res = document.getElementById("rr-edit-result");
      if (res) {
        res.textContent = ok ? "Submitted to dashboard." : "Could not submit automatically; copy the JSON payload from the console.";
      }
      if (!ok) console.log("RR edit payload:", payload);
    });
  }

  function renderPreview(initial) {
    const container = document.getElementById("rr-preview");
    if (!container) return;
    container.innerHTML = "";
    const preview = initial && initial.preview ? initial.preview : {};
    const content = document.createElement("div");
    content.textContent = preview.content || "";
    container.appendChild(content);
    const mappings = document.createElement("div");
    (preview.mappings || []).forEach((m) => {
      const span = document.createElement("span");
      span.className = "rr-mapping";
      span.textContent = `${m.emoji} → ${m.role_id}`;
      mappings.appendChild(span);
    });
    container.appendChild(mappings);
  }

  // Listen for acks from parent (optional). Some dashboards post back a result message.
  window.addEventListener("message", function (ev) {
    try {
      const data = ev.data || {};
      if (data && data.type === "third_party_form_result") {
        // expected shape: { success: true/false, notifications: [...] }
        const notifs = data.notifications || [];
        if (notifs.length && document.getElementById("rr-create-result")) {
          document.getElementById("rr-create-result").textContent = notifs.map((n) => n.message || JSON.stringify(n)).join("; ");
        }
        if (notifs.length && document.getElementById("rr-edit-result")) {
          document.getElementById("rr-edit-result").textContent = notifs.map((n) => n.message || JSON.stringify(n)).join("; ");
        }
      }
    } catch (e) {
      // ignore
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    const data = parseInitialData();
    if (document.getElementById("rr-list")) renderList(data);
    if (document.getElementById("rr-create-form")) handleCreate();
    if (document.getElementById("rr-edit-form")) handleEdit(data);
    if (document.getElementById("rr-preview")) renderPreview(data);
  });
})();
